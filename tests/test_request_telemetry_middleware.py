"""Regression tests for request-telemetry attribution (Issue #240).

Drives ``RequestTelemetryMiddleware`` directly over minimal ASGI scopes:
unmatched requests must log the single bounded ``unrouted`` label (never
the raw path), and tenant-scoped routes carrying ``tenant_id`` in the
query string must attribute the tenant. No other query parameter may
become a telemetry dimension.
"""

from arc.api.middleware import RequestTelemetryMiddleware


class _Route:
    def __init__(self, path):
        self.path = path


class _Service:
    def __init__(self):
        self.records = []

    async def record_api_request(self, record):
        self.records.append(record)


async def _run(path, *, status=200, route=None, path_params=None, query=b"", method="GET"):
    service = _Service()

    async def app(scope, receive, send):
        if route is not None:
            scope["route"] = route
        if path_params is not None:
            scope["path_params"] = path_params
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(message):
        sent.append(message)

    middleware = RequestTelemetryMiddleware(app, lambda: service)
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query,
        "headers": [],
    }
    await middleware(scope, receive, send)
    assert len(service.records) == 1
    return service.records[0]


async def test_unrouted_request_logs_stable_fallback():
    record = await _run("/openapi.json", status=200)
    assert record.route_template == "unrouted"
    assert record.route_template != "unmatched"
    assert "openapi.json" not in record.route_template


async def test_unrouted_paths_share_one_bounded_label():
    first = await _run("/users/123456", status=404)
    second = await _run("/users/789", status=404)
    assert first.route_template == second.route_template == "unrouted"
    assert first.error_kind == second.error_kind == "client_error"


async def test_query_scoped_tenant_route_logs_tenant():
    record = await _run(
        "/skills",
        status=200,
        route=_Route("/skills"),
        path_params={},
        query=b"tenant_id=t-1&limit=5",
    )
    assert record.route_template == "/skills"
    assert record.tenant_id == "t-1"


async def test_path_param_tenant_takes_precedence_over_query():
    record = await _run(
        "/tenants/t-path/skills",
        status=200,
        route=_Route("/tenants/{tenant_id}/skills"),
        path_params={"tenant_id": "t-path"},
        query=b"tenant_id=t-query",
    )
    assert record.tenant_id == "t-path"


async def test_failed_request_stays_unattributed():
    record = await _run(
        "/skills",
        status=404,
        route=_Route("/skills"),
        path_params={},
        query=b"tenant_id=t-1",
    )
    assert record.tenant_id is None
    assert record.error_kind == "client_error"


async def test_other_query_params_are_ignored():
    record = await _run(
        "/skills",
        status=200,
        route=_Route("/skills"),
        path_params={},
        query=b"foo=bar&limit=5",
    )
    assert record.tenant_id is None
    assert "?" not in record.route_template


async def test_matched_route_template_preserved():
    record = await _run(
        "/tenants/t-1/knowledge",
        status=200,
        route=_Route("/tenants/{tenant_id}/knowledge"),
        path_params={"tenant_id": "t-1"},
    )
    assert record.route_template == "/tenants/{tenant_id}/knowledge"
    assert record.tenant_id == "t-1"
