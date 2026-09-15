"""Connector service for Arc multi-tenant connector configuration.

The ConnectorService accepts a trusted ``TenantContext`` established by
X-10 and extracts the tenant boundary from it.  The service never
queries tenancy tables, never authenticates users, and never authorizes
callers.
"""

import uuid
from datetime import datetime, timezone

from arc.domain.models import (
    ConnectorConfig,
    ConnectorProvider,
    ConnectorStatus,
    TenantContext,
)
from arc.repositories import ConnectorRepository


class ConnectorService:
    """Domain service for connector configuration operations."""

    def __init__(self, connector_repo: ConnectorRepository):
        self.connector_repo = connector_repo

    async def create_connector(
        self,
        context: TenantContext,
        provider: ConnectorProvider,
        name: str,
        target: str = "",
    ) -> ConnectorConfig:
        """Create a new connector configuration for a tenant.

        The ``context`` must be an already-validated TenantContext
        established by X-10's TenantContextService.  The service
        extracts the trusted tenant_id from it.
        """
        if not name:
            raise ValueError("Connector config name cannot be empty")

        connector = ConnectorConfig(
            id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            provider=provider,
            name=name,
            target=target,
            status=ConnectorStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        return await self.connector_repo.create(connector)

    async def get_connector(self, context: TenantContext, connector_id: str) -> ConnectorConfig:
        """Get a connector configuration by ID within a tenant."""
        return await self.connector_repo.get_by_id(connector_id, context.tenant_id)

    async def list_connectors(self, context: TenantContext) -> list:
        """List all connector configurations for a tenant."""
        return await self.connector_repo.list_for_tenant(context.tenant_id)

    async def list_connectors_paginated(
        self, context: TenantContext, limit: int, offset: int
    ) -> tuple:
        """List connectors with LIMIT/OFFSET and total count."""
        return await self.connector_repo.list_for_tenant_paginated(context.tenant_id, limit, offset)

    async def delete_connector(self, context: TenantContext, connector_id: str) -> None:
        """Delete a connector configuration within a tenant."""
        await self.connector_repo.delete(connector_id, context.tenant_id)
