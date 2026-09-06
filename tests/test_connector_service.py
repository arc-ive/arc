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


@pytest.fixture
def other_tenant_context():
    """Create a second trusted TenantContext for a different tenant."""
    return TenantContext(
        tenant_id="tenant-2",
        tenant_name="Other Tenant",
        user_id="user-2",
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
            target="#general",
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

    async def test_get_connector_delegates_to_repo(self, service, connector_repo, tenant_context):
        """Test that get_connector calls repository get_by_id with tenant_id from context."""
        expected = ConnectorConfig(
            id="c1",
            tenant_id=tenant_context.tenant_id,
            provider=ConnectorProvider.GITHUB,
            name="GitHub",
            target="org/repo",
        )
        connector_repo.get_by_id.return_value = expected

        result = await service.get_connector(tenant_context, "c1")

        assert result == expected
        connector_repo.get_by_id.assert_called_once_with("c1", tenant_context.tenant_id)

    async def test_get_connector_propagates_not_found(
        self, service, connector_repo, tenant_context
    ):
        """Test that NotFoundError from repo propagates."""
        connector_repo.get_by_id.side_effect = NotFoundError("not found")

        with pytest.raises(NotFoundError):
            await service.get_connector(tenant_context, "missing-id")


class TestConnectorServiceList:
    """Test list_connectors delegation."""

    async def test_list_connectors_delegates_to_repo(self, service, connector_repo, tenant_context):
        """Test list_connectors calls repository with tenant_id from context."""
        expected = [
            ConnectorConfig(
                id="c1",
                tenant_id=tenant_context.tenant_id,
                provider=ConnectorProvider.SLACK,
                name="Slack",
                target="#general",
            )
        ]
        connector_repo.list_for_tenant.return_value = expected

        result = await service.list_connectors(tenant_context)

        assert result == expected
        connector_repo.list_for_tenant.assert_called_once_with(tenant_context.tenant_id)


class TestConnectorServiceDelete:
    """Test delete_connector delegation."""

    async def test_delete_connector_delegates_to_repo(
        self, service, connector_repo, tenant_context
    ):
        """Test that delete_connector calls repository delete with tenant_id from context."""
        await service.delete_connector(tenant_context, "c1")

        connector_repo.delete.assert_called_once_with("c1", tenant_context.tenant_id)


class TestConnectorServiceTenantIsolation:
    """Prove that different TenantContext instances produce different
    tenant_id values in repository calls."""

    async def test_create_uses_context_tenant_id(self, service, connector_repo):
        """Test create_connector derives tenant_id from context."""
        ctx_a = TenantContext(
            tenant_id="tenant-A",
            tenant_name="Tenant A",
            user_id="user-a",
            role=UserRole.MEMBER,
        )
        ctx_b = TenantContext(
            tenant_id="tenant-B",
            tenant_name="Tenant B",
            user_id="user-b",
            role=UserRole.MEMBER,
        )
        connector_repo.create.return_value = ConnectorConfig(
            id="id", tenant_id="x", provider=ConnectorProvider.SLACK, name="x", target="x"
        )

        await service.create_connector(ctx_a, ConnectorProvider.SLACK, "A")
        created_a = connector_repo.create.call_args[0][0]
        assert created_a.tenant_id == "tenant-A"

        await service.create_connector(ctx_b, ConnectorProvider.SLACK, "B")
        created_b = connector_repo.create.call_args[0][0]
        assert created_b.tenant_id == "tenant-B"

        assert created_a.tenant_id != created_b.tenant_id

    async def test_get_uses_context_tenant_id(self, service, connector_repo):
        """Test get_connector passes context.tenant_id to repository."""
        ctx_a = TenantContext(
            tenant_id="tenant-A",
            tenant_name="Tenant A",
            user_id="user-a",
            role=UserRole.MEMBER,
        )
        ctx_b = TenantContext(
            tenant_id="tenant-B",
            tenant_name="Tenant B",
            user_id="user-b",
            role=UserRole.MEMBER,
        )
        connector_repo.get_by_id.return_value = ConnectorConfig(
            id="c1", tenant_id="x", provider=ConnectorProvider.SLACK, name="x", target="x"
        )

        await service.get_connector(ctx_a, "c1")
        assert connector_repo.get_by_id.call_args[0] == ("c1", "tenant-A")

        await service.get_connector(ctx_b, "c1")
        assert connector_repo.get_by_id.call_args[0] == ("c1", "tenant-B")

    async def test_list_uses_context_tenant_id(self, service, connector_repo):
        """Test list_connectors passes context.tenant_id to repository."""
        ctx_a = TenantContext(
            tenant_id="tenant-A",
            tenant_name="Tenant A",
            user_id="user-a",
            role=UserRole.MEMBER,
        )
        ctx_b = TenantContext(
            tenant_id="tenant-B",
            tenant_name="Tenant B",
            user_id="user-b",
            role=UserRole.MEMBER,
        )
        connector_repo.list_for_tenant.return_value = []

        await service.list_connectors(ctx_a)
        assert connector_repo.list_for_tenant.call_args[0] == ("tenant-A",)

        await service.list_connectors(ctx_b)
        assert connector_repo.list_for_tenant.call_args[0] == ("tenant-B",)

    async def test_delete_uses_context_tenant_id(self, service, connector_repo):
        """Test delete_connector passes context.tenant_id to repository."""
        ctx_a = TenantContext(
            tenant_id="tenant-A",
            tenant_name="Tenant A",
            user_id="user-a",
            role=UserRole.MEMBER,
        )
        ctx_b = TenantContext(
            tenant_id="tenant-B",
            tenant_name="Tenant B",
            user_id="user-b",
            role=UserRole.MEMBER,
        )

        await service.delete_connector(ctx_a, "c1")
        assert connector_repo.delete.call_args[0] == ("c1", "tenant-A")

        await service.delete_connector(ctx_b, "c1")
        assert connector_repo.delete.call_args[0] == ("c1", "tenant-B")
