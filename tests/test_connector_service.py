"""Tests for the ConnectorService with mocked repository."""

from unittest.mock import AsyncMock

import pytest

from arc.db.connection import NotFoundError
from arc.domain.models import (
    ConnectorConfig,
    ConnectorProvider,
    ConnectorStatus,
    TenantContext,
    UserRole,
)
from arc.repositories import ConnectorRepository
from arc.services.connectors import ConnectorService


@pytest.fixture
def connector_repo():
    """Create a mock ConnectorRepository."""
    return AsyncMock(spec=ConnectorRepository)


@pytest.fixture
def service(connector_repo):
    """Create a ConnectorService with the mock repository."""
    return ConnectorService(connector_repo)


@pytest.fixture
def tenant_context():
    """Create a trusted TenantContext for testing."""
    return TenantContext(
        tenant_id="tenant-1",
        tenant_name="Test Tenant",
        user_id="user-1",
        role=UserRole.MEMBER,
    )


class TestConnectorServiceCreate:
    """Test create_connector delegation and validation."""

    async def test_create_connector_delegates_to_repo(
        self, service, connector_repo, tenant_context
    ):
        """Test that create_connector calls repository create with trusted tenant_id."""
        expected = ConnectorConfig(
            id="generated-id",
            tenant_id=tenant_context.tenant_id,
            provider=ConnectorProvider.SLACK,
            name="Slack Workspace",
        )
        connector_repo.create.return_value = expected

        result = await service.create_connector(
            context=tenant_context,
            provider=ConnectorProvider.SLACK,
            name="Slack Workspace",
        )

        assert result == expected
        connector_repo.create.assert_called_once()
        call_args = connector_repo.create.call_args
        created = call_args[0][0]
        assert created.tenant_id == tenant_context.tenant_id
        assert created.provider == ConnectorProvider.SLACK
        assert created.name == "Slack Workspace"
        assert created.status == ConnectorStatus.ACTIVE

    async def test_create_connector_validates_name(self, service, tenant_context):
        """Test empty name raises ValueError."""
        with pytest.raises(ValueError, match="Connector config name cannot be empty"):
            await service.create_connector(
                context=tenant_context,
                provider=ConnectorProvider.SLACK,
                name="",
            )

    async def test_create_connector_propagates_duplicate_error(
        self, service, connector_repo, tenant_context
    ):
        """Test that DuplicateKeyError from repo propagates."""
        from arc.db.connection import DuplicateKeyError

        connector_repo.create.side_effect = DuplicateKeyError("duplicate")

        with pytest.raises(DuplicateKeyError):
            await service.create_connector(
                context=tenant_context,
                provider=ConnectorProvider.SLACK,
                name="Slack",
            )


class TestConnectorServiceGet:
    """Test get_connector delegation."""

    async def test_get_connector_delegates_to_repo(
        self, service, connector_repo, tenant_context
    ):
        """Test that get_connector calls repository get_by_id with tenant_id from context."""
        expected = ConnectorConfig(
            id="c1",
            tenant_id=tenant_context.tenant_id,
            provider=ConnectorProvider.GITHUB,
            name="GitHub",
        )
        connector_repo.get_by_id.return_value = expected

        result = await service.get_connector(tenant_context, "c1")

        assert result == expected
        connector_repo.get_by_id.assert_called_once_with(
            "c1", tenant_context.tenant_id
        )

    async def test_get_connector_propagates_not_found(
        self, service, connector_repo, tenant_context
    ):
        """Test that NotFoundError from repo propagates."""
        connector_repo.get_by_id.side_effect = NotFoundError("not found")

        with pytest.raises(NotFoundError):
            await service.get_connector(tenant_context, "missing-id")


class TestConnectorServiceList:
    """Test list_connectors delegation."""

    async def test_list_connectors_delegates_to_repo(
        self, service, connector_repo, tenant_context
    ):
        """Test list_connectors calls repository with tenant_id from context."""
        expected = [
            ConnectorConfig(
                id="c1",
                tenant_id=tenant_context.tenant_id,
                provider=ConnectorProvider.SLACK,
                name="Slack",
            )
        ]
        connector_repo.list_for_tenant.return_value = expected

        result = await service.list_connectors(tenant_context)

        assert result == expected
        connector_repo.list_for_tenant.assert_called_once_with(
            tenant_context.tenant_id
        )


class TestConnectorServiceDelete:
    """Test delete_connector delegation."""

    async def test_delete_connector_delegates_to_repo(
        self, service, connector_repo, tenant_context
    ):
        """Test that delete_connector calls repository delete with tenant_id from context."""
        await service.delete_connector(tenant_context, "c1")

        connector_repo.delete.assert_called_once_with(
            "c1", tenant_context.tenant_id
        )
