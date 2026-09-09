"""FastAPI dependencies for X-11 authentication and authorization.

This is the smallest stable application-level contract. Downstream modules
consume ``AuthenticatedPrincipal``, the trusted ``TenantContext``, and
permission checks WITHOUT knowing anything about JWT parsing, the JWT
secret, token validation internals, or credential storage.

Responsibilities are separated:
- ``get_authenticated_principal`` — authentication (session cookie OR JWT bearer).
- ``get_trusted_tenant_context`` — X-10 tenant boundary only.
- ``require_permission`` / ``require_tenant_permission`` — authorization only.
"""

from functools import lru_cache
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from arc.db.connection import NotFoundError
from arc.domain.models import TenantContext, User
from arc.security.authorization import AuthorizationService
from arc.security.jwt import AuthenticationError, JwtService
from arc.security.models import AuthenticatedPrincipal, Permission
from arc.security.session import SESSION_COOKIE_NAME, SessionService
from arc.security.settings import SecurityConfigurationError
from arc.security.settings import get_security_settings as load_security_settings

_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=None)
def _security_settings():
    """Cached settings built from the environment at first use."""
    return load_security_settings()


@lru_cache(maxsize=None)
def get_jwt_service() -> JwtService:
    """Return the shared JWT service (internal authentication concern)."""
    return JwtService(_security_settings())


@lru_cache(maxsize=None)
def get_authorization_service() -> AuthorizationService:
    """Return the shared authorization service.

    If the security configuration is invalid, deny everything (fail closed):
    an empty assignment mapping authorizes nobody.
    """
    try:
        return AuthorizationService(_security_settings().application_role_assignments)
    except SecurityConfigurationError:
        return AuthorizationService({})


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str = "Access denied") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def get_authenticated_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedPrincipal:
    """Authenticate the request and return the authenticated principal.

    Supports two authentication methods:
    1. Server-side session cookie (primary for browser UX)
    2. Bearer JWT token (backward compatibility for API clients/tests)

    The principal's ``user_id`` comes exclusively from the validated
    session or JWT ``sub`` claim. Missing, malformed, or invalid
    credentials produce a generic 401.

    Raises:
        HTTPException 401: when credentials are missing or invalid.
    """
    # Try session cookie first (browser UX)
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session_service: SessionService = request.app.state.session_service
        user: User | None = await session_service.validate_session(session_id)
        if user is not None:
            return AuthenticatedPrincipal(user_id=user.id)

    # Fall back to Bearer token (API clients, tests)
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized()

    try:
        user_id = get_jwt_service().decode_access_token(credentials.credentials)
    except (AuthenticationError, SecurityConfigurationError):
        raise _unauthorized()

    return AuthenticatedPrincipal(user_id=user_id)


async def get_trusted_tenant_context(
    tenant_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> TenantContext:
    """Establish the trusted tenant context through the X-10 boundary.

    The client-supplied ``tenant_id`` is request input only. Identity comes
    exclusively from the authenticated principal. The X-10
    ``TenantContextService.create_tenant_context`` verifies the persisted
    membership and derives the membership role from the database.

    Raises:
        HTTPException 400: for invalid tenant context input.
        HTTPException 403: for missing membership / cross-tenant access /
            missing tenant context (fail closed, no data leakage).
    """
    from arc.api.controllers import app_context  # deferred: avoids import cycle

    try:
        return await app_context.tenant_context_service.create_tenant_context(
            tenant_id=tenant_id,
            user_id=principal.user_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant context"
        )
    except NotFoundError:
        raise _forbidden("Access to the requested tenant is denied")


def require_permission(permission: Permission) -> Callable:
    """Return a dependency requiring a GLOBAL permission.

    Global permissions (for example ``tenant:create``) do NOT require a
    tenant context. Authentication alone never grants permission.
    """

    def dependency(
        principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
        authorization: AuthorizationService = Depends(get_authorization_service),
    ) -> AuthenticatedPrincipal:
        if not authorization.has_permission(principal, permission):
            raise _forbidden("Insufficient permissions")
        return principal

    return dependency


def require_tenant_permission(permission: Permission) -> Callable:
    """Return a dependency requiring a trusted tenant context AND a permission.

    Order: authenticated principal -> X-10 trusted tenant context ->
    application role permission check. Any failure denies the request.
    """

    def dependency(
        context: TenantContext = Depends(get_trusted_tenant_context),
        principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
        authorization: AuthorizationService = Depends(get_authorization_service),
    ) -> TenantContext:
        if not authorization.has_permission(principal, permission):
            raise _forbidden("Insufficient permissions")
        return context

    return dependency
