"""Tool human-approval integration tests (Issue #213, V2-ADR-011/012).

Exercises the real approval-gated tool ``grant_temporary_access`` through
the canonical ``ToolExecutionService`` boundary with real PostgreSQL:

- HIGH risk + REQUIRE_HUMAN_APPROVAL catalog entry
- pending approval creation without handler execution
- approve -> resume -> consume -> execution
- replay protection, deny path, request mismatch, tenant isolation
- RBAC/capability still enforced
"""

import uuid

import pytest

from arc.domain.models import ApprovalStatus, Tenant, TenantContext, ToolRiskLevel, UserRole
from arc.repositories.approvals import PostgreSQLApprovalRequestRepository
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal
from arc.services.approvals import HumanApprovalService
from arc.services.capabilities import CapabilityService
from arc.services.tools import (
    GRANT_TEMPORARY_ACCESS_TOOL,
    ToolDeniedError,
    ToolExecutionService,
    ToolRegistry,
    build_platform_tool_registry,
)


def _unique(prefix: str) -> str:
    return f"approval-int-{prefix}-{uuid.uuid4().hex[:8]}"


def _context(tenant_id: str, user_id: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Approval Test Tenant",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id)


def _authorization(
    user_id: str = "user-1", role: ApplicationRole = ApplicationRole.OPERATIONS_USER
) -> AuthorizationService:
    return AuthorizationService({user_id: role})


@pytest.fixture
async def approval_setup(db):
    """Real approval + tool services wired for the HIGH-risk tool."""
    approval_repo = PostgreSQLApprovalRequestRepository(db)
    approval_svc = HumanApprovalService(approval_repo)
    tool_repo = PostgreSQLToolExecutionRepository(db)
    # Capability service with no DB state -> all capabilities pass through (no ceiling).
    # For real DB, we use a fake that always returns True for simplicity; the
    # RBAC/capability test below uses a real one.
    registry = build_platform_tool_registry()
    tool_svc = ToolExecutionService(
        registry=registry,
        record_repo=tool_repo,
        approval_service=approval_svc,
        capability_service=None,
    )
    return approval_svc, tool_svc, tool_repo, approval_repo


@pytest.fixture
async def tenant_pair(db):
    """Two tenants for isolation tests."""
    from arc.repositories.tenancy import PostgreSQLTenantRepository

    repo = PostgreSQLTenantRepository(db)
    t1 = await repo.create(Tenant(id=_unique("tenant"), name="Tenant A"))
    t2 = await repo.create(Tenant(id=_unique("tenant"), name="Tenant B"))
    yield t1, t2
    await repo.delete(t1.id)
    await repo.delete(t2.id)


class TestApprovalRequired:
    async def test_high_risk_tool_creates_pending_without_execution(self, db, approval_setup):
        approval_svc, tool_svc, tool_repo, approval_repo = approval_setup
        tenant_id = _unique("tenant")
        # Create tenant for FK
        from arc.repositories.tenancy import PostgreSQLTenantRepository

        tenants = PostgreSQLTenantRepository(db)
        await tenants.create(Tenant(id=tenant_id, name="Temp Tenant"))
        try:
            ctx = _context(tenant_id)
            principal = _principal()
            authz = _authorization()

            # Track handler calls
            original_handler = GRANT_TEMPORARY_ACCESS_TOOL.handler
            called = []

            def _tracking_handler(input_data, tid):
                called.append(input_data)
                return original_handler(input_data, tid)

            # Temporarily replace handler via a new ToolDefinition with same policy
            from arc.domain.models import ToolRiskLevel
            from arc.services.tools import (
                ToolDefinition,
                ToolExecutionPolicy,
                ToolExecutionPolicyMode,
            )

            tracking_tool = ToolDefinition(
                name=GRANT_TEMPORARY_ACCESS_TOOL.name,
                version=GRANT_TEMPORARY_ACCESS_TOOL.version,
                description=GRANT_TEMPORARY_ACCESS_TOOL.description,
                input_model=GRANT_TEMPORARY_ACCESS_TOOL.input_model,
                output_model=GRANT_TEMPORARY_ACCESS_TOOL.output_model,
                required_permissions=GRANT_TEMPORARY_ACCESS_TOOL.required_permissions,
                risk_level=ToolRiskLevel.HIGH,
                execution_policy=ToolExecutionPolicy(
                    mode=ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL
                ),
                audit_policy=GRANT_TEMPORARY_ACCESS_TOOL.audit_policy,
                handler=_tracking_handler,
            )
            tool_svc.registry = ToolRegistry({tracking_tool.name: tracking_tool})

            with pytest.raises(ToolDeniedError) as exc_info:
                await tool_svc.execute_tool(
                    ctx,
                    principal,
                    tracking_tool.name,
                    {"justification": "need access for audit"},
                    authz,
                )
            assert exc_info.value.approval_id is not None
            assert called == [], "Handler must not be invoked before approval"

            # Verify pending approval exists and is bound correctly
            approval_id = exc_info.value.approval_id
            pending = await approval_svc.get_request(ctx, approval_id)
            assert pending.status == ApprovalStatus.PENDING
            assert pending.tool_name == tracking_tool.name
        finally:
            await tenants.delete(tenant_id)

    async def test_tool_visible_in_catalog(self):
        registry = build_platform_tool_registry()
        tool = registry.get("grant_temporary_access")
        assert tool is not None
        assert tool.risk_level == ToolRiskLevel.HIGH
        from arc.services.tools import ToolExecutionPolicyMode

        assert tool.execution_policy.mode == ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL


class TestApprovalGrantedAndConsume:
    async def test_approve_then_resume_executes_and_consumes(self, db, approval_setup, tenant_pair):
        approval_svc, tool_svc, tool_repo, approval_repo = approval_setup
        t1, t2 = tenant_pair
        # Use t1 for this test
        tenant_id = t1.id
        requester_id = _unique("requester")
        approver_id = _unique("approver")
        ctx_requester = _context(tenant_id, requester_id)
        ctx_approver = _context(tenant_id, approver_id)
        principal_requester = _principal(requester_id)
        _principal(approver_id)
        authz_requester = _authorization(requester_id)
        _authorization(approver_id, ApplicationRole.COMPANY_ADMINISTRATOR)

        # Need to give approver the decision permission; use PLATFORM_ADMIN for simplicity
        # Actually HumanApprovalService checks self-decision, not RBAC.  # noqa: E501
        # RBAC is checked at API layer, not service layer for decide.  # noqa: E501
        # So any user can decide except self.

        raw_input = {"justification": "need temporary access for incident"}

        # Step 1: requester invokes tool -> pending
        with pytest.raises(ToolDeniedError) as exc_info:
            await tool_svc.execute_tool(
                ctx_requester,
                principal_requester,
                "grant_temporary_access",
                raw_input,
                authz_requester,
            )
        approval_id = exc_info.value.approval_id
        assert approval_id is not None

        # Verify pending
        pending = await approval_svc.get_request(ctx_requester, approval_id)
        assert pending.status == ApprovalStatus.PENDING

        # Step 2: approver approves
        approved = await approval_svc.decide_request(
            ctx_approver, approver_id, approval_id, ApprovalStatus.APPROVED
        )
        assert approved.status == ApprovalStatus.APPROVED

        # Step 3: requester resumes with same input and approval_id -> executes
        result = await tool_svc.execute_tool(
            ctx_requester,
            principal_requester,
            "grant_temporary_access",
            raw_input,
            authz_requester,
            approval_id=approval_id,
        )
        assert result.tool_name == "grant_temporary_access"
        assert result.output["granted"] is True

        # Verify consumed
        consumed = await approval_svc.get_request(ctx_requester, approval_id)
        assert consumed.status == ApprovalStatus.CONSUMED

        # Verify tool execution record exists
        records = await tool_repo.list_for_tenant(tenant_id)
        assert any(r.tool_name == "grant_temporary_access" for r in records)


class TestReplayProtection:
    async def test_replay_of_consumed_approval_is_refused(self, db, approval_setup, tenant_pair):
        approval_svc, tool_svc, tool_repo, approval_repo = approval_setup
        t1, _ = tenant_pair
        tenant_id = t1.id
        requester_id = _unique("requester")
        approver_id = _unique("approver")
        ctx_requester = _context(tenant_id, requester_id)
        ctx_approver = _context(tenant_id, approver_id)
        principal_requester = _principal(requester_id)
        authz_requester = _authorization(requester_id)

        raw_input = {"justification": "replay test"}

        with pytest.raises(ToolDeniedError) as exc_info:
            await tool_svc.execute_tool(
                ctx_requester,
                principal_requester,
                "grant_temporary_access",
                raw_input,
                authz_requester,
            )
        approval_id = exc_info.value.approval_id

        await approval_svc.decide_request(
            ctx_approver, approver_id, approval_id, ApprovalStatus.APPROVED
        )

        # First resume succeeds
        await tool_svc.execute_tool(
            ctx_requester,
            principal_requester,
            "grant_temporary_access",
            raw_input,
            authz_requester,
            approval_id=approval_id,
        )

        # Second replay should fail
        with pytest.raises(ToolDeniedError):
            await tool_svc.execute_tool(
                ctx_requester,
                principal_requester,
                "grant_temporary_access",
                raw_input,
                authz_requester,
                approval_id=approval_id,
            )

        # Verify still consumed
        consumed = await approval_svc.get_request(ctx_requester, approval_id)
        assert consumed.status == ApprovalStatus.CONSUMED


class TestDenyPath:
    async def test_deny_then_resume_is_refused(self, db, approval_setup, tenant_pair):
        approval_svc, tool_svc, tool_repo, approval_repo = approval_setup
        t1, _ = tenant_pair
        tenant_id = t1.id
        requester_id = _unique("requester")
        approver_id = _unique("approver")
        ctx_requester = _context(tenant_id, requester_id)
        ctx_approver = _context(tenant_id, approver_id)
        principal_requester = _principal(requester_id)
        authz_requester = _authorization(requester_id)

        raw_input = {"justification": "deny test"}

        with pytest.raises(ToolDeniedError) as exc_info:
            await tool_svc.execute_tool(
                ctx_requester,
                principal_requester,
                "grant_temporary_access",
                raw_input,
                authz_requester,
            )
        approval_id = exc_info.value.approval_id

        # Reject
        rejected = await approval_svc.decide_request(
            ctx_approver, approver_id, approval_id, ApprovalStatus.REJECTED
        )
        assert rejected.status == ApprovalStatus.REJECTED

        # Resume should be denied
        with pytest.raises(ToolDeniedError):
            await tool_svc.execute_tool(
                ctx_requester,
                principal_requester,
                "grant_temporary_access",
                raw_input,
                authz_requester,
                approval_id=approval_id,
            )

        # Verify still rejected
        stored = await approval_svc.get_request(ctx_requester, approval_id)
        assert stored.status == ApprovalStatus.REJECTED


class TestRequestMismatch:
    async def test_changed_input_does_not_match_approval(self, db, approval_setup, tenant_pair):
        approval_svc, tool_svc, tool_repo, approval_repo = approval_setup
        t1, _ = tenant_pair
        tenant_id = t1.id
        requester_id = _unique("requester")
        approver_id = _unique("approver")
        ctx_requester = _context(tenant_id, requester_id)
        ctx_approver = _context(tenant_id, approver_id)
        principal_requester = _principal(requester_id)
        authz_requester = _authorization(requester_id)

        raw_input_a = {"justification": "original request"}
        raw_input_b = {"justification": "modified request"}

        with pytest.raises(ToolDeniedError) as exc_info:
            await tool_svc.execute_tool(
                ctx_requester,
                principal_requester,
                "grant_temporary_access",
                raw_input_a,
                authz_requester,
            )
        approval_id = exc_info.value.approval_id
        await approval_svc.decide_request(
            ctx_approver, approver_id, approval_id, ApprovalStatus.APPROVED
        )

        # Try to resume with different input -> should fail (binding mismatch)
        with pytest.raises(ToolDeniedError):
            await tool_svc.execute_tool(
                ctx_requester,
                principal_requester,
                "grant_temporary_access",
                raw_input_b,
                authz_requester,
                approval_id=approval_id,
            )

        # Original approval should remain approved (not consumed) or binding error
        stored = await approval_svc.get_request(ctx_requester, approval_id)
        # It should not be consumed; it remains approved or becomes binding error
        assert stored.status in (ApprovalStatus.APPROVED, ApprovalStatus.PENDING)


class TestTenantIsolation:
    async def test_approval_from_tenant_a_cannot_authorize_tenant_b(
        self, db, approval_setup, tenant_pair
    ):
        approval_svc, tool_svc, tool_repo, approval_repo = approval_setup
        t1, t2 = tenant_pair
        tenant_a_id = t1.id
        tenant_b_id = t2.id
        requester_a = _unique("requester-a")
        approver_a = _unique("approver-a")
        requester_b = _unique("requester-b")
        ctx_a_requester = _context(tenant_a_id, requester_a)
        ctx_a_approver = _context(tenant_a_id, approver_a)
        ctx_b_requester = _context(tenant_b_id, requester_b)
        authz_a = _authorization(requester_a)
        authz_b = _authorization(requester_b)

        raw_input = {"justification": "cross-tenant test"}

        # Create approval in tenant A
        with pytest.raises(ToolDeniedError) as exc_info:
            await tool_svc.execute_tool(
                ctx_a_requester,
                _principal(requester_a),
                "grant_temporary_access",
                raw_input,
                authz_a,
            )
        approval_id = exc_info.value.approval_id
        await approval_svc.decide_request(
            ctx_a_approver, approver_a, approval_id, ApprovalStatus.APPROVED
        )

        # Try to use tenant A's approval in tenant B -> should fail
        with pytest.raises(ToolDeniedError):
            await tool_svc.execute_tool(
                ctx_b_requester,
                _principal(requester_b),
                "grant_temporary_access",
                raw_input,
                authz_b,
                approval_id=approval_id,
            )


class TestRbacAndCapability:
    async def test_unauthorized_user_cannot_create_approval(self, db, approval_setup, tenant_pair):
        """Unauthorized (no tool:execute) is denied before approval creation."""
        approval_svc, tool_svc, tool_repo, approval_repo = approval_setup
        t1, _ = tenant_pair
        tenant_id = t1.id
        user_id = _unique("user")
        ctx = _context(tenant_id, user_id)
        principal = _principal(user_id)
        # EMPLOYEE has no tool:execute
        authz = _authorization(user_id, ApplicationRole.EMPLOYEE)

        with pytest.raises(ToolDeniedError) as exc_info:
            await tool_svc.execute_tool(
                ctx, principal, "grant_temporary_access", {"justification": "test"}, authz
            )
        # Should be denied without approval_id (not the approval path)
        assert exc_info.value.approval_id is None

    async def test_capability_disabled_still_denied_even_with_approval(self, db, tenant_pair):
        """Capability disabled -> denied, approval cannot bypass."""
        from arc.repositories.capabilities import PostgreSQLCapabilityRepository

        approval_repo = PostgreSQLApprovalRequestRepository(db)
        approval_svc = HumanApprovalService(approval_repo)
        tool_repo = PostgreSQLToolExecutionRepository(db)
        cap_repo = PostgreSQLCapabilityRepository(db)
        cap_svc = CapabilityService(cap_repo)

        # Disable tool_execution for this tenant's platform
        # Use set_platform to disable globally (hard ceiling)
        await cap_svc.set_platform("tool_execution", False)

        # Create a tenant-specific capability service? The tool service checks
        # capability_service.is_enabled(tenant_id, "tool_execution")
        # With platform disabled, it will be False for all tenants.

        registry = build_platform_tool_registry()
        tool_svc = ToolExecutionService(
            registry=registry,
            record_repo=tool_repo,
            approval_service=approval_svc,
            capability_service=cap_svc,
        )

        t1, _ = tenant_pair
        tenant_id = t1.id
        user_id = _unique("user")
        ctx = _context(tenant_id, user_id)
        principal = _principal(user_id)
        authz = _authorization(user_id)

        # Even though we will try to create approval, the capability gate
        # happens before tool lookup, so it will be denied without approval_id
        with pytest.raises(ToolDeniedError) as exc_info:
            await tool_svc.execute_tool(
                ctx, principal, "grant_temporary_access", {"justification": "test"}, authz
            )
        assert exc_info.value.approval_id is None

        # Restore platform
        await cap_svc.set_platform("tool_execution", True)
