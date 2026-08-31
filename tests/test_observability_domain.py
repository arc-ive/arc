"""Domain validation tests for Observability telemetry records (TRD 17).

ApiRequestRecord is metadata-only by contract: these tests pin the
fail-closed validation surface (identifiers, HTTP method allowlist,
status bounds, non-negative duration) and the guarantees that keep
untrusted request material out of persistence.
"""

import pytest

from arc.domain.models import (
    ApiRequestRecord,
    ApprovalActivityMetrics,
    ConnectorSyncActivityMetrics,
    HttpUsageMetrics,
    ToolExecutionActivityMetrics,
    WebhookEventActivityMetrics,
)


def _record(**overrides):
    defaults = dict(
        id="req-record-1",
        request_id="0f4a2d3c-0000-4000-8000-000000000001",
        method="GET",
        route_template="/tenants/{tenant_id}/tools",
        status_code=200,
        duration_ms=12,
    )
    defaults.update(overrides)
    return ApiRequestRecord(**defaults)


class TestApiRequestRecordValidation:
    def test_valid_minimal_record(self):
        record = _record()
        assert record.tenant_id is None
        assert record.error_kind is None
        assert record.created_at is not None

    def test_valid_attributed_record(self):
        record = _record(tenant_id="t-1", error_kind="client_error")
        assert record.tenant_id == "t-1"
        assert record.error_kind == "client_error"

    def test_empty_record_id_rejected(self):
        with pytest.raises(ValueError):
            _record(id="")

    def test_oversized_record_id_rejected(self):
        with pytest.raises(ValueError):
            _record(id="x" * 256)

    def test_empty_request_id_rejected(self):
        with pytest.raises(ValueError):
            _record(request_id="")

    def test_oversized_request_id_rejected(self):
        with pytest.raises(ValueError):
            _record(request_id="x" * 65)

    @pytest.mark.parametrize("method", ["", "TRACE", "CONNECT", "get", "fetch"])
    def test_invalid_http_methods_rejected(self, method):
        with pytest.raises(ValueError):
            _record(method=method)

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    def test_allowed_http_methods_accepted(self, method):
        assert _record(method=method).method == method

    def test_empty_route_template_rejected(self):
        with pytest.raises(ValueError):
            _record(route_template="")

    def test_oversized_route_template_rejected(self):
        with pytest.raises(ValueError):
            _record(route_template="/" + "x" * 255)

    def test_query_string_in_route_template_rejected(self):
        with pytest.raises(ValueError):
            _record(route_template="/health?user=secret")

    def test_status_code_below_range_rejected(self):
        with pytest.raises(ValueError):
            _record(status_code=99)

    def test_status_code_above_range_rejected(self):
        with pytest.raises(ValueError):
            _record(status_code=600)

    def test_non_integer_status_code_rejected(self):
        with pytest.raises(ValueError):
            _record(status_code="200")

    def test_negative_duration_rejected(self):
        with pytest.raises(ValueError):
            _record(duration_ms=-1)

    def test_non_integer_duration_rejected(self):
        with pytest.raises(ValueError):
            _record(duration_ms=1.5)

    def test_blank_attributed_tenant_id_rejected(self):
        with pytest.raises(ValueError):
            _record(tenant_id="")

    def test_blank_error_kind_rejected(self):
        with pytest.raises(ValueError):
            _record(error_kind="")


class TestMetricReadModels:
    def test_http_usage_metrics_accepts_zero_traffic(self):
        metrics = HttpUsageMetrics(
            total_requests=0,
            error_count=0,
            error_rate=0.0,
            avg_duration_ms=0.0,
            p95_duration_ms=0.0,
        )
        assert metrics.total_requests == 0

    def test_http_usage_metrics_error_count_cannot_exceed_total(self):
        with pytest.raises(ValueError):
            HttpUsageMetrics(
                total_requests=5,
                error_count=6,
                error_rate=0.0,
                avg_duration_ms=0.0,
                p95_duration_ms=0.0,
            )

    def test_http_usage_metrics_rate_bounds(self):
        with pytest.raises(ValueError):
            HttpUsageMetrics(
                total_requests=10,
                error_count=1,
                error_rate=1.5,
                avg_duration_ms=0.0,
                p95_duration_ms=0.0,
            )

    def test_http_usage_metrics_negative_latency_rejected(self):
        with pytest.raises(ValueError):
            HttpUsageMetrics(
                total_requests=1,
                error_count=0,
                error_rate=0.0,
                avg_duration_ms=-1.0,
                p95_duration_ms=0.0,
            )

    def test_tool_activity_breakdown_cannot_exceed_total(self):
        with pytest.raises(ValueError):
            ToolExecutionActivityMetrics(total_executions=2, successful=2, failed=1, denied=0)

    def test_connector_activity_negative_counts_rejected(self):
        with pytest.raises(ValueError):
            ConnectorSyncActivityMetrics(total_syncs=1, successful=1, failed=0, items_fetched=-1)

    def test_webhook_metrics_default_to_unavailable_source(self):
        metrics = WebhookEventActivityMetrics(available=False)
        assert metrics.available is False
        assert metrics.total_events == 0

    def test_webhook_metrics_negative_counts_rejected(self):
        with pytest.raises(ValueError):
            WebhookEventActivityMetrics(available=True, total_events=-1)


class TestApprovalActivityMetrics:
    def test_approval_activity_metrics_accepts_zero_approvals(self):
        metrics = ApprovalActivityMetrics(
            total=0, pending=0, approved=0, rejected=0, expired=0, consumed=0
        )
        assert metrics.total == 0

    def test_approval_activity_metrics_valid_counts(self):
        metrics = ApprovalActivityMetrics(
            total=10, pending=3, approved=2, rejected=1, expired=2, consumed=2
        )
        assert metrics.total == 10
        assert metrics.pending == 3
        assert metrics.consumed == 2

    def test_approval_activity_breakdown_cannot_exceed_total(self):
        with pytest.raises(ValueError):
            ApprovalActivityMetrics(
                total=2, pending=1, approved=1, rejected=1, expired=0, consumed=0
            )

    def test_approval_activity_negative_counts_rejected(self):
        with pytest.raises(ValueError):
            ApprovalActivityMetrics(
                total=0, pending=-1, approved=0, rejected=0, expired=0, consumed=0
            )

    def test_approval_activity_negative_consumed_rejected(self):
        with pytest.raises(ValueError):
            ApprovalActivityMetrics(
                total=0, pending=0, approved=0, rejected=0, expired=0, consumed=-1
            )
