"""Tests for Arc Skill domain models."""

import pytest

from arc.domain.models import Skill, SkillStatus


class TestSkillStatus:
    """Test SkillStatus enum."""

    def test_status_values(self):
        """Test status enum values."""
        assert SkillStatus.ACTIVE == "active"
        assert SkillStatus.INACTIVE == "inactive"
        assert SkillStatus.ARCHIVED == "archived"

    def test_status_member_check(self):
        """Test that all expected statuses are valid."""
        expected = {"active", "inactive", "archived"}
        for status in SkillStatus:
            assert status.value in expected


class TestSkillModel:
    """Test Skill domain model."""

    def test_skill_creation(self):
        """Test creating a skill with all fields."""
        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            name="Service Recovery",
            purpose="Recover a degraded service",
            version="2",
            inputs=["service_name"],
            preconditions=["service_health_degraded"],
            steps=["check_health", "recover_service", "verify_health"],
            constraints=["do_not_restart_production"],
            allowed_tools=["check_service_health", "restart_service"],
            approval_required=True,
            expected_output="service_healthy",
            failure_behavior="create_incident",
            provenance="ops-runbook-v1",
            risk="low",
        )
        assert skill.id == "skill-1"
        assert skill.tenant_id == "tenant-1"
        assert skill.name == "Service Recovery"
        assert skill.purpose == "Recover a degraded service"
        assert skill.version == "2"
        assert skill.inputs == ["service_name"]
        assert skill.preconditions == ["service_health_degraded"]
        assert skill.steps == ["check_health", "recover_service", "verify_health"]
        assert skill.constraints == ["do_not_restart_production"]
        assert skill.allowed_tools == ["check_service_health", "restart_service"]
        assert skill.approval_required is True
        assert skill.expected_output == "service_healthy"
        assert skill.failure_behavior == "create_incident"
        assert skill.provenance == "ops-runbook-v1"
        assert skill.risk == "low"
        assert skill.status == SkillStatus.ACTIVE

    def test_skill_defaults(self):
        """Test default values."""
        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            name="Recovery",
            purpose="Recover a service",
        )
        assert skill.version == "1"
        assert skill.inputs == []
        assert skill.preconditions == []
        assert skill.steps == []
        assert skill.constraints == []
        assert skill.allowed_tools == []
        assert skill.approval_required is False
        assert skill.expected_output is None
        assert skill.failure_behavior is None
        assert skill.provenance is None
        assert skill.risk is None
        assert skill.status == SkillStatus.ACTIVE

    def test_skill_default_timestamps(self):
        """Test that default timestamps are datetime instances."""
        from datetime import datetime

        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            name="Recovery",
            purpose="Recover a service",
        )
        assert isinstance(skill.created_at, datetime)
        assert isinstance(skill.updated_at, datetime)

    def test_skill_validation_empty_id(self):
        """Test empty ID raises ValueError."""
        with pytest.raises(ValueError, match="Skill ID cannot be empty"):
            Skill(id="", tenant_id="t1", name="Recovery", purpose="Recover a service")

    def test_skill_validation_empty_tenant_id(self):
        """Test empty tenant ID raises ValueError."""
        with pytest.raises(ValueError, match="Tenant ID cannot be empty"):
            Skill(id="s1", tenant_id="", name="Recovery", purpose="Recover a service")

    def test_skill_validation_empty_name(self):
        """Test empty name raises ValueError."""
        with pytest.raises(ValueError, match="Skill name cannot be empty"):
            Skill(id="s1", tenant_id="t1", name="", purpose="Recover a service")

    def test_skill_validation_empty_purpose(self):
        """Test empty purpose raises ValueError."""
        with pytest.raises(ValueError, match="Skill purpose cannot be empty"):
            Skill(id="s1", tenant_id="t1", name="Recovery", purpose="")

    def test_skill_validation_empty_version(self):
        """Test empty version raises ValueError."""
        with pytest.raises(ValueError, match="Skill version must be a non-empty string"):
            Skill(id="s1", tenant_id="t1", name="Recovery", purpose="Recover", version="")

    def test_skill_validation_invalid_status(self):
        """Test invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid skill status"):
            Skill(id="s1", tenant_id="t1", name="Recovery", purpose="Recover", status="invalid")

    def test_skill_validation_non_bool_approval_required(self):
        """Test non-boolean approval_required raises ValueError."""
        with pytest.raises(ValueError, match="approval_required must be a boolean"):
            Skill(
                id="s1",
                tenant_id="t1",
                name="Recovery",
                purpose="Recover",
                approval_required="yes",
            )

    def test_skill_validation_non_list_steps(self):
        """Test steps that are not a list of strings raise ValueError."""
        with pytest.raises(ValueError, match="steps must be a list of strings"):
            Skill(id="s1", tenant_id="t1", name="Recovery", purpose="Recover", steps="recover")

    def test_skill_validation_non_string_step(self):
        """Test steps containing a non-string raise ValueError."""
        with pytest.raises(ValueError, match="steps must be a list of strings"):
            Skill(id="s1", tenant_id="t1", name="Recovery", purpose="Recover", steps=[1, 2])

    def test_skill_validation_non_list_allowed_tools(self):
        """Test allowed_tools that are not a list of strings raise ValueError."""
        with pytest.raises(ValueError, match="allowed_tools must be a list of strings"):
            Skill(
                id="s1",
                tenant_id="t1",
                name="Recovery",
                purpose="Recover",
                allowed_tools="check_service_health",
            )

    def test_skill_risk_field_optional(self):
        """Test that risk field defaults to None and accepts string values."""
        skill_no_risk = Skill(id="s1", tenant_id="t1", name="Recovery", purpose="Recover")
        assert skill_no_risk.risk is None

        skill_with_risk = Skill(
            id="s2", tenant_id="t1", name="Deploy", purpose="Deploy code", risk="high"
        )
        assert skill_with_risk.risk == "high"

        skill_low_risk = Skill(
            id="s3", tenant_id="t1", name="Health Check", purpose="Check health", risk="low"
        )
        assert skill_low_risk.risk == "low"
