"""Development-only reference-user authentication endpoint.

Allows developers to genuinely authenticate as seeded reference users
without requiring real Google accounts. Mounted ONLY when
``APP_ENV=development`` (see ``arc.main``).

Security properties:
- Only accepts known reference user IDs (hardcoded allowlist)
- Creates a real server-side session via SessionService
- Sets the same session/CSRF cookies as Google OIDC
- CSRF exempt (no prior session exists to protect)
- Never mounted in production
- No password, no bypass, no weakened auth
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from arc.api.auth_routes import _set_csrf_cookie, _set_session_cookie
from arc.api.schemas import AUTHENTICATED_ERROR_RESPONSES
from arc.db.connection import NotFoundError
from arc.security.session import SessionService

logger = logging.getLogger(__name__)

dev_auth_router = APIRouter(prefix="/internal/dev/auth")


# ---------------------------------------------------------------------------
# Reference user allowlist
# ---------------------------------------------------------------------------


def _tenant(tenant_id: str, tenant_name: str, role: str) -> Dict[str, str]:
    return {"tenant_id": tenant_id, "tenant_name": tenant_name, "role": role}


_REFERENCE_USERS: List[Dict[str, Any]] = [
    {
        "user_id": "ref-platform-admin",
        "display_name": "Platform Administrator",
        "role": "platform_administrator",
        "tenants": [],
    },
    # Acme Technologies
    {
        "user_id": "ref-acme-technologies-company-admin",
        "display_name": "Company Admin",
        "role": "company_administrator",
        "tenants": [_tenant("ref-acme-technologies", "Acme Technologies", "owner")],
    },
    {
        "user_id": "ref-acme-technologies-ops-user",
        "display_name": "Ops User",
        "role": "operations_user",
        "tenants": [_tenant("ref-acme-technologies", "Acme Technologies", "member")],
    },
    {
        "user_id": "ref-acme-technologies-employee-1",
        "display_name": "Employee 1",
        "role": "employee",
        "tenants": [_tenant("ref-acme-technologies", "Acme Technologies", "member")],
    },
    {
        "user_id": "ref-acme-technologies-employee-2",
        "display_name": "Employee 2",
        "role": "employee",
        "tenants": [_tenant("ref-acme-technologies", "Acme Technologies", "viewer")],
    },
    # Nova Systems
    {
        "user_id": "ref-nova-systems-company-admin",
        "display_name": "Company Admin",
        "role": "company_administrator",
        "tenants": [_tenant("ref-nova-systems", "Nova Systems", "owner")],
    },
    {
        "user_id": "ref-nova-systems-ops-user",
        "display_name": "Ops User",
        "role": "operations_user",
        "tenants": [_tenant("ref-nova-systems", "Nova Systems", "member")],
    },
    {
        "user_id": "ref-nova-systems-employee-1",
        "display_name": "Employee 1",
        "role": "employee",
        "tenants": [_tenant("ref-nova-systems", "Nova Systems", "member")],
    },
    {
        "user_id": "ref-nova-systems-employee-2",
        "display_name": "Employee 2",
        "role": "employee",
        "tenants": [_tenant("ref-nova-systems", "Nova Systems", "viewer")],
    },
    # Vertex Solutions
    {
        "user_id": "ref-vertex-solutions-company-admin",
        "display_name": "Company Admin",
        "role": "company_administrator",
        "tenants": [_tenant("ref-vertex-solutions", "Vertex Solutions", "owner")],
    },
    {
        "user_id": "ref-vertex-solutions-ops-user",
        "display_name": "Ops User",
        "role": "operations_user",
        "tenants": [_tenant("ref-vertex-solutions", "Vertex Solutions", "member")],
    },
    {
        "user_id": "ref-vertex-solutions-employee-1",
        "display_name": "Employee 1",
        "role": "employee",
        "tenants": [_tenant("ref-vertex-solutions", "Vertex Solutions", "member")],
    },
    {
        "user_id": "ref-vertex-solutions-employee-2",
        "display_name": "Employee 2",
        "role": "employee",
        "tenants": [_tenant("ref-vertex-solutions", "Vertex Solutions", "viewer")],
    },
    # Northstar Digital
    {
        "user_id": "ref-northstar-digital-company-admin",
        "display_name": "Company Admin",
        "role": "company_administrator",
        "tenants": [_tenant("ref-northstar-digital", "Northstar Digital", "owner")],
    },
    {
        "user_id": "ref-northstar-digital-ops-user",
        "display_name": "Ops User",
        "role": "operations_user",
        "tenants": [_tenant("ref-northstar-digital", "Northstar Digital", "member")],
    },
    {
        "user_id": "ref-northstar-digital-employee-1",
        "display_name": "Employee 1",
        "role": "employee",
        "tenants": [_tenant("ref-northstar-digital", "Northstar Digital", "member")],
    },
    {
        "user_id": "ref-northstar-digital-employee-2",
        "display_name": "Employee 2",
        "role": "employee",
        "tenants": [_tenant("ref-northstar-digital", "Northstar Digital", "viewer")],
    },
]

_ALLOWED_USER_IDS = frozenset(u["user_id"] for u in _REFERENCE_USERS)


# ---------------------------------------------------------------------------
# Dev login personas (role-level selector)
# ---------------------------------------------------------------------------

_DEV_PERSONAS: List[Dict[str, Any]] = [
    {
        "persona": "Platform Admin",
        "description": "Global platform administrator with full permissions",
        "user_id": "ref-platform-admin",
    },
    {
        "persona": "Tenant Admin",
        "description": "Company administrator for Acme Technologies",
        "user_id": "ref-acme-technologies-company-admin",
    },
    {
        "persona": "Employee",
        "description": "Employee with knowledge:read access at Acme Technologies",
        "user_id": "ref-acme-technologies-employee-1",
    },
    {
        "persona": "Viewer",
        "description": "Viewer with read-only access at Acme Technologies",
        "user_id": "ref-acme-technologies-employee-2",
    },
]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class DevLoginRequest(BaseModel):
    user_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@dev_auth_router.get("/reference-users")
async def list_reference_users() -> Dict[str, Any]:
    """List available reference users for development login.

    Returns the full allowlist with display names, roles, and tenant
    memberships so the frontend can render a useful selector.
    """
    return {"users": _REFERENCE_USERS}


@dev_auth_router.get("/reference-personas")
async def list_reference_personas() -> Dict[str, Any]:
    """List role-level personas for the primary dev login selector.

    Returns a small set of role-level personas, each mapped to a
    representative seeded reference user. The frontend displays these
    as the primary development login options.
    """
    return {"personas": _DEV_PERSONAS}


@dev_auth_router.post(
    "/login",
    responses={403: AUTHENTICATED_ERROR_RESPONSES[403]},
)
async def dev_login(
    body: DevLoginRequest,
    request: Request,
    response: Response,
) -> Dict[str, Any]:
    """Authenticate as a seeded reference user (development-only).

    Creates a real server-side session and sets the same session/CSRF
    cookies as the Google OIDC flow. The session is indistinguishable
    from a normally authenticated session.

    Security:
    - Only accepts user IDs in the reference allowlist
    - Fails closed on unknown user IDs
    - Creates a real session via SessionService
    - Sets real cookies with the same security attributes
    """
    user_id = body.user_id

    if user_id not in _ALLOWED_USER_IDS:
        logger.warning(
            "dev_auth_login_rejected user_id=%s ip=%s",
            user_id,
            _client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unknown reference user",
        )

    # Look up the user in the database (must exist from reference data seeding)
    db = request.app.state.db
    try:
        user = await db.get_user(user_id)
    except NotFoundError:
        logger.error(
            "dev_auth_login_error user_id=%s reason=user_not_in_database",
            user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Reference user not found in database",
        )

    if user.status != "active":
        logger.warning(
            "dev_auth_login_rejected user_id=%s reason=user_inactive",
            user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reference user is not active",
        )

    # Create a real server-side session (same as Google OIDC)
    session_service: SessionService = request.app.state.session_service
    user_agent = request.headers.get("user-agent")
    ip_address = _client_ip(request)

    session = await session_service.create_session(
        user,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    logger.info(
        "dev_auth_login_success user_id=%s ip=%s",
        user_id,
        ip_address or "unknown",
    )

    # Set the same session/CSRF cookies as Google OIDC
    session_max_age = int((session.expires_at - session.created_at).total_seconds())
    _set_session_cookie(response, session.id, max_age=session_max_age)
    _set_csrf_cookie(response, session.csrf_token, max_age=session_max_age)

    return {
        "status": "ok",
        "user_id": user_id,
        "session_id": session.id,
    }


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
