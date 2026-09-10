"""Google OIDC authentication routes.

Endpoints:
- GET /auth/google — Redirect to Google OAuth2 authorization
- GET /auth/callback — Handle Google OAuth2 callback
- GET /auth/workspaces — Return only authorized workspaces for the session user
- POST /auth/logout — Invalidate session and clear cookie

Security properties:
- State parameter validated on callback (CSRF protection)
- Nonce validated on ID token verification (replay protection)
- Session cookie is HttpOnly, SameSite=Lax
- Cookie Secure attribute is derived from APP_ENV:
    APP_ENV=development → Secure=False (allows HTTP local development)
    any other value or unset → Secure=True (production default)
- Post-authentication redirects use FRONTEND_URL (backend origin differs
  from frontend origin in development)
- Unknown Google identities are NOT auto-provisioned
- Disabled users are rejected
- Session invalidation on logout
"""

import logging
import os
import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from arc.db.connection import ArcDatabase
from arc.domain.models import User
from arc.security.google import GoogleAuthError, GoogleOIDCService
from arc.security.session import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, SessionService

logger = logging.getLogger(__name__)

auth_router = APIRouter()


def _cookie_secure() -> bool:
    """Derive the Secure cookie attribute from the runtime environment.

    HTTP (development) requires Secure=False so browsers actually store
    the cookie.  HTTPS (production) requires Secure=True to prevent
    network-level interception.

    The decision is based on ``APP_ENV`` — the same signal already used
    in ``main.py`` to gate development-only routes.  An explicit
    ``APP_ENV=development`` disables Secure; every other value (including
    unset) keeps Secure enabled.
    """
    return os.getenv("APP_ENV") != "development"


_FRONTEND_URL_DEFAULT = "http://localhost:5173"


def _frontend_url() -> str:
    """Return the frontend base URL for browser redirects after authentication.

    After successful authentication, the backend redirects the browser to
    ``{FRONTEND_URL}/app``. On authentication failure, the redirect goes
    to ``{FRONTEND_URL}/login?error=...``.

    The backend runs on a different origin (port 8000) than the frontend
    (port 5173), so relative URLs like ``/app`` would resolve to the
    backend which has no frontend routes.
    """
    return os.getenv("FRONTEND_URL", _FRONTEND_URL_DEFAULT)


# Google OIDC session cookie keys (stored in the session cookie, not DB)
_STATE_KEY = "google_state"
_NONCE_KEY = "google_nonce"


def _get_google_service(request: Request) -> GoogleOIDCService:
    """Get the Google OIDC service from app state."""
    return request.app.state.google_oidc_service


def _get_session_service(request: Request) -> SessionService:
    """Get the session service from app state."""
    return request.app.state.session_service


def _get_db(request: Request) -> ArcDatabase:
    """Get the database from app state."""
    return request.app.state.db


def _set_session_cookie(response: Response, session_id: str, max_age: int) -> None:
    """Set the session cookie on the response."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def _set_csrf_cookie(response: Response, csrf_token: str, max_age: int) -> None:
    """Set the CSRF token cookie on the response.

    This cookie is NOT HttpOnly so JavaScript can read it and send it
    in a custom header for CSRF protection on state-changing requests.
    """
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=max_age,
        httponly=False,  # JavaScript needs to read this
        secure=_cookie_secure(),
        samesite="strict",  # CSRF token should only be sent on same-site
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def _clear_csrf_cookie(response: Response) -> None:
    """Clear the CSRF token cookie."""
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        httponly=False,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )


async def _get_current_user(request: Request) -> Optional[User]:
    """Extract the current user from the session cookie.

    Returns None if no valid session exists. Never raises exceptions.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None

    session_service = _get_session_service(request)
    return await session_service.validate_session(session_id)


@auth_router.get("/auth/google")
async def google_login(request: Request) -> RedirectResponse:
    """Redirect to Google OAuth2 authorization endpoint.

    Generates a random state (CSRF) and nonce (replay prevention),
    stores them in a short-lived cookie, and redirects to Google.
    """
    google_service = _get_google_service(request)
    if google_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google authentication is not configured",
        )

    state = google_service.generate_state()
    nonce = google_service.generate_nonce()

    auth_url = google_service.build_authorization_url(state, nonce)

    # Store state and nonce in a temporary cookie for validation on callback
    # This cookie is short-lived and cleared after callback
    response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    cookie_max_age = 600  # 10 minutes
    response.set_cookie(
        key="arc_oidc_state",
        value=state,
        max_age=cookie_max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key="arc_oidc_nonce",
        value=nonce,
        max_age=cookie_max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )

    return response


@auth_router.get("/auth/callback")
async def google_callback(
    request: Request,
    response: Response,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
) -> RedirectResponse:
    """Handle Google OAuth2 callback.

    Validates the state parameter, exchanges the authorization code for
    tokens, verifies the ID token, and maps the Google identity to an
    Arc user. Creates a server-side session and sets the session cookie.
    """
    # Check for Google errors
    if error:
        logger.warning("Google OAuth2 error: %s", error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication failed",
        )

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code or state",
        )

    # Validate state (CSRF protection)
    stored_state = request.cookies.get("arc_oidc_state")
    if not stored_state or not secrets.compare_digest(stored_state, state):
        logger.warning("State mismatch: possible CSRF attack")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid authentication state",
        )

    # Get nonce for validation (MUST exist — fail closed if missing)
    nonce = request.cookies.get("arc_oidc_nonce")
    if not nonce:
        logger.warning("Missing OIDC nonce cookie — possible replay attack")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid authentication state",
        )

    google_service = _get_google_service(request)
    session_service = _get_session_service(request)

    try:
        # Exchange code for tokens
        token_response = await google_service.exchange_code(code)
        id_token = token_response.get("id_token")
        if not id_token:
            raise GoogleAuthError("No ID token in response")

        # Verify ID token and extract identity
        identity = await google_service.verify_id_token(id_token, nonce)

        # Map Google identity to Arc user (does NOT auto-provision)
        user = await google_service.find_or_link_user(identity)
        if user is None:
            # Unknown identity or disabled user — redirect with error
            logger.warning(
                "Authentication failed: Google identity not linked to Arc user. sub=%s email=%s",
                identity.sub,
                identity.email,
            )
            # Redirect to login with error message
            error_url = f"{_frontend_url()}/login?error=access_denied"
            resp = RedirectResponse(url=error_url, status_code=status.HTTP_302_FOUND)
            _clear_session_cookie(resp)
            # Clear OIDC cookies
            resp.delete_cookie(
                "arc_oidc_state",
                httponly=True,
                secure=_cookie_secure(),
                samesite="lax",
                path="/",
            )
            resp.delete_cookie(
                "arc_oidc_nonce",
                httponly=True,
                secure=_cookie_secure(),
                samesite="lax",
                path="/",
            )
            return resp

        # Create server-side session
        user_agent = request.headers.get("user-agent")
        ip_address = request.client.host if request.client else None
        session = await session_service.create_session(
            user,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        # Structured security event: successful login
        logger.info(
            "auth_login_success user_id=%s ip=%s user_agent=%s",
            user.id,
            ip_address or "unknown",
            (user_agent or "unknown")[:100],
        )

        # Set session cookie and CSRF cookie, then redirect to app
        resp = RedirectResponse(url=f"{_frontend_url()}/app", status_code=status.HTTP_302_FOUND)
        # Derive cookie max_age from the actual session lifetime so cookies
        # cannot disagree with the server-side session expiry.
        session_max_age = int((session.expires_at - session.created_at).total_seconds())
        _set_session_cookie(resp, session.id, max_age=session_max_age)
        _set_csrf_cookie(resp, session.csrf_token, max_age=session_max_age)

        # Clear OIDC cookies
        resp.delete_cookie(
            "arc_oidc_state",
            httponly=True,
            secure=_cookie_secure(),
            samesite="lax",
            path="/",
        )
        resp.delete_cookie(
            "arc_oidc_nonce",
            httponly=True,
            secure=_cookie_secure(),
            samesite="lax",
            path="/",
        )

        return resp

    except GoogleAuthError as e:
        # Structured security event: failed authentication
        ip = request.client.host if request.client else "unknown"
        logger.warning("auth_login_failed error=%s ip=%s", type(e).__name__, ip)
        error_url = f"{_frontend_url()}/login?error=auth_failed"
        resp = RedirectResponse(url=error_url, status_code=status.HTTP_302_FOUND)
        _clear_session_cookie(resp)
        resp.delete_cookie(
            "arc_oidc_state",
            httponly=True,
            secure=_cookie_secure(),
            samesite="lax",
            path="/",
        )
        resp.delete_cookie(
            "arc_oidc_nonce",
            httponly=True,
            secure=_cookie_secure(),
            samesite="lax",
            path="/",
        )
        return resp


@auth_router.get("/auth/workspaces")
async def get_workspaces(
    request: Request,
) -> Dict[str, Any]:
    """Return only the authorized workspaces for the session user.

    This endpoint NEVER returns the global tenant inventory. It returns
    ONLY tenants for which the authenticated user has a valid membership.
    """
    user = await _get_current_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    db = _get_db(request)
    memberships = await db.get_memberships_for_user(user.id)
    tenants = await db.get_tenants_for_user(user.id)

    # Build tenant lookup
    tenant_map = {t.id: t for t in tenants}

    workspaces = []
    for m in memberships:
        tenant = tenant_map.get(m.tenant_id)
        if tenant:
            workspaces.append(
                {
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "role": m.role.value,
                }
            )

    return {
        "workspaces": workspaces,
        "count": len(workspaces),
    }


@auth_router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
) -> Dict[str, str]:
    """Invalidate the session and clear the session cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session_service = _get_session_service(request)
        await session_service.invalidate_session(session_id)

    # Structured security event: logout
    logger.info(
        "auth_logout ip=%s",
        request.client.host if request.client else "unknown",
    )

    _clear_session_cookie(response)
    _clear_csrf_cookie(response)
    return {"status": "ok"}


@auth_router.post("/auth/logout-all")
async def logout_all(
    request: Request,
    response: Response,
) -> Dict[str, str]:
    """Invalidate ALL sessions for the current user."""
    user = await _get_current_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    session_service = _get_session_service(request)
    await session_service.invalidate_all_sessions(user.id)

    _clear_session_cookie(response)
    _clear_csrf_cookie(response)
    return {"status": "ok"}
