"""Platform capability service (V2-ADR-004 hierarchy, Issue #144).

Central capability resolution: owns the effective-state logic that
combines platform and tenant configuration. Each execution path calls
``is_enabled`` as a pre-check before proceeding.

Effective-state semantics (V2-ADR-004, PRD 6, Issue #212):

Platform disabled is a hard ceiling — no tenant override can re-enable.
Platform enable does NOT implicitly disable tenants with no tenant override.

Resolution matrix (platform × tenant → effective):

| Platform | Tenant   | Effective |
|----------|----------|-----------|
| absent   | absent   | ENABLED   |
| absent   | true     | ENABLED   |
| absent   | false    | DISABLED  |
| true     | absent   | ENABLED   |
| true     | true     | ENABLED   |
| true     | false    | DISABLED  |
| false    | absent   | DISABLED  |
| false    | true     | DISABLED  |
| false    | false    | DISABLED  |

Unknown capability ID -> DISABLED (fail closed).
"""

from typing import List, Optional

from arc.domain.models import (
    KNOWN_CAPABILITIES,
    PlatformCapability,
)
from arc.repositories import CapabilityRepository


class CapabilityService:
    """Capability resolution and management service.

    Args:
        repository: persistence layer for platform and tenant capability
            state.
    """

    def __init__(self, repository: CapabilityRepository):
        self._repo = repository

    @staticmethod
    def is_effective(platform_enabled: Optional[bool], tenant_enabled: Optional[bool]) -> bool:
        """Resolve the effective capability state.

        Platform ``False`` is a hard ceiling — disabled for all tenants
        regardless of tenant override. Tenant ``False`` explicitly
        disables. Otherwise the capability is enabled (covers
        platform-absent and platform-enabled with absent tenant
        override — V2-ADR-004, Issue #212).
        """
        if platform_enabled is False:
            return False  # hard ceiling
        if tenant_enabled is False:
            return False  # tenant explicitly disabled
        return True

    async def is_enabled(self, tenant_id: str, capability_id: str) -> bool:
        """Check whether a capability is effective for a tenant.

        Returns ``False`` for unknown capability IDs (fail closed).
        """
        if capability_id not in KNOWN_CAPABILITIES:
            return False
        platform = await self._repo.get_platform_capability(capability_id)
        platform_enabled = platform.enabled if platform else None
        tenant = await self._repo.get_tenant_capability(tenant_id, capability_id)
        tenant_enabled = tenant.enabled if tenant else None
        return self.is_effective(platform_enabled, tenant_enabled)

    async def list_platform(self) -> List[PlatformCapability]:
        """Return all platform capability states."""
        return await self._repo.list_platform_capabilities()

    async def get_platform(self, capability_id: str) -> Optional[PlatformCapability]:
        """Return the platform state for one capability."""
        return await self._repo.get_platform_capability(capability_id)

    async def set_platform(self, capability_id: str, enabled: bool) -> PlatformCapability:
        """Set the platform state for a capability.

        Raises ``ValueError`` for unknown capability IDs.
        """
        if capability_id not in KNOWN_CAPABILITIES:
            raise ValueError(f"Unknown capability: {capability_id!r}")
        return await self._repo.set_platform_capability(capability_id, enabled)

    async def list_tenant(self, tenant_id: str) -> List[dict]:
        """Return effective capability state for a tenant.

        Each entry includes platform_enabled, tenant_enabled, and
        effective_enabled so the API can present the full picture.
        """
        platform_states = await self._repo.list_platform_capabilities()
        tenant_states = await self._repo.list_tenant_capabilities(tenant_id)
        tenant_map = {tc.capability_id: tc.enabled for tc in tenant_states}
        results = []
        for pc in platform_states:
            te = tenant_map.get(pc.capability_id)
            results.append(
                {
                    "capability_id": pc.capability_id,
                    "platform_enabled": pc.enabled,
                    "tenant_enabled": te,
                    "effective_enabled": self.is_effective(pc.enabled, te),
                }
            )
        return results

    async def get_tenant(self, tenant_id: str, capability_id: str) -> Optional[dict]:
        """Return effective state for one capability of a tenant."""
        if capability_id not in KNOWN_CAPABILITIES:
            return None
        pc = await self._repo.get_platform_capability(capability_id)
        tc = await self._repo.get_tenant_capability(tenant_id, capability_id)
        platform_enabled = pc.enabled if pc else None
        tenant_enabled = tc.enabled if tc else None
        return {
            "capability_id": capability_id,
            "platform_enabled": platform_enabled,
            "tenant_enabled": tenant_enabled,
            "effective_enabled": self.is_effective(platform_enabled, tenant_enabled),
        }

    async def set_tenant(self, tenant_id: str, capability_id: str, enabled: bool) -> dict:
        """Set the tenant config for a capability.

        Raises ``ValueError`` for unknown capability IDs. The platform
        capability must be seeded first (set via ``set_platform``).
        """
        if capability_id not in KNOWN_CAPABILITIES:
            raise ValueError(f"Unknown capability: {capability_id!r}")
        await self._repo.set_tenant_capability(tenant_id, capability_id, enabled)
        return await self.get_tenant(tenant_id, capability_id)
