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
    def test_exactly_five_capabilities(self):
        assert len(KNOWN_CAPABILITIES) == 5

    def test_expected_capability_ids(self):
        expected = {
            "skill_execution",
            "tool_execution",
            "agent_execution",
            "connector_sync",
            # ADR-013: the platform kill switch for anything that leaves
            # the tenant boundary.
            "external_action",
        }
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
    """The heart of V2-ADR-004: the nine-state resolution matrix (Issue #212)."""

    def test_no_platform_row(self):
        assert CapabilityService.is_effective(None, None) is True
        assert CapabilityService.is_effective(None, True) is True
        assert CapabilityService.is_effective(None, False) is False

    def test_platform_disabled_hard_ceiling(self):
        assert CapabilityService.is_effective(False, None) is False
        assert CapabilityService.is_effective(False, True) is False
        assert CapabilityService.is_effective(False, False) is False

    def test_platform_enabled(self):
        assert CapabilityService.is_effective(True, None) is True
        assert CapabilityService.is_effective(True, True) is True
        assert CapabilityService.is_effective(True, False) is False

    def test_nine_state_matrix_comprehensive(self):
        """Explicitly assert all nine combinations."""
        matrix = [
            (None, None, True),
            (None, True, True),
            (None, False, False),
            (True, None, True),
            (True, True, True),
            (True, False, False),
            (False, None, False),
            (False, True, False),
            (False, False, False),
        ]
        for platform, tenant, expected in matrix:
            assert CapabilityService.is_effective(platform, tenant) is expected, (
                f"platform={platform!r} tenant={tenant!r} expected {expected!r}"
            )

    def test_enabling_platform_never_reduces_availability(self):
        """Enabling the platform must not make a tenant unavailable (Issue #212)."""
        for tenant in (None, True, False):
            before = CapabilityService.is_effective(None, tenant)
            after = CapabilityService.is_effective(True, tenant)
            # Enabling platform cannot turn True -> False
            assert not (before is True and after is False), f"tenant={tenant!r}"

    def test_platform_disable_is_hard_ceiling(self):
        """Platform False disables for every tenant state."""
        for tenant in (None, True, False):
            assert CapabilityService.is_effective(False, tenant) is False


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

    async def test_is_enabled_platform_enabled_no_tenant_override_is_enabled(self, svc):
        """Platform true + tenant absent -> ENABLED (Issue #212)."""
        await svc.set_platform("skill_execution", True)
        assert await svc.is_enabled("tenant-1", "skill_execution") is True

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

    # ------------------------------------------------------------------
    # Issue #212: platform enable must not disable tenants without override
    # ------------------------------------------------------------------

    async def test_platform_enable_preserves_tenant_with_no_override(self, svc):
        """Regression: tenant with no row is enabled before and after platform enable."""
        cap = "skill_execution"
        # No platform row -> enabled (no ceiling)
        assert await svc.is_enabled("tenant-1", cap) is True
        # Enable platform, leave tenant absent -> still enabled
        await svc.set_platform(cap, True)
        assert await svc.is_enabled("tenant-1", cap) is True
        # Disable platform -> hard ceiling, now disabled
        await svc.set_platform(cap, False)
        assert await svc.is_enabled("tenant-1", cap) is False

    async def test_all_four_capabilities_share_semantics(self, svc):
        """The same resolution applies to all four capability types."""
        for cap in (
            "skill_execution",
            "tool_execution",
            "agent_execution",
            "connector_sync",
        ):
            # Absent/absent -> enabled, then platform true/absent -> enabled,
            # then platform false -> disabled
            fresh_repo = FakeCapabilityRepository()
            fresh_svc = CapabilityService(fresh_repo)
            assert await fresh_svc.is_enabled("t1", cap) is True
            await fresh_svc.set_platform(cap, True)
            assert await fresh_svc.is_enabled("t1", cap) is True
            await fresh_svc.set_platform(cap, False)
            assert await fresh_svc.is_enabled("t1", cap) is False

    async def test_tenant_isolation_platform_enable(self, svc):
        """Tenant A absent, tenant B explicitly disabled — platform enable respects both."""
        cap = "tool_execution"
        await svc.set_platform(cap, True)
        # Tenant A has no override -> enabled
        assert await svc.is_enabled("tenant-a", cap) is True
        # Tenant B explicitly disabled -> disabled
        await svc.set_tenant("tenant-b", cap, False)
        assert await svc.is_enabled("tenant-b", cap) is False
        # Tenant A still enabled after B's override
        assert await svc.is_enabled("tenant-a", cap) is True
        # Platform hard ceiling disables both
        await svc.set_platform(cap, False)
        assert await svc.is_enabled("tenant-a", cap) is False
        assert await svc.is_enabled("tenant-b", cap) is False
        # Tenant B true cannot override hard ceiling
        await svc.set_tenant("tenant-b", cap, True)
        assert await svc.is_enabled("tenant-b", cap) is False
