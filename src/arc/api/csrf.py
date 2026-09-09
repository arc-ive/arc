"""CSRF protection middleware for Arc.

Implements the Double-Submit Cookie Pattern for CSRF protection:
- Session cookie (HttpOnly) contains the session ID
- CSRF cookie (non-HttpOnly) contains the CSRF token
- Server stores the CSRF token in the session
- Client sends the CSRF token in a custom header (X-CSRF-Token)
- Server validates the token matches what's stored in the session

Bearer token clients are exempt from CSRF validation because:
- Bearer tokens are not automatically attached by the browser
- Bearer tokens must be explicitly set in the Authorization header
- This prevents CSRF attacks that rely on automatic cookie attachment
"""

import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from arc.security.session import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, SessionService

logger = logging.getLogger(__name__)

# HTTP methods that require CSRF protection
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Paths that are exempt from CSRF protection (authentication endpoints)
CSRF_EXEMPT_PATHS = frozenset(
    {
        "/auth/google",
        "/auth/callback",
        "/health",
    }
)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware to validate CSRF tokens on state-changing requests.

    This middleware implements the Double-Submit Cookie Pattern:
    1. Client reads the CSRF token from the non-HttpOnly cookie
    2. Client sends the CSRF token in the X-CSRF-Token header
    3. Server validates the token matches what's stored in the session

    Bearer token clients are exempt from CSRF validation.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only protect state-changing methods
        if request.method not in STATE_CHANGING_METHODS:
            return await call_next(request)

        # Exempt certain paths
        if request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # Check if this is a Bearer token request (API client)
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            # Bearer token clients are exempt from CSRF validation
            return await call_next(request)

        # Get the session ID from the cookie
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if not session_id:
            # No session cookie - not authenticated, CSRF doesn't apply
            return await call_next(request)

        # Get the CSRF token from the cookie
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        if not csrf_cookie:
            logger.warning(
                "csrf_cookie_missing session=%s ip=%s",
                session_id[:8],
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token cookie missing"},
            )

        # Get the CSRF token from the header
        csrf_header = request.headers.get("x-csrf-token")
        if not csrf_header:
            logger.warning(
                "csrf_header_missing session=%s ip=%s",
                session_id[:8],
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token header missing"},
            )

        # Validate that the cookie and header match
        if csrf_cookie != csrf_header:
            logger.warning(
                "csrf_token_mismatch session=%s ip=%s",
                session_id[:8],
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token mismatch"},
            )

        # Validate the CSRF token against the session
        session_service: SessionService = request.app.state.session_service
        is_valid = await session_service.validate_csrf_token(session_id, csrf_header)
        if not is_valid:
            logger.warning(
                "csrf_token_invalid session=%s ip=%s",
                session_id[:8],
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid CSRF token"},
            )

        # CSRF validation passed
        return await call_next(request)
