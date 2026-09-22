"""Request-telemetry middleware (PRD 17, TRD 17/28/31; approved design).

Responsibilities (Observability-owned correlation infrastructure):

1. Mint a UUID4 correlation ID per HTTP request and publish it through
   ``arc.api.correlation.request_id_var`` for structured logging.
2. Return it to the caller as the ``X-Request-ID`` response header,
   including on handled error responses.
3. Measure request duration with a monotonic clock.
4. Record a metadata-only ``ApiRequestRecord`` AFTER the response.

Tenant attribution is SUCCESS-GATED LABELING (approved L1):
a request is labelled with a tenant ONLY when it completed with
status < 400 and carries a tenant ID — first the ``tenant_id`` path
parameter, then the ``tenant_id`` query parameter (some tenant-scoped
routes such as ``GET /skills`` bind the tenant through the query
string). This is telemetry bookkeeping — it must NEVER establish
tenant identity or authorization; failed, unauthorized, malformed,
and public requests are recorded with tenant_id = NULL.

Telemetry writes are BEST-EFFORT: any failure is dropped by the
observability service without ever failing the served business response.
Route templates are normalized (never raw paths or query strings);
requests outside the route table share the single ``unrouted`` label.
"""

import logging
import time
import uuid
from typing import Callable, Optional
from urllib.parse import parse_qsl

from arc.api.correlation import request_id_var
from arc.domain.models import ApiRequestRecord

logger = logging.getLogger("arc.http")


def _query_tenant_id(query_string) -> Optional[str]:
    """First non-empty ``tenant_id`` query value, else None.

    Only this one explicitly supported key is ever read: no other query
    parameter can become a telemetry dimension, and the raw query string
    itself is never stored or logged.
    """
    if isinstance(query_string, (bytes, bytearray)):
        # latin-1 never raises, so a hostile query string degrades to no
        # attribution instead of breaking telemetry recording entirely.
        raw = bytes(query_string).decode("latin-1")
    elif isinstance(query_string, str):
        raw = query_string
    else:
        return None
    for key, value in parse_qsl(raw):
        if key == "tenant_id" and value:
            return value
    return None


class RequestTelemetryMiddleware:
    """Pure-ASGI middleware: correlate, measure, then record best-effort."""

    UNMATCHED_ROUTE_TEMPLATE = "unrouted"

    def __init__(self, app, service_provider: Callable[[], Optional[object]]):
        self.app = app
        self._service_provider = service_provider

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        state = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = dict(message, headers=headers)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            try:
                # Response bytes were already delivered by send(); awaiting
                # the telemetry write here keeps recording deterministic
                # while remaining strictly BEST-EFFORT: no failure below can
                # alter or fail the served business response.
                await self._record(scope, state["status"], started, request_id)
            except Exception:
                logger.warning("telemetry_pipeline_failed route=%s", scope.get("route"))
            finally:
                request_id_var.reset(token)

    # ------------------------------------------------------------------
    async def _record(self, scope, status_code: int, started: float, request_id: str) -> None:
        duration_ms = max(int((time.perf_counter() - started) * 1000), 0)

        route = scope.get("route")
        template = getattr(route, "path", None) or self.UNMATCHED_ROUTE_TEMPLATE

        tenant_id: Optional[str] = None
        error_kind: Optional[str] = None
        if status_code < 400:
            candidate = (scope.get("path_params") or {}).get("tenant_id")
            if not (isinstance(candidate, str) and candidate):
                candidate = _query_tenant_id(scope.get("query_string", b""))
            if isinstance(candidate, str) and candidate:
                tenant_id = candidate
        else:
            error_kind = "client_error" if status_code < 500 else "server_error"

        logger.info(
            "%s %s -> %d duration_ms=%d tenant=%s",
            scope.get("method", ""),
            template,
            status_code,
            duration_ms,
            "attributed" if tenant_id else "unattributed",
        )

        service = self._service_provider()
        if service is None:
            return
        try:
            record = ApiRequestRecord(
                id=str(uuid.uuid4()),
                request_id=request_id,
                method=scope.get("method", "GET"),
                route_template=template,
                status_code=status_code,
                duration_ms=duration_ms,
                tenant_id=tenant_id,
                error_kind=error_kind,
            )
        except ValueError:
            logger.warning("telemetry_record_rejected route=%s", template)
            return
        # record_api_request never raises (best-effort contract); guard
        # defensively anyway so telemetry can never break a request.
        await service.record_api_request(record)
