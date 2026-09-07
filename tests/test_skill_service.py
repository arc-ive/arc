"""Tests for the SkillService with mocked repository."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from arc.db.connection import DuplicateKeyError, NotFoundError
from arc.domain.models import Skill, SkillStatus, TenantContext, UserRole
from arc.repositories import SkillRepository
from arc.services.pii import PiiGuardConfig, PiiGuardService
from arc.services.skills import SkillService


class _FakeRecognizerResult:
    """Minimal RecognizerResult compatible with PiiGuardService."""

    def __init__(self, entity_type: str, start: int, end: int, score: float):
        self.entity_type = entity_type
        self.start = start
        self.end = end
        self.score = score


class _FakeAnalyzer:
    """Fake Presidio AnalyzerEngine returning no results."""

    def analyze(self, text: str, language: str, entities=None):
        return []


class _FakeAnonymizer:
    """Fake Presidio AnonymizerEngine applying replace semantics."""

    def anonymize(self, text: str, analyzer_results, operators=None):
        out = text
        for result in sorted(analyzer_results, key=lambda r: -r.start):
            out = out[: result.start] + f"<{result.entity_type}>" + out[result.end :]
        return SimpleNamespace(text=out)


def _make_noop_pii_guard() -> PiiGuardService:
    """Create a PiiGuardService that never detects PII (for legacy tests)."""
    return PiiGuardService(
        config=PiiGuardConfig(enabled_categories=set()),
        analyzer_engine=_FakeAnalyzer(),
        anonymizer_engine=_FakeAnonymizer(),
    )


@pytest.fixture
def skill_repo():
    """Create a mock SkillRepository."""
    return AsyncMock(spec=SkillRepository)


@pytest.fixture
def service(skill_repo):
    """Create a SkillService with the mock repository."""
    return SkillService(skill_repo, pii_guard=_make_noop_pii_guard())


@pytest.fixture
def tenant_context():
    """Create a trusted TenantContext for testing."""
    return TenantContext(
        tenant_id="tenant-1",
        tenant_name="Test Tenant",
        user_id="user-1",
        role=UserRole.MEMBER,
    )


@pytest.fixture
def other_tenant_context():
    """Create a second trusted TenantContext for a different tenant."""
    return TenantContext(
        tenant_id="tenant-2",
        tenant_name="Other Tenant",
        user_id="user-2",
        role=UserRole.MEMBER,
    )


def _skill(**overrides) -> Skill:
    """Build a valid Skill with overridable fields."""
    values = {
        "id": "skill-1",
        "tenant_id": "placeholder",
        "name": "Service Recovery",
        "purpose": "Recover a degraded service",
    }
    values.update(overrides)
    return Skill(**values)


class TestSkillServiceCreate:
    """Test create_skill delegation and validation."""

    async def test_create_skill_delegates_to_repo(self, service, skill_repo, tenant_context):
        """Test that create_skill calls repository create with trusted tenant_id."""
        expected = _skill(tenant_id=tenant_context.tenant_id)
        skill_repo.create.return_value = expected

        result = await service.create_skill(tenant_context, _skill())

        assert result == expected
        skill_repo.create.assert_called_once()
        call_args = skill_repo.create.call_args
        created = call_args[0][0]
        assert created.tenant_id == tenant_context.tenant_id
        assert created.name == "Service Recovery"
        assert created.purpose == "Recover a degraded service"
        assert created.status == SkillStatus.ACTIVE

    async def test_create_skill_overrides_caller_tenant_id(
        self, service, skill_repo, tenant_context
    ):
        """Test that a caller-supplied tenant_id is never trusted."""
        skill = _skill(tenant_id="malicious-tenant")
        await service.create_skill(tenant_context, skill)
        created = skill_repo.create.call_args[0][0]
        assert created.tenant_id == tenant_context.tenant_id

    async def test_create_skill_validates_name(self, service, tenant_context):
        """Test empty name raises ValueError."""
        with pytest.raises(ValueError, match="Skill name cannot be empty"):
            await service.create_skill(tenant_context, _skill(name=""))

    async def test_create_skill_validates_purpose(self, service, tenant_context):
        """Test empty purpose raises ValueError."""
        with pytest.raises(ValueError, match="Skill purpose cannot be empty"):
            await service.create_skill(tenant_context, _skill(purpose=""))

    async def test_create_skill_propagates_duplicate_error(
        self, service, skill_repo, tenant_context
    ):
        """Test that DuplicateKeyError from repo propagates."""
        skill_repo.create.side_effect = DuplicateKeyError("duplicate")

        with pytest.raises(DuplicateKeyError):
            await service.create_skill(tenant_context, _skill())


class TestSkillServiceGet:
    """Test get_skill delegation."""

    async def test_get_skill_delegates_to_repo(self, service, skill_repo, tenant_context):
        """Test that get_skill calls repository get_by_id with tenant_id from context."""
        expected = _skill(tenant_id=tenant_context.tenant_id)
        skill_repo.get_by_id.return_value = expected

        result = await service.get_skill(tenant_context, "skill-1")

        assert result == expected
        skill_repo.get_by_id.assert_called_once_with("skill-1", tenant_context.tenant_id)

    async def test_get_skill_propagates_not_found(self, service, skill_repo, tenant_context):
        """Test that NotFoundError from repo propagates."""
        skill_repo.get_by_id.side_effect = NotFoundError("not found")

        with pytest.raises(NotFoundError):
            await service.get_skill(tenant_context, "missing-id")


class TestSkillServiceList:
    """Test list_skills delegation."""

    async def test_list_skills_delegates_to_repo(self, service, skill_repo, tenant_context):
        """Test list_skills calls repository with tenant_id from context."""
        expected = [_skill(tenant_id=tenant_context.tenant_id)]
        skill_repo.list_for_tenant.return_value = expected

        result = await service.list_skills(tenant_context)

        assert result == expected
        skill_repo.list_for_tenant.assert_called_once_with(tenant_context.tenant_id)


class TestSkillServiceDelete:
    """Test delete_skill delegation."""

    async def test_delete_skill_delegates_to_repo(self, service, skill_repo, tenant_context):
        """Test that delete_skill calls repository delete with tenant_id from context."""
        await service.delete_skill(tenant_context, "skill-1")

        skill_repo.delete.assert_called_once_with("skill-1", tenant_context.tenant_id)


class TestSkillServiceTenantIsolation:
    """Prove that different TenantContext instances produce different
    tenant_id values in repository calls."""

    async def test_create_uses_context_tenant_id(self, service, skill_repo):
        """Test create_skill derives tenant_id from context."""
        ctx_a = TenantContext(
            tenant_id="tenant-A", tenant_name="Tenant A", user_id="user-a", role=UserRole.MEMBER
        )
        ctx_b = TenantContext(
            tenant_id="tenant-B", tenant_name="Tenant B", user_id="user-b", role=UserRole.MEMBER
        )
        skill_repo.create.return_value = _skill(tenant_id="x")

        await service.create_skill(ctx_a, _skill())
        created_a = skill_repo.create.call_args[0][0]
        assert created_a.tenant_id == "tenant-A"

        await service.create_skill(ctx_b, _skill())
        created_b = skill_repo.create.call_args[0][0]
        assert created_b.tenant_id == "tenant-B"

        assert created_a.tenant_id != created_b.tenant_id

    async def test_get_uses_context_tenant_id(self, service, skill_repo):
        """Test get_skill passes context.tenant_id to repository."""
        ctx_a = TenantContext(
            tenant_id="tenant-A", tenant_name="Tenant A", user_id="user-a", role=UserRole.MEMBER
        )
        ctx_b = TenantContext(
            tenant_id="tenant-B", tenant_name="Tenant B", user_id="user-b", role=UserRole.MEMBER
        )
        skill_repo.get_by_id.return_value = _skill(tenant_id="x")

        await service.get_skill(ctx_a, "s1")
        assert skill_repo.get_by_id.call_args[0] == ("s1", "tenant-A")

        await service.get_skill(ctx_b, "s1")
        assert skill_repo.get_by_id.call_args[0] == ("s1", "tenant-B")

    async def test_list_uses_context_tenant_id(self, service, skill_repo):
        """Test list_skills passes context.tenant_id to repository."""
        ctx_a = TenantContext(
            tenant_id="tenant-A", tenant_name="Tenant A", user_id="user-a", role=UserRole.MEMBER
        )
        ctx_b = TenantContext(
            tenant_id="tenant-B", tenant_name="Tenant B", user_id="user-b", role=UserRole.MEMBER
        )
        skill_repo.list_for_tenant.return_value = []

        await service.list_skills(ctx_a)
        assert skill_repo.list_for_tenant.call_args[0] == ("tenant-A",)

        await service.list_skills(ctx_b)
        assert skill_repo.list_for_tenant.call_args[0] == ("tenant-B",)

    async def test_delete_uses_context_tenant_id(self, service, skill_repo):
        """Test delete_skill passes context.tenant_id to repository."""
        ctx_a = TenantContext(
            tenant_id="tenant-A", tenant_name="Tenant A", user_id="user-a", role=UserRole.MEMBER
        )
        ctx_b = TenantContext(
            tenant_id="tenant-B", tenant_name="Tenant B", user_id="user-b", role=UserRole.MEMBER
        )

        await service.delete_skill(ctx_a, "s1")
        assert skill_repo.delete.call_args[0] == ("s1", "tenant-A")

        await service.delete_skill(ctx_b, "s1")
        assert skill_repo.delete.call_args[0] == ("s1", "tenant-B")


class TestSkillServiceUpdate:
    """Test update_skill delegation and validation."""

    async def test_update_skill_delegates_to_repo(self, service, skill_repo, tenant_context):
        """Test that update_skill calls repository update with trusted tenant_id."""
        original = _skill(tenant_id=tenant_context.tenant_id)
        skill_repo.get_by_id.return_value = original

        updated = _skill(
            id="skill-1",
            tenant_id=tenant_context.tenant_id,
            name="Updated Name",
            purpose="Updated purpose",
        )
        skill_repo.update.return_value = updated

        result = await service.update_skill(tenant_context, updated)

        assert result == updated
        skill_repo.update.assert_called_once()
        call_args = skill_repo.update.call_args
        persisted = call_args[0][0]
        assert persisted.tenant_id == tenant_context.tenant_id

    async def test_update_skill_overrides_caller_tenant_id(
        self, service, skill_repo, tenant_context
    ):
        """Test that a caller-supplied tenant_id is never trusted."""
        skill = _skill(tenant_id="malicious-tenant", name="S", purpose="P")
        skill_repo.update.return_value = skill

        await service.update_skill(tenant_context, skill)
        persisted = skill_repo.update.call_args[0][0]
        assert persisted.tenant_id == tenant_context.tenant_id

    async def test_update_skill_validates_name(self, service, tenant_context):
        """Test empty name raises ValueError (defense-in-depth)."""
        skill = _skill(name="x", purpose="p")
        # Bypass frozen dataclass to test service-level validation guard
        object.__setattr__(skill, "name", "")
        with pytest.raises(ValueError, match="Skill name cannot be empty"):
            await service.update_skill(tenant_context, skill)

    async def test_update_skill_validates_purpose(self, service, tenant_context):
        """Test empty purpose raises ValueError (defense-in-depth)."""
        skill = _skill(name="n", purpose="x")
        object.__setattr__(skill, "purpose", "")
        with pytest.raises(ValueError, match="Skill purpose cannot be empty"):
            await service.update_skill(tenant_context, skill)

    async def test_update_skill_propagates_not_found(self, service, skill_repo, tenant_context):
        """Test that NotFoundError from repo propagates."""
        skill = _skill(tenant_id=tenant_context.tenant_id, name="N", purpose="P")
        skill_repo.update.side_effect = NotFoundError("not found")

        with pytest.raises(NotFoundError):
            await service.update_skill(tenant_context, skill)

    async def test_update_skill_propagates_duplicate_error(
        self, service, skill_repo, tenant_context
    ):
        """Test that DuplicateKeyError from repo propagates."""
        skill = _skill(tenant_id=tenant_context.tenant_id, name="N", purpose="P")
        skill_repo.update.side_effect = DuplicateKeyError("duplicate")

        with pytest.raises(DuplicateKeyError):
            await service.update_skill(tenant_context, skill)

    async def test_update_skill_overrides_malicious_tenant_id(
        self, service, skill_repo, tenant_context
    ):
        """Test that the repo receives the context tenant_id, not any malicious value."""
        skill = _skill(tenant_id="malicious-tenant", name="N", purpose="P")
        skill_repo.update.return_value = _skill(
            tenant_id="malicious-tenant", name="N", purpose="P"
        )

        await service.update_skill(tenant_context, skill)
        persisted = skill_repo.update.call_args[0][0]
        assert persisted.tenant_id == tenant_context.tenant_id


class TestSkillPreconditionValidation:
    """Skill-level precondition validation (TRD 25)."""

    def test_no_preconditions_are_satisfied(self, service):
        """A Skill with no preconditions is satisfied."""
        skill = _skill(preconditions=[])
        assert service.preconditions_met(skill, []) is True

    def test_all_preconditions_satisfied(self, service):
        """All preconditions present in the satisfied set."""
        skill = _skill(preconditions=["user_identity_verified", "account_is_active"])
        assert (
            service.preconditions_met(
                skill, ["user_identity_verified", "account_is_active", "unrelated"]
            )
            is True
        )

    def test_missing_precondition_is_not_met(self, service):
        """A missing precondition means preconditions are not met."""
        skill = _skill(preconditions=["user_identity_verified", "account_is_active"])
        assert service.preconditions_met(skill, ["user_identity_verified"]) is False

    def test_empty_satisfied_set_blocks_conditional_skill(self, service):
        """An empty satisfied set blocks a Skill that has preconditions."""
        skill = _skill(preconditions=["service_health_degraded"])
        assert service.preconditions_met(skill, []) is False


class TestSkillToolValidation:
    """Skill-level tool authorization (TRD 25)."""

    def test_tool_within_allowed_tools(self, service):
        """A tool listed in allowed_tools is allowed."""
        skill = _skill(allowed_tools=["check_service_health", "restart_service"])
        assert service.is_tool_allowed(skill, "check_service_health") is True

    def test_tool_outside_allowed_tools(self, service):
        """A tool not listed in allowed_tools is not allowed."""
        skill = _skill(allowed_tools=["check_service_health"])
        assert service.is_tool_allowed(skill, "restart_service") is False

    def test_empty_allowed_tools_allows_nothing(self, service):
        """A Skill with no allowed_tools allows nothing."""
        skill = _skill(allowed_tools=[])
        assert service.is_tool_allowed(skill, "check_service_health") is False
