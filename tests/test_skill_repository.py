"""Integration tests for the PostgreSQL SkillRepository.

These tests exercise the concrete PostgreSQL skill repository through the
service-facing Protocol method names against a real PostgreSQL database.
They verify the repository contract, the JSONB definition round-trip, and
tenant isolation end-to-end.
"""

import uuid

import pytest

from arc.db.connection import DuplicateKeyError, NotFoundError
from arc.domain.models import Skill, SkillStatus, Tenant
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"sk-{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def skill_repo(db):
    """Create a PostgreSQLSkillRepository."""
    return PostgreSQLSkillRepository(db)


@pytest.fixture
async def seeded_tenant(db):
    """Create a tenant for test data and clean up afterwards."""
    tenant_repo = PostgreSQLTenantRepository(db)
    tenant_id = _unique("tenant")
    tenant = await tenant_repo.create(Tenant(id=tenant_id, name="Skill Test Tenant"))
    yield tenant
    await tenant_repo.delete(tenant.id)


@pytest.fixture
async def seeded_tenants(db):
    """Create two tenants for cross-tenant isolation tests."""
    tenant_repo = PostgreSQLTenantRepository(db)
    tenant_a_id = _unique("tenant-a")
    tenant_b_id = _unique("tenant-b")
    tenant_a = await tenant_repo.create(Tenant(id=tenant_a_id, name="Tenant A"))
    tenant_b = await tenant_repo.create(Tenant(id=tenant_b_id, name="Tenant B"))
    yield tenant_a, tenant_b
    await tenant_repo.delete(tenant_a.id)
    await tenant_repo.delete(tenant_b.id)


def _skill(tenant_id: str, **overrides) -> Skill:
    """Build a valid Skill with overridable fields."""
    values = {
        "id": _unique("skill"),
        "tenant_id": tenant_id,
        "name": "Service Recovery",
        "purpose": "Recover a degraded service",
        "inputs": ["service_name"],
        "preconditions": ["service_health_degraded"],
        "steps": ["check_health", "recover_service", "verify_health"],
        "constraints": ["do_not_restart_production"],
        "allowed_tools": ["check_service_health", "restart_service"],
        "approval_required": True,
        "expected_output": "service_healthy",
        "failure_behavior": "create_incident",
        "provenance": "ops-runbook-v1",
    }
    values.update(overrides)
    return Skill(**values)


class TestSkillRepositoryContract:
    """Verify the SkillRepository Protocol methods against PostgreSQL."""

    async def test_create_and_get(self, skill_repo, seeded_tenant):
        """Test creating a skill and retrieving it."""
        skill = _skill(seeded_tenant.id)
        created = await skill_repo.create(skill)
        assert created.id == skill.id
        assert created.tenant_id == seeded_tenant.id
        assert created.name == "Service Recovery"
        assert created.status == SkillStatus.ACTIVE

        fetched = await skill_repo.get_by_id(skill.id, seeded_tenant.id)
        assert fetched.id == skill.id
        assert fetched.tenant_id == seeded_tenant.id
        assert fetched.name == "Service Recovery"
        assert fetched.status == SkillStatus.ACTIVE

        await skill_repo.delete(skill.id, seeded_tenant.id)

    async def test_definition_round_trip(self, skill_repo, seeded_tenant):
        """Test the JSONB definition body round-trips through PostgreSQL."""
        skill = _skill(seeded_tenant.id)
        await skill_repo.create(skill)

        fetched = await skill_repo.get_by_id(skill.id, seeded_tenant.id)
        assert fetched.inputs == ["service_name"]
        assert fetched.preconditions == ["service_health_degraded"]
        assert fetched.steps == ["check_health", "recover_service", "verify_health"]
        assert fetched.constraints == ["do_not_restart_production"]
        assert fetched.allowed_tools == ["check_service_health", "restart_service"]
        assert fetched.approval_required is True
        assert fetched.expected_output == "service_healthy"
        assert fetched.failure_behavior == "create_incident"
        assert fetched.provenance == "ops-runbook-v1"

        await skill_repo.delete(skill.id, seeded_tenant.id)

    async def test_definition_round_trip_defaults(self, skill_repo, seeded_tenant):
        """Test default body values round-trip."""
        skill = _skill(
            seeded_tenant.id,
            inputs=[],
            preconditions=[],
            steps=[],
            constraints=[],
            allowed_tools=[],
            approval_required=False,
            expected_output=None,
            failure_behavior=None,
            provenance=None,
        )
        await skill_repo.create(skill)

        fetched = await skill_repo.get_by_id(skill.id, seeded_tenant.id)
        assert fetched.inputs == []
        assert fetched.preconditions == []
        assert fetched.steps == []
        assert fetched.constraints == []
        assert fetched.allowed_tools == []
        assert fetched.approval_required is False
        assert fetched.expected_output is None
        assert fetched.failure_behavior is None
        assert fetched.provenance is None

        await skill_repo.delete(skill.id, seeded_tenant.id)

    async def test_list_for_tenant_empty(self, skill_repo, seeded_tenant):
        """Test listing skills for a tenant with none."""
        result = await skill_repo.list_for_tenant(seeded_tenant.id)
        assert result == []

    async def test_list_for_tenant_multiple(self, skill_repo, seeded_tenant):
        """Test listing multiple skills for a tenant."""
        ids = []
        for i in range(3):
            skill = _skill(seeded_tenant.id, name=f"Recovery {i}")
            await skill_repo.create(skill)
            ids.append(skill.id)

        result = await skill_repo.list_for_tenant(seeded_tenant.id)
        assert len(result) == 3
        returned_ids = {s.id for s in result}
        assert returned_ids == set(ids)

        for skill_id in ids:
            await skill_repo.delete(skill_id, seeded_tenant.id)

    async def test_exists_true(self, skill_repo, seeded_tenant):
        """Test exists returns True for existing skill."""
        skill = _skill(seeded_tenant.id)
        await skill_repo.create(skill)
        assert await skill_repo.exists(skill.id, seeded_tenant.id) is True
        await skill_repo.delete(skill.id, seeded_tenant.id)

    async def test_exists_false(self, skill_repo, seeded_tenant):
        """Test exists returns False for missing skill."""
        assert await skill_repo.exists("missing-id", seeded_tenant.id) is False

    async def test_delete(self, skill_repo, seeded_tenant):
        """Test deleting a skill."""
        skill = _skill(seeded_tenant.id)
        await skill_repo.create(skill)
        await skill_repo.delete(skill.id, seeded_tenant.id)
        assert await skill_repo.exists(skill.id, seeded_tenant.id) is False

    async def test_get_by_id_not_found(self, skill_repo, seeded_tenant):
        """Test get_by_id raises NotFoundError for missing skill."""
        with pytest.raises(NotFoundError):
            await skill_repo.get_by_id("missing-id", seeded_tenant.id)

    async def test_duplicate_name_same_version(self, skill_repo, seeded_tenant):
        """Test creating two skills with same tenant/name/version fails."""
        await skill_repo.create(_skill(seeded_tenant.id, name="Duplicate Skill"))
        with pytest.raises(DuplicateKeyError):
            await skill_repo.create(_skill(seeded_tenant.id, name="Duplicate Skill"))
        # Cleanup
        skills = await skill_repo.list_for_tenant(seeded_tenant.id)
        for s in skills:
            if s.name == "Duplicate Skill":
                await skill_repo.delete(s.id, seeded_tenant.id)

    async def test_same_name_different_version_allowed(self, skill_repo, seeded_tenant):
        """Test a new version of the same skill name is allowed."""
        skill_v1 = _skill(seeded_tenant.id, name="Versioned Skill", version="1")
        skill_v2 = _skill(seeded_tenant.id, name="Versioned Skill", version="2")
        await skill_repo.create(skill_v1)
        await skill_repo.create(skill_v2)

        result = await skill_repo.list_for_tenant(seeded_tenant.id)
        versions = {s.version for s in result if s.name == "Versioned Skill"}
        assert versions == {"1", "2"}

        await skill_repo.delete(skill_v1.id, seeded_tenant.id)
        await skill_repo.delete(skill_v2.id, seeded_tenant.id)


class TestSkillTenantIsolation:
    """Prove that the SQL WHERE clause enforces tenant isolation."""

    async def test_get_by_id_isolation(self, skill_repo, seeded_tenants):
        """Tenant A cannot read tenant B's skill by ID."""
        tenant_a, tenant_b = seeded_tenants
        skill = _skill(tenant_a.id, name="Tenant A Recovery")

        await skill_repo.create(skill)

        # Tenant B tries to read tenant A's skill
        with pytest.raises(NotFoundError):
            await skill_repo.get_by_id(skill.id, tenant_b.id)

        await skill_repo.delete(skill.id, tenant_a.id)

    async def test_list_isolation(self, skill_repo, seeded_tenants):
        """Tenant A cannot see tenant B's skills through list."""
        tenant_a, tenant_b = seeded_tenants
        skill_a = _skill(tenant_a.id, name="Tenant A Recovery")
        skill_b = _skill(tenant_b.id, name="Tenant B Recovery")

        await skill_repo.create(skill_a)
        await skill_repo.create(skill_b)

        # Tenant A lists — should only see their own
        list_a = await skill_repo.list_for_tenant(tenant_a.id)
        assert len(list_a) == 1
        assert list_a[0].id == skill_a.id

        # Tenant B lists — should only see their own
        list_b = await skill_repo.list_for_tenant(tenant_b.id)
        assert len(list_b) == 1
        assert list_b[0].id == skill_b.id

        await skill_repo.delete(skill_a.id, tenant_a.id)
        await skill_repo.delete(skill_b.id, tenant_b.id)

    async def test_delete_isolation(self, skill_repo, seeded_tenants):
        """Tenant A cannot delete tenant B's skill."""
        tenant_a, tenant_b = seeded_tenants
        skill_b = _skill(tenant_b.id, name="Tenant B Recovery")
        await skill_repo.create(skill_b)

        # Tenant A tries to delete tenant B's skill — no error raised
        # because DELETE WHERE id=$1 AND tenant_id=$2 affects 0 rows
        await skill_repo.delete(skill_b.id, tenant_a.id)

        # Tenant B's skill still exists
        assert await skill_repo.exists(skill_b.id, tenant_b.id) is True

        await skill_repo.delete(skill_b.id, tenant_b.id)

    async def test_exists_isolation(self, skill_repo, seeded_tenants):
        """Tenant A cannot confirm existence of tenant B's skill."""
        tenant_a, tenant_b = seeded_tenants
        skill_b = _skill(tenant_b.id, name="Tenant B Recovery")
        await skill_repo.create(skill_b)

        # Tenant A checks existence — should return False
        assert await skill_repo.exists(skill_b.id, tenant_a.id) is False

        await skill_repo.delete(skill_b.id, tenant_b.id)
