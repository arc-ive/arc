"""Unit tests for platform capability domain model and service logic.

Tests the domain model (KNOWN_CAPABILITIES, dataclasses), the
``CapabilityService.is_effective`` static method, and the service
resolution logic using a fake in-memory repository.
"""

import pytest

from arc.domain.models import (
    KNOWN_CAPABILITIES,
    PlatformCapability,
    TenantCapability,
)

# ---------------------------------------------------------------------------
# Domain model tests
# ---------------------------------------------------------------------------


class TestKnownCapabilities:
    def test_exactly_four_capabilities(self):
        assert len(KNOWN_CAPABILITIES) == 4

    def test_expected_capability_ids(self):
        expected = {"skill_execution", "tool_execution", "agent_execution", "connector_sync"}
        assert KNOWN_CAPABILITIES == expected

    def test_frozen(self):
        with pytest.raises(AttributeError):
            KNOWN_CAPABILITIES.add("fake")  # type: ignore[union-attr]


class TestPlatformCapability:
    def test_fields(self):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        pc = PlatformCapability(capability_id="skill_execution", enabled=True, updated_at=now)
        assert pc.capability_id == "skill_execution"
        assert pc.enabled is True
        assert pc.updated_at == now

    def test_immutability(self):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        pc = PlatformCapability(capability_id="skill_execution", enabled=True, updated_at=now)
        with pytest.raises(AttributeError):
            pc.enabled = False  # type: ignore[misc]


class TestTenantCapability:
    def test_fields(self):
        tc = TenantCapability(
            tenant_id="tenant-1",
            capability_id="tool_execution",
            enabled=False,
        )
        assert tc.tenant_id == "tenant-1"
        assert tc.capability_id == "tool_execution"
        assert tc.enabled is False


# ---------------------------------------------------------------------------
# CapabilityService.is_effective — static resolution logic
# ---------------------------------------------------------------------------


class TestIsEffective:
    """The heart of V2-ADR-004: the four-way resolution matrix."""

    def test_no_platform_row_passes_through(self):
        """No platform row = no ceiling, capability passes through."""
        assert CapabilityService.is_effective(None, None) is True
        assert CapabilityService.is_effective(None, True) is True
        assert CapabilityService.is_effective(None, False) is True

    def test_platform_disabled_always_false(self):
        assert CapabilityService.is_effective(False, None) is False
        assert CapabilityService.is_effective(False, True) is False
        assert CapabilityService.is_effective(False, False) is False

    def test_platform_enabled_no_tenant_config_defaults_disabled(self):
        """Global enabled does NOT auto-enable for every tenant (ADR-004)."""
        assert CapabilityService.is_effective(True, None) is False

    def test_platform_enabled_tenant_enabled(self):
        assert CapabilityService.is_effective(True, True) is True

    def test_platform_enabled_tenant_disabled(self):
        assert CapabilityService.is_effective(True, False) is False


# ---------------------------------------------------------------------------
# CapabilityService with fake repository — integration of service logic
# ---------------------------------------------------------------------------


class FakeCapabilityRepository:
    """In-memory fake for unit-testing CapabilityService without PostgreSQL."""

    def __init__(self):
        self._platform: dict[str, PlatformCapability] = {}
        self._tenant: dict[tuple[str, str], TenantCapability] = {}

    async def get_platform_capability(self, capability_id: str):
        return self._platform.get(capability_id)

    async def set_platform_capability(
        self, capability_id: str, enabled: bool
    ) -> PlatformCapability:
        from datetime import datetime, timezone

        pc = PlatformCapability(
            capability_id=capability_id,
            enabled=enabled,
            updated_at=datetime.now(timezone.utc),
        )
        self._platform[capability_id] = pc
        return pc

    async def list_platform_capabilities(self):
        return list(self._platform.values())

    async def get_tenant_capability(self, tenant_id: str, capability_id: str):
        return self._tenant.get((tenant_id, capability_id))

    async def set_tenant_capability(
        self, tenant_id: str, capability_id: str, enabled: bool
    ) -> TenantCapability:
        tc = TenantCapability(
            tenant_id=tenant_id,
            capability_id=capability_id,
            enabled=enabled,
        )
        self._tenant[(tenant_id, capability_id)] = tc
        return tc

    async def list_tenant_capabilities(self, tenant_id: str):
        return [tc for (tid, _), tc in self._tenant.items() if tid == tenant_id]


# Import here so the fake can reference the real class
from arc.services.capabilities import CapabilityService  # noqa: E402


class TestCapabilityService:
    @pytest.fixture
    def repo(self):
        return FakeCapabilityRepository()

    @pytest.fixture
    def svc(self, repo):
        return CapabilityService(repo)

    async def test_is_enabled_unknown_capability_returns_false(self, svc):
        assert await svc.is_enabled("tenant-1", "nonexistent") is False

    async def test_is_enabled_no_platform_row_passes_through(self, svc):
        """No platform row = no ceiling, execution proceeds."""
        assert await svc.is_enabled("tenant-1", "skill_execution") is True

    async def test_is_enabled_platform_disabled_returns_false(self, svc):
        await svc.set_platform("skill_execution", False)
        assert await svc.is_enabled("tenant-1", "skill_execution") is False

    async def test_is_enabled_no_tenant_config_returns_false(self, svc):
        await svc.set_platform("skill_execution", True)
        assert await svc.is_enabled("tenant-1", "skill_execution") is False

    async def test_is_enabled_platform_and_tenant_enabled(self, svc):
        await svc.set_platform("tool_execution", True)
        await svc.set_tenant("tenant-1", "tool_execution", True)
        assert await svc.is_enabled("tenant-1", "tool_execution") is True

    async def test_is_enabled_tenant_disabled_overrides(self, svc):
        await svc.set_platform("tool_execution", True)
        await svc.set_tenant("tenant-1", "tool_execution", False)
        assert await svc.is_enabled("tenant-1", "tool_execution") is False

    async def test_set_platform_unknown_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="Unknown capability"):
            await svc.set_platform("fake_cap", True)

    async def test_set_tenant_unknown_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="Unknown capability"):
            await svc.set_tenant("tenant-1", "fake_cap", True)

    async def test_list_platform(self, svc):
        await svc.set_platform("skill_execution", True)
        await svc.set_platform("tool_execution", False)
        states = await svc.list_platform()
        assert len(states) == 2
        by_id = {s.capability_id: s.enabled for s in states}
        assert by_id == {"skill_execution": True, "tool_execution": False}

    async def test_list_tenant_effective(self, svc):
        await svc.set_platform("skill_execution", True)
        await svc.set_platform("tool_execution", False)
        await svc.set_tenant("t1", "skill_execution", True)
        results = await svc.list_tenant("t1")
        assert len(results) == 2
        r1 = next(r for r in results if r["capability_id"] == "skill_execution")
        assert r1["platform_enabled"] is True
        assert r1["tenant_enabled"] is True
        assert r1["effective_enabled"] is True
        r2 = next(r for r in results if r["capability_id"] == "tool_execution")
        assert r2["platform_enabled"] is False
        assert r2["effective_enabled"] is False

    async def test_get_tenant_one_capability(self, svc):
        await svc.set_platform("agent_execution", True)
        await svc.set_tenant("t1", "agent_execution", True)
        result = await svc.get_tenant("t1", "agent_execution")
        assert result["effective_enabled"] is True

    async def test_get_tenant_unknown_capability_returns_none(self, svc):
        result = await svc.get_tenant("t1", "nonexistent")
        assert result is None
