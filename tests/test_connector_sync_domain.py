"""Domain model tests for ConnectorSyncRecord audit entities."""

import uuid
from datetime import datetime, timezone

import pytest

from arc.domain.models import (
    ConnectorProvider,
    ConnectorSyncRecord,
    ConnectorSyncStatus,
)


def _unique(prefix: str) -> str:
    return f"csd-{prefix}-{uuid.uuid4().hex[:10]}"


def _record(**overrides):
    values = dict(
        id=_unique("record"),
        tenant_id=_unique("tenant"),
        connector_id=_unique("connector"),
        provider=ConnectorProvider.GITHUB,
        status=ConnectorSyncStatus.SUCCESS,
        items_fetched=3,
        created_at=datetime.now(timezone.utc),
    )
    values.update(overrides)
    return ConnectorSyncRecord(**values)


class TestConnectorSyncRecordValidation:
    def test_success_record_without_error_kind_is_valid(self):
        record = _record()
        assert record.status is ConnectorSyncStatus.SUCCESS
        assert record.error_kind is None

    def test_failed_record_with_error_kind_is_valid(self):
        record = _record(
            status=ConnectorSyncStatus.FAILED,
            items_fetched=0,
            error_kind="auth_failed",
        )
        assert record.error_kind == "auth_failed"

    def test_empty_id_is_rejected(self):
        with pytest.raises(ValueError, match="ID cannot be empty"):
            _record(id="")

    def test_empty_tenant_id_is_rejected(self):
        with pytest.raises(ValueError, match="Tenant ID cannot be empty"):
            _record(tenant_id="")

    def test_empty_connector_id_is_rejected(self):
        with pytest.raises(ValueError, match="Connector ID cannot be empty"):
            _record(connector_id="")

    def test_invalid_provider_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid connector provider"):
            _record(provider="github")

    def test_invalid_status_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid connector sync status"):
            _record(status="success")

    def test_negative_items_fetched_is_rejected(self):
        with pytest.raises(ValueError, match="non-negative integer"):
            _record(items_fetched=-1)

    def test_success_record_cannot_have_error_kind(self):
        with pytest.raises(ValueError, match="cannot have an error kind"):
            _record(error_kind="auth_failed")

    def test_failed_record_cannot_report_items(self):
        with pytest.raises(ValueError, match="cannot report fetched items"):
            _record(status=ConnectorSyncStatus.FAILED, items_fetched=1, error_kind="auth_failed")

    def test_failed_record_with_zero_items_is_valid(self):
        record = _record(
            status=ConnectorSyncStatus.FAILED,
            items_fetched=0,
            error_kind="transport_error",
        )
        assert record.items_fetched == 0
