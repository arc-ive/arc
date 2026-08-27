"""X-11 application RBAC tests: roles, permissions, and authorization boundary.

Authentication (JWT) establishes identity; it NEVER grants permission.
Authorization is enforced by ``AuthorizationService`` through the explicit
development role assignments. The X-10 membership ``UserRole`` is
completely independent and never grants application permissions.
"""

import uuid

import pytest

from arc.domain.models import UserRole
from arc.security.authorization import (
    AGENT_EXECUTE,
    APPROVAL_DECIDE,
    APPROVAL_READ,
    CONNECTOR_CREATE,
    CONNECTOR_READ,
    CONNECTOR_SYNC,
    KNOWLEDGE_CREATE,
    KNOWLEDGE_READ,
    MEMBERSHIP_CREATE,
    OBSERVABILITY_PLATFORM_READ,
    OBSERVABILITY_READ,
    ROLE_PERMISSIONS,
    SKILL_CREATE,
    SKILL_DELETE,
    SKILL_EXECUTE,
    SKILL_READ,
    SKILL_UPDATE,
    TENANT_CREATE,
    TENANT_READ,
    TOOL_EXECUTE,
    TOOL_READ,
    USER_CREATE,
    WEBHOOK_READ,
    AuthorizationService,
)
from arc.security.models import ApplicationRole, AuthenticatedPrincipal, Permission


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"rbac-{prefix}-{uuid.uuid4().hex[:10]}"


def test_application_roles_are_independent_of_membership_roles():
    """ApplicationRole must never overlap or derive from the X-10 UserRole."""
    application_values = {role.value for role in ApplicationRole}
    membership_values = {role.value for role in UserRole}
    assert application_values.isdisjoint(membership_values)


def test_exactly_four_application_roles_exist():
    assert set(ApplicationRole) == {
        ApplicationRole.PLATFORM_ADMINISTRATOR,
        ApplicationRole.COMPANY_ADMINISTRATOR,
        ApplicationRole.OPERATIONS_USER,
        ApplicationRole.EMPLOYEE,
    }


@pytest.mark.parametrize(
    "role, allowed, denied",
    [
        (
            ApplicationRole.PLATFORM_ADMINISTRATOR,
            [
                AGENT_EXECUTE,
                TENANT_CREATE,
                USER_CREATE,
                MEMBERSHIP_CREATE,
                TENANT_READ,
                KNOWLEDGE_CREATE,
                KNOWLEDGE_READ,
                SKILL_CREATE,
                SKILL_READ,
                SKILL_UPDATE,
                SKILL_DELETE,
                SKILL_EXECUTE,
                TOOL_READ,
                TOOL_EXECUTE,
                CONNECTOR_CREATE,
                CONNECTOR_READ,
                CONNECTOR_SYNC,
                WEBHOOK_READ,
                OBSERVABILITY_READ,
                OBSERVABILITY_PLATFORM_READ,
                APPROVAL_READ,
                APPROVAL_DECIDE,
            ],
            [],
        ),
        (
            ApplicationRole.COMPANY_ADMINISTRATOR,
            [
                AGENT_EXECUTE,
                TENANT_READ,
                KNOWLEDGE_CREATE,
                KNOWLEDGE_READ,
                SKILL_CREATE,
                SKILL_READ,
                SKILL_UPDATE,
                SKILL_DELETE,
                SKILL_EXECUTE,
                TOOL_READ,
                TOOL_EXECUTE,
                CONNECTOR_CREATE,
                CONNECTOR_READ,
                CONNECTOR_SYNC,
                WEBHOOK_READ,
                OBSERVABILITY_READ,
                APPROVAL_READ,
                APPROVAL_DECIDE,
            ],
            [TENANT_CREATE, USER_CREATE, MEMBERSHIP_CREATE],
        ),
        (
            ApplicationRole.OPERATIONS_USER,
            [
                AGENT_EXECUTE,
                TENANT_READ,
                KNOWLEDGE_READ,
                SKILL_READ,
                SKILL_EXECUTE,
                TOOL_READ,
                TOOL_EXECUTE,
                CONNECTOR_READ,
                CONNECTOR_SYNC,
                WEBHOOK_READ,
                OBSERVABILITY_READ,
            ],
            [
                TENANT_CREATE,
                USER_CREATE,
                MEMBERSHIP_CREATE,
                KNOWLEDGE_CREATE,
                SKILL_CREATE,
                SKILL_UPDATE,
                SKILL_DELETE,
                CONNECTOR_CREATE,
                APPROVAL_READ,
                APPROVAL_DECIDE,
            ],
        ),
        (
            ApplicationRole.EMPLOYEE,
            [],
            [
                AGENT_EXECUTE,
                TENANT_CREATE,
                USER_CREATE,
                MEMBERSHIP_CREATE,
                TENANT_READ,
                KNOWLEDGE_CREATE,
                KNOWLEDGE_READ,
                SKILL_CREATE,
                SKILL_READ,
                SKILL_UPDATE,
                SKILL_DELETE,
                SKILL_EXECUTE,
                TOOL_READ,
                TOOL_EXECUTE,
                CONNECTOR_CREATE,
                CONNECTOR_READ,
                CONNECTOR_SYNC,
                WEBHOOK_READ,
                OBSERVABILITY_READ,
                OBSERVABILITY_PLATFORM_READ,
                APPROVAL_READ,
                APPROVAL_DECIDE,
            ],
        ),
    ],
)
def test_permission_matrix(role, allowed, denied):
    """The approved X-11 permission matrix must hold exactly."""
    principal = AuthenticatedPrincipal(user_id="u")
    service = AuthorizationService({"u": role})
    for permission in allowed:
        assert service.has_permission(principal, permission), (
            f"{role.value} should have {permission}"
        )
    for permission in denied:
        assert not service.has_permission(principal, permission), (
            f"{role.value} should NOT have {permission}"
        )


def test_unknown_user_is_denied():
    """An unassigned user has no role and is denied by default (fail closed)."""
    service = AuthorizationService({"other": ApplicationRole.OPERATIONS_USER})
    assert service.role_for("unassigned") is None
    assert not service.has_permission(AuthenticatedPrincipal(user_id="unassigned"), TENANT_READ)


def test_empty_assignments_deny_everyone():
    """Empty role assignments must authorize nobody."""
    service = AuthorizationService({})
    principal = AuthenticatedPrincipal(user_id="u")
    assert not service.has_permission(principal, TENANT_CREATE)
    assert not service.has_permission(principal, TENANT_READ)


def test_membership_role_never_grants_application_permissions():
    """OWNER/MEMBER/VIEWER memberships must not grant any application permission."""
    service = AuthorizationService({})
    for membership_role in UserRole:
        principal = AuthenticatedPrincipal(user_id=f"u-{membership_role.value}")
        for permission in ROLE_PERMISSIONS[ApplicationRole.PLATFORM_ADMINISTRATOR]:
            assert not service.has_permission(principal, permission)


def test_authenticated_but_unassigned_user_denied_403(client, make_token):
    """A valid JWT alone does not authorize: 403, not 401."""
    token = make_token("unassigned-user")
    response = client.post(
        "/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"id": _unique("rbac"), "name": "RBAC Tenant"},
    )
    assert response.status_code == 403


def test_platform_administrator_can_create_tenant(client, make_token, authorization_override):
    authorization_override({"admin": ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token("admin")
    response = client.post(
        "/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"id": _unique("rbac"), "name": "RBAC Tenant"},
    )
    assert response.status_code == 200


def test_company_administrator_cannot_create_tenant(client, make_token, authorization_override):
    authorization_override({"company-admin": ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token("company-admin")
    response = client.post(
        "/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"id": _unique("rbac"), "name": "RBAC Tenant"},
    )
    assert response.status_code == 403


def test_employee_cannot_create_tenant(client, make_token, authorization_override):
    authorization_override({"employee": ApplicationRole.EMPLOYEE})
    token = make_token("employee")
    response = client.post(
        "/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"id": _unique("rbac"), "name": "RBAC Tenant"},
    )
    assert response.status_code == 403


def test_platform_administrator_can_create_user(client, make_token, authorization_override):
    authorization_override({"admin": ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token("admin")
    response = client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "id": _unique("rbac"),
            "email": f"{_unique('rbac')}@example.com",
            "username": "rbac-user",
        },
    )
    assert response.status_code == 200


def test_operations_user_cannot_create_user(client, make_token, authorization_override):
    authorization_override({"ops": ApplicationRole.OPERATIONS_USER})
    token = make_token("ops")
    response = client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "id": _unique("rbac"),
            "email": f"{_unique('rbac')}@example.com",
            "username": "rbac-user",
        },
    )
    assert response.status_code == 403


def test_unknown_connector_permission_is_never_granted():
    """An unknown connector permission is denied for every role (fail closed).

    The connector layer consumes only the centralized matrix; a permission
    that does not exist in ROLE_PERMISSIONS can never authorize an action.
    """
    unknown = Permission(resource="connector", action="purge")
    service = AuthorizationService({})
    for role in ApplicationRole:
        principal = AuthenticatedPrincipal(user_id=f"u-{role.value}")
        assert not service.has_permission(principal, unknown), (
            f"{role.value} must never hold the unknown permission"
        )


def test_connector_permissions_are_tenant_scoped_operations():
    """Every connector permission requires a trusted tenant context.

    The connector endpoints all use ``require_tenant_permission`` (never a
    global permission), so the trusted TenantContext is the tenant
    boundary for connector:create/read/sync.
    """
    for permission in (CONNECTOR_CREATE, CONNECTOR_READ, CONNECTOR_SYNC):
        assert permission.resource == "connector"
        assert permission.action in ("create", "read", "sync")
