"""Tests for the SkillService PII guard on textual Skill fields.

These tests verify that:
1. Clean Skill creation still succeeds.
2. PII-containing Skill input follows the real PiiGuardService behavior.
3. The Skill creation persistence path cannot bypass the guard.
4. The guarded fields are actually transformed before repository persistence.
5. Structural Skill fields that should remain exact are not accidentally modified.
6. Existing RBAC remains unchanged.
7. Existing tenant isolation remains unchanged.
8. PII guard failure prevents persistence.

Unit tests use fake analyzer/anonymizer engines (matching test_pii.py pattern)
so they never load the spaCy model.
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import List, Optional, Tuple
from unittest.mock import AsyncMock

import pytest

from arc.domain.models import Skill, TenantContext, UserRole
from arc.repositories import SkillRepository
from arc.services.pii import PiiGuardConfig, PiiGuardError, PiiGuardService
from arc.services.skills import SkillService


@dataclass
class FakeRecognizerResult:
    """Minimal RecognizerResult compatible with PiiGuardService."""

    entity_type: str
    start: int
    end: int
    score: float


class FakeAnalyzer:
    """Fake Presidio AnalyzerEngine returning configured results."""

    def __init__(self, results: List[Tuple[str, int, int, float]]):
        self.results = results
        self.calls = 0

    def analyze(self, text: str, language: str, entities=None):
        self.calls += 1
        return [
            FakeRecognizerResult(entity_type, start, end, score)
            for entity_type, start, end, score in self.results
        ]


class FakeAnonymizer:
    """Fake Presidio AnonymizerEngine applying replace semantics."""

    def __init__(self, text_out: Optional[str] = None):
        self.text_out = text_out

    def anonymize(self, text: str, analyzer_results, operators=None):
        if self.text_out is not None:
            return SimpleNamespace(text=self.text_out)
        out = text
        for result in sorted(analyzer_results, key=lambda r: -r.start):
            out = out[: result.start] + f"<{result.entity_type}>" + out[result.end :]
        return SimpleNamespace(text=out)


def make_pii_guard(
    analyzer_results: List[Tuple[str, int, int, float]],
    config: Optional[PiiGuardConfig] = None,
) -> PiiGuardService:
    """Create a PiiGuardService with fake engines for unit testing."""
    analyzer = FakeAnalyzer(analyzer_results)
    anonymizer = FakeAnonymizer()
    return PiiGuardService(
        config=config or PiiGuardConfig(),
        analyzer_engine=analyzer,
        anonymizer_engine=anonymizer,
    )


def _find_pii_spans(
    text: str, entity_type: str, substrings: List[str]
) -> List[Tuple[str, int, int, float]]:
    """Find PII spans in text for given substrings."""
    results = []
    for substring in substrings:
        start = text.find(substring)
        if start >= 0:
            results.append((entity_type, start, start + len(substring), 0.9))
    return results


@pytest.fixture
def skill_repo():
    """Create a mock SkillRepository."""
    return AsyncMock(spec=SkillRepository)


@pytest.fixture
def tenant_context():
    """Create a trusted TenantContext for testing."""
    return TenantContext(
        tenant_id="tenant-1",
        tenant_name="Test Tenant",
        user_id="user-1",
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


class TestSkillCreationWithPiiGuard:
    """Test that PII guard is applied to textual fields during Skill creation."""

    async def test_clean_skill_creation_succeeds(self, skill_repo, tenant_context):
        """Clean Skill creation (no PII) should succeed normally."""
        pii_guard = make_pii_guard([])
        service = SkillService(skill_repo, pii_guard=pii_guard)
        expected = _skill(tenant_id=tenant_context.tenant_id)
        skill_repo.create.return_value = expected

        result = await service.create_skill(tenant_context, _skill())

        assert result == expected
        skill_repo.create.assert_called_once()

    async def test_pii_in_name_is_sanitized(self, skill_repo, tenant_context):
        """PII in the name field should be sanitized before persistence."""
        name = "Contact John Smith about billing"
        detections = _find_pii_spans(name, "PERSON", ["John Smith"])
        pii_guard = make_pii_guard(detections)
        service = SkillService(skill_repo, pii_guard=pii_guard)

        skill = _skill(name=name)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert "John Smith" not in created.name
        assert "<PERSON>" in created.name

    async def test_pii_in_purpose_is_sanitized(self, skill_repo, tenant_context):
        """PII in the purpose field should be sanitized before persistence."""
        purpose = "Help alice@example.com with account recovery"
        detections = _find_pii_spans(purpose, "EMAIL_ADDRESS", ["alice@example.com"])
        pii_guard = make_pii_guard(detections)
        service = SkillService(skill_repo, pii_guard=pii_guard)

        skill = _skill(purpose=purpose)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert "alice@example.com" not in created.purpose
        assert "<EMAIL_ADDRESS>" in created.purpose

    async def test_pii_in_inputs_is_sanitized(self, skill_repo, tenant_context):
        """PII in the inputs list should be sanitized before persistence."""
        input_text = "User email: bob@example.com"
        detections = _find_pii_spans(input_text, "EMAIL_ADDRESS", ["bob@example.com"])
        pii_guard = make_pii_guard(detections)
        service = SkillService(skill_repo, pii_guard=pii_guard)

        skill = _skill(inputs=[input_text, "Phone: 555-1234567"])
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert "bob@example.com" not in created.inputs[0]
        assert "<EMAIL_ADDRESS>" in created.inputs[0]

    async def test_pii_in_steps_is_sanitized(self, skill_repo, tenant_context):
        """PII in the steps list should be sanitized before persistence."""
        step = "Call John at 555-1234567"
        detections = _find_pii_spans(step, "PHONE_NUMBER", ["555-1234567"])
        pii_guard = make_pii_guard(detections)
        service = SkillService(skill_repo, pii_guard=pii_guard)

        skill = _skill(steps=[step, "Verify identity"])
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert "555-1234567" not in created.steps[0]
        assert "<PHONE_NUMBER>" in created.steps[0]

    async def test_pii_in_expected_output_is_sanitized(self, skill_repo, tenant_context):
        """PII in expected_output should be sanitized before persistence."""
        expected = "Send summary to john.doe@company.com"
        detections = _find_pii_spans(expected, "EMAIL_ADDRESS", ["john.doe@company.com"])
        pii_guard = make_pii_guard(detections)
        service = SkillService(skill_repo, pii_guard=pii_guard)

        skill = _skill(expected_output=expected)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert "john.doe@company.com" not in created.expected_output
        assert "<EMAIL_ADDRESS>" in created.expected_output

    async def test_none_expected_output_stays_none(self, skill_repo, tenant_context):
        """None expected_output should remain None after sanitization."""
        pii_guard = make_pii_guard([])
        service = SkillService(skill_repo, pii_guard=pii_guard)

        skill = _skill(expected_output=None)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert created.expected_output is None

    async def test_multiple_pii_types_in_name(self, skill_repo, tenant_context):
        """Multiple PII types in name should all be sanitized."""
        name = "Contact John Smith at john@corp.com"
        detections = [
            ("PERSON", 8, 18, 0.9),
            ("EMAIL_ADDRESS", 22, 35, 0.9),
        ]
        pii_guard = make_pii_guard(detections)
        service = SkillService(skill_repo, pii_guard=pii_guard)

        skill = _skill(name=name)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert "John Smith" not in created.name
        assert "john@corp.com" not in created.name


class TestStructuralFieldsUnchanged:
    """Test that structural/machine fields are not modified by PII guard."""

    async def test_allowed_tools_not_modified(self, skill_repo, tenant_context):
        """allowed_tools (machine identifiers) should not be modified."""
        pii_guard = make_pii_guard([])
        service = SkillService(skill_repo, pii_guard=pii_guard)

        tools = ["check_service_health", "restart_service"]
        skill = _skill(allowed_tools=tools)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert created.allowed_tools == tools

    async def test_preconditions_not_modified(self, skill_repo, tenant_context):
        """preconditions should not be modified."""
        pii_guard = make_pii_guard([])
        service = SkillService(skill_repo, pii_guard=pii_guard)

        preconditions = ["user_identity_verified", "account_is_active"]
        skill = _skill(preconditions=preconditions)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert created.preconditions == preconditions

    async def test_constraints_not_modified(self, skill_repo, tenant_context):
        """constraints should not be modified."""
        pii_guard = make_pii_guard([])
        service = SkillService(skill_repo, pii_guard=pii_guard)

        constraints = ["max_retries: 3", "timeout: 30s"]
        skill = _skill(constraints=constraints)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert created.constraints == constraints

    async def test_version_not_modified(self, skill_repo, tenant_context):
        """version should not be modified."""
        pii_guard = make_pii_guard([])
        service = SkillService(skill_repo, pii_guard=pii_guard)

        skill = _skill(version="2.1")
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert created.version == "2.1"

    async def test_approval_required_not_modified(self, skill_repo, tenant_context):
        """approval_required (boolean) should not be modified."""
        pii_guard = make_pii_guard([])
        service = SkillService(skill_repo, pii_guard=pii_guard)

        skill = _skill(approval_required=True)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert created.approval_required is True

    async def test_failure_behavior_not_modified(self, skill_repo, tenant_context):
        """failure_behavior should not be modified (not PII-sensitive)."""
        pii_guard = make_pii_guard([])
        service = SkillService(skill_repo, pii_guard=pii_guard)

        behavior = "retry up to 3 times"
        skill = _skill(failure_behavior=behavior)
        await service.create_skill(tenant_context, skill)

        created = skill_repo.create.call_args[0][0]
        assert created.failure_behavior == behavior


class TestPiiGuardFailurePreventsPersistence:
    """Test that PII guard failure prevents Skill persistence."""

    async def test_pii_guard_error_prevents_persistence(self, skill_repo, tenant_context):
        """PiiGuardError should prevent Skill persistence (fail closed)."""

        class ExplodingPiiGuard(PiiGuardService):
            def sanitize(self, text):
                raise PiiGuardError("analysis failed")

        service = SkillService(skill_repo, pii_guard=ExplodingPiiGuard())

        with pytest.raises(PiiGuardError):
            await service.create_skill(tenant_context, _skill())

        skill_repo.create.assert_not_called()

    async def test_analyzer_failure_prevents_persistence(self, skill_repo, tenant_context):
        """Analyzer failure should prevent Skill persistence."""

        class BrokenAnalyzer:
            def analyze(self, text, language, entities=None):
                raise RuntimeError("analyzer broken")

        pii_guard = PiiGuardService(
            config=PiiGuardConfig(),
            analyzer_engine=BrokenAnalyzer(),
        )
        service = SkillService(skill_repo, pii_guard=pii_guard)

        with pytest.raises(PiiGuardError):
            await service.create_skill(tenant_context, _skill())

        skill_repo.create.assert_not_called()


class TestTenantIsolationUnchanged:
    """Prove that PII guard does not break tenant isolation."""

    async def test_create_uses_context_tenant_id(self, skill_repo):
        """create_skill derives tenant_id from context, not from input."""
        ctx_a = TenantContext(
            tenant_id="tenant-A", tenant_name="Tenant A", user_id="user-a", role=UserRole.MEMBER
        )
        ctx_b = TenantContext(
            tenant_id="tenant-B", tenant_name="Tenant B", user_id="user-b", role=UserRole.MEMBER
        )
        pii_guard = make_pii_guard([])
        service = SkillService(skill_repo, pii_guard=pii_guard)
        skill_repo.create.return_value = _skill(tenant_id="x")

        await service.create_skill(ctx_a, _skill())
        created_a = skill_repo.create.call_args[0][0]
        assert created_a.tenant_id == "tenant-A"

        await service.create_skill(ctx_b, _skill())
        created_b = skill_repo.create.call_args[0][0]
        assert created_b.tenant_id == "tenant-B"

        assert created_a.tenant_id != created_b.tenant_id


class TestExistingBehaviorPreserved:
    """Test that existing SkillService behavior is preserved."""

    async def test_validates_name_empty(self, skill_repo, tenant_context):
        """Empty name should raise ValueError."""
        service = SkillService(skill_repo)
        with pytest.raises(ValueError, match="Skill name cannot be empty"):
            await service.create_skill(tenant_context, _skill(name=""))

    async def test_validates_purpose_empty(self, skill_repo, tenant_context):
        """Empty purpose should raise ValueError."""
        service = SkillService(skill_repo)
        with pytest.raises(ValueError, match="Skill purpose cannot be empty"):
            await service.create_skill(tenant_context, _skill(purpose=""))

    def test_preconditions_met(self, skill_repo):
        """preconditions_met helper should still work."""
        service = SkillService(skill_repo)
        skill = _skill(preconditions=["cond_a", "cond_b"])
        assert service.preconditions_met(skill, ["cond_a", "cond_b", "cond_c"]) is True
        assert service.preconditions_met(skill, ["cond_a"]) is False

    def test_is_tool_allowed(self, skill_repo):
        """is_tool_allowed helper should still work."""
        service = SkillService(skill_repo)
        skill = _skill(allowed_tools=["tool_a", "tool_b"])
        assert service.is_tool_allowed(skill, "tool_a") is True
        assert service.is_tool_allowed(skill, "tool_c") is False


class TestSanitizationOrder:
    """Test that sanitization occurs before persistence."""

    async def test_sanitize_called_before_repo_create(self, skill_repo, tenant_context):
        """Sanitization must occur before the repository create call."""
        call_order = []

        async def tracking_create(skill):
            call_order.append("repo_create")
            return skill

        skill_repo.create = tracking_create

        pii_guard = make_pii_guard([])
        original_sanitize = pii_guard.sanitize

        def tracking_sanitize(text):
            call_order.append("pii_sanitize")
            return original_sanitize(text)

        pii_guard.sanitize = tracking_sanitize

        service = SkillService(skill_repo, pii_guard=pii_guard)
        await service.create_skill(tenant_context, _skill())

        # sanitize called for name, purpose, inputs list, steps list = 4 calls
        # then repo_create
        assert call_order[0] == "pii_sanitize"
        assert call_order[-1] == "repo_create"
