"""Request-telemetry middleware (PRD 17, TRD 17/28/31; approved design).

Responsibilities (Observability-owned correlation infrastructure):

1. Mint a UUID4 correlation ID per HTTP request and publish it through
   ``arc.api.correlation.request_id_var`` for structured logging.
2. Return it to the caller as the ``X-Request-ID`` response header,
   including on handled error responses.
3. Measure request duration with a monotonic clock.
4. Record a metadata-only ``ApiRequestRecord`` AFTER the response.

Tenant attribution is RESOLVED-CONTEXT LABELING: a request is labelled
with a tenant ONLY when the application's tenant dependency resolved and
authorized a tenant for it (published to request state, covering
path-bound tenant routes such as ``GET /tenants/{tenant_id}/skills``).
Raw client input — path parameters, query strings — is never trusted as
the attribution source, so an unrelated endpoint cannot be attributed by
merely adding ``?tenant_id=``. This is telemetry bookkeeping — it must
NEVER establish tenant identity or authorization; unauthenticated,
unauthorized, malformed and public requests are recorded with
tenant_id = NULL, because none of them establishes a context.

Attribution was previously ALSO gated on ``status < 400``. That made
per-tenant error counts structurally always zero: every failure
recorded NULL, so an error spike pooled entirely into "Unattributed"
and could not be traced to a customer. The status gate is gone; the
context gate, which is the one that carries the security property,
remains. A request that failed BEFORE establishing a context — a
cross-tenant probe, a failed sign-in — still records NULL, because the
state key was never written.

Telemetry writes are BEST-EFFORT: any failure is dropped by the
observability service without ever failing the served business response.
Route templates are normalized (never raw paths or query strings);
requests outside the route table share the single ``unrouted`` label.
"""

import logging
import time
import uuid
from typing import Callable, Optional

from arc.api.correlation import request_id_var
from arc.domain.models import ApiRequestRecord
from arc.security.dependencies import RESOLVED_TENANT_STATE_KEY

logger = logging.getLogger("arc.http")


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
        if status_code >= 400:
            error_kind = "client_error" if status_code < 500 else "server_error"

        # Attribution is keyed on whether a trusted context was actually
        # ESTABLISHED, not on whether the response succeeded.
        #
        # This used to be gated on `status_code < 400`, which meant every
        # error was recorded with tenant_id = NULL. Per-tenant error
        # counts were therefore structurally always zero, and an error
        # spike pooled entirely into "Unattributed" -- defeating the one
        # question the per-tenant view exists to answer (ADR-010).
        #
        # Reading the resolved tenant regardless of status is safe
        # BECAUSE of what sets it: `get_trusted_tenant_context` writes
        # RESOLVED_TENANT_STATE_KEY only after membership is verified. A
        # cross-tenant probe fails while establishing the context, so the
        # key is never written and the request still records NULL. The
        # same holds for unauthenticated and failed-auth requests.
        #
        # What DOES attribute now is the case that matters: a member of a
        # tenant whose request reached the handler and then failed -- a
        # 5xx, or a 403 from a permission check that runs after the
        # context is established. Those are that tenant's errors.
        state = scope.get("state") or {}
        candidate = state.get(RESOLVED_TENANT_STATE_KEY) if isinstance(state, dict) else None
        if isinstance(candidate, str) and candidate:
            tenant_id = candidate

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
