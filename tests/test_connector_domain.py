"""Tests for Arc connector domain models."""

import pytest

from arc.domain.models import ConnectorConfig, ConnectorProvider, ConnectorStatus


class TestConnectorProvider:
    """Test ConnectorProvider enum."""

    def test_provider_values(self):
        """Test provider enum values."""
        assert ConnectorProvider.SLACK == "slack"
        assert ConnectorProvider.GITHUB == "github"
        assert ConnectorProvider.GOOGLE_DRIVE == "google_drive"
        assert ConnectorProvider.LINEAR == "linear"

    def test_provider_member_check(self):
        """Test that all expected providers are valid."""
        expected = {"slack", "github", "google_drive", "linear"}
        for provider in ConnectorProvider:
            assert provider.value in expected

    def test_provider_count(self):
        """Test that exactly four providers are defined."""
        assert len(ConnectorProvider) == 4


class TestConnectorStatus:
    """Test ConnectorStatus enum."""

    def test_status_values(self):
        """Test status enum values."""
        assert ConnectorStatus.ACTIVE == "active"
        assert ConnectorStatus.INACTIVE == "inactive"
        assert ConnectorStatus.ERROR == "error"

    def test_status_member_check(self):
        """Test that all expected statuses are valid."""
        expected = {"active", "inactive", "error"}
        for status in ConnectorStatus:
            assert status.value in expected


class TestConnectorConfigModel:
    """Test ConnectorConfig domain model."""

    def test_config_creation(self):
        """Test creating a connector config."""
        config = ConnectorConfig(
            id="test-connector-1",
            tenant_id="test-tenant-1",
            provider=ConnectorProvider.SLACK,
            name="Test Slack",
        )
        assert config.id == "test-connector-1"
        assert config.tenant_id == "test-tenant-1"
        assert config.provider == ConnectorProvider.SLACK
        assert config.name == "Test Slack"
        assert config.status == ConnectorStatus.ACTIVE

    def test_config_default_status(self):
        """Test default status is ACTIVE."""
        config = ConnectorConfig(
            id="c1",
            tenant_id="t1",
            provider=ConnectorProvider.GITHUB,
            name="GitHub",
        )
        assert config.status == ConnectorStatus.ACTIVE

    def test_config_explicit_status(self):
        """Test explicit status override."""
        config = ConnectorConfig(
            id="c1",
            tenant_id="t1",
            provider=ConnectorProvider.LINEAR,
            name="Linear",
            status=ConnectorStatus.INACTIVE,
        )
        assert config.status == ConnectorStatus.INACTIVE

    def test_config_default_timestamps(self):
        """Test that default timestamps are datetime instances."""
        from datetime import datetime

        config = ConnectorConfig(
            id="c1",
            tenant_id="t1",
            provider=ConnectorProvider.SLACK,
            name="Slack",
        )
        assert isinstance(config.created_at, datetime)
        assert isinstance(config.updated_at, datetime)

    def test_config_validation_empty_id(self):
        """Test empty ID raises ValueError."""
        with pytest.raises(ValueError, match="Connector config ID cannot be empty"):
            ConnectorConfig(
                id="",
                tenant_id="t1",
                provider=ConnectorProvider.SLACK,
                name="Slack",
            )

    def test_config_validation_empty_tenant_id(self):
        """Test empty tenant ID raises ValueError."""
        with pytest.raises(ValueError, match="Tenant ID cannot be empty"):
            ConnectorConfig(
                id="c1",
                tenant_id="",
                provider=ConnectorProvider.SLACK,
                name="Slack",
            )

    def test_config_validation_empty_name(self):
        """Test empty name raises ValueError."""
        with pytest.raises(ValueError, match="Connector config name cannot be empty"):
            ConnectorConfig(
                id="c1",
                tenant_id="t1",
                provider=ConnectorProvider.SLACK,
                name="",
            )
