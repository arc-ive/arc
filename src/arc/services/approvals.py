"""Human Intervention approval-gate service (V1 foundation; ADR-004).

Owns ONLY the approval lifecycle: idempotent creation of pending
requests, tenant-scoped listing/reading with lazy expiry derivation,
terminal approve/reject decisions, and the ATOMIC single-use consumption
boundary that a later ToolExecutionService integration will call before
executing an approved request.

Hard boundaries:

- This service NEVER executes, validates, authorizes, or audits tools.
  ToolExecutionService remains the sole authorization/validation/policy/
  execution/audit boundary; approval existence never substitutes for tool
  authorization (an approved request still goes through a full,
  authorized ``execute_tool`` call which consumes it first).
- Raw tool arguments are never accepted or stored — only the redacted
  summary and the SHA-256 digest of the canonically VALIDATED arguments,
  both computed inside the execution boundary.
- Tenant identity comes exclusively from the trusted X-10 context;
  every repository call is tenant-scoped and fails closed.
- Expiry is LAZY (24 h V1 TTL): reads derive expiry from ``expires_at``
  without mutating; decision/consumption transitions past-due pending
  rows to terminal ``expired`` atomically.  A background sweep provides
  persistence-level cleanup of stale pending rows (PRD §15).

Creation is BEST-EFFORT from the caller's perspective: the denial that
triggered it is fail-closed regardless, so a persistence failure is
logged safely and never breaks the served business response.
"""

import dataclasses
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from arc.db.connection import CorruptDataError, DuplicateKeyError, NotFoundError
from arc.domain.models import ApprovalRequest, ApprovalStatus, TenantContext

logger = logging.getLogger("arc.approvals")

TTL_HOURS = 24


class ApprovalError(Exception):
    """Base class for controlled approval-gate failures."""


class ApprovalNotFoundError(ApprovalError):
    """The approval ID does not exist within the trusted tenant."""


class ApprovalStateError(ApprovalError):
    """The request is not in the state required for this operation."""


class ApprovalExpiredError(ApprovalStateError):
    """The request's 24-hour TTL elapsed before this operation."""


class ApprovalBindingError(ApprovalError):
    """Tool identity/version/argument digest do not match the approval."""


class ApprovalConsumedError(ApprovalStateError):
    """The approval was already consumed (single-use replay prevention)."""


class ApprovalSelfDecisionError(ApprovalError):
    """The requester attempted to approve or reject their own request."""


class ApprovalCorruptError(ApprovalError):
    """A persisted approval row violates an application invariant.

    Defense-in-depth for legacy/corrupt data that predates the database
    CHECK constraint (Issue #239). Fail-closed and observable: callers
    must surface a controlled error, never treat the row as valid.
    """


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _corrupt_error(approval_id: str, tenant_id: str, exc: Exception) -> ApprovalCorruptError:
    """Log and build the controlled error for a corrupt persisted row.

    The log carries identifiers only (never secrets); the error message
    surfaced to callers carries no database internals.
    """
    logger.warning(
        "approval_row_corrupt approval_id=%s tenant_id=%s",
        approval_id,
        tenant_id,
        exc_info=True,
    )
    return ApprovalCorruptError(
        f"Approval request {approval_id} is unreadable and requires operator attention"
    )


class HumanApprovalService:
    """Lifecycle service for Human Intervention approval requests."""

    def __init__(self, repository, clock=_utc_now):
        self.repository = repository
        self._clock = clock

    # ------------------------------------------------------------------
    # Creation (called by ToolExecutionService on REQUIRE_HUMAN_APPROVAL)
    # ------------------------------------------------------------------
    async def record_required_approval(
        self,
        *,
        tenant_id: str,
        requester_user_id: str,
        tool_name: str,
        tool_version: str,
        risk_level: str,
        input_summary: str,
        arguments_digest: str,
        encrypted_input: Optional[bytes] = None,
        input_key_version: Optional[int] = None,
    ) -> Optional[str]:
        """Create (or reuse) one pending approval for the exact binding.

        Best-effort: returns the approval ID, or ``None`` when persistence
        fails. The triggering denial is fail-closed either way, so a
        telemetry-like failure here must never break the served response.
        Idempotent per (tenant, tool, version, digest): an existing open
        (pending, unexpired) request is reused instead of duplicated.
        """
        try:
            existing = await self.repository.find_open(
                tenant_id, tool_name, tool_version, arguments_digest
            )
            if existing is not None:
                return existing.id
            now = self._clock()
            request = ApprovalRequest(
                id=f"appr-{uuid.uuid4().hex[:16]}",
                tenant_id=tenant_id,
                requester_user_id=requester_user_id,
                tool_name=tool_name,
                tool_version=tool_version,
                risk_level=risk_level,
                input_summary=input_summary,
                arguments_digest=arguments_digest,
                status=ApprovalStatus.PENDING,
                created_at=now,
                expires_at=now + timedelta(hours=TTL_HOURS),
                encrypted_input=encrypted_input,
                input_key_version=input_key_version,
            )
            created = await self.repository.create(request)
            return created.id
        except DuplicateKeyError:
            # Concurrent creation raced past the find_open check; the
            # unique partial index enforced idempotency.  Re-read the
            # existing open row so the caller gets a valid ID.
            existing = await self.repository.find_open(
                tenant_id, tool_name, tool_version, arguments_digest
            )
            if existing is not None:
                return existing.id
            return None
        except Exception:
            logger.warning(
                "approval_request_not_recorded tool=%s digest_prefix=%s",
                tool_name,
                arguments_digest[:12],
            )
            return None

    # ------------------------------------------------------------------
    # Reads (lazy expiry derived, never mutated)
    # ------------------------------------------------------------------
    def _with_effective_status(self, request: ApprovalRequest) -> ApprovalRequest:
        now = self._clock()
        effective = request.effective_status(now)
        if effective != request.status:
            return dataclasses.replace(request, status=effective)
        return request

    async def list_requests(self, context: TenantContext, status: Optional[ApprovalStatus] = None):
        """List requests for the trusted tenant, newest first."""
        try:
            requests = await self.repository.list_for_tenant(context.tenant_id)
        except CorruptDataError as exc:
            raise _corrupt_error("list", context.tenant_id, exc) from exc
        derived = [self._with_effective_status(r) for r in requests]
        if status is None:
            return derived
        return [r for r in derived if r.status == status]

    async def list_requests_paginated(
        self,
        context: TenantContext,
        limit: int,
        offset: int,
        status: Optional[ApprovalStatus] = None,
    ):
        """List requests with LIMIT/OFFSET and total count."""
        try:
            all_items, total = await self.repository.list_for_tenant_paginated(
                context.tenant_id, limit, offset
            )
        except CorruptDataError as exc:
            raise _corrupt_error("list", context.tenant_id, exc) from exc
        derived = [self._with_effective_status(r) for r in all_items]
        if status is not None:
            derived = [r for r in derived if r.status == status]
        return derived, total

    async def get_request(self, context: TenantContext, approval_id: str) -> ApprovalRequest:
        try:
            request = await self.repository.get_by_id(approval_id, context.tenant_id)
        except NotFoundError as exc:
            logger.debug("Approval %s not found for tenant %s", approval_id, context.tenant_id)
            raise ApprovalNotFoundError(str(exc)) from exc
        except CorruptDataError as exc:
            raise _corrupt_error(approval_id, context.tenant_id, exc) from exc
        return self._with_effective_status(request)

    # ------------------------------------------------------------------
    # Decisions (approve / reject) — pending rows only, lazy expiry first
    # ------------------------------------------------------------------
    async def decide_request(
        self,
        context: TenantContext,
        principal_user_id: str,
        approval_id: str,
        decision: ApprovalStatus,
    ) -> ApprovalRequest:
        """Approve or reject a PENDING request; terminal and immutable.

        Fails closed: unknown IDs raise :class:`ApprovalNotFoundError`;
        expired requests are transitioned to terminal ``expired`` — a
        system transition with NO human decider recorded — and surface as
        :class:`ApprovalExpiredError`; already-decided/consumed requests
        raise :class:`ApprovalStateError`/:class:`ApprovalConsumedError`.
        The requester may NOT approve or reject their own request.
        """
        if decision not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            raise ValueError("decision must be approved or rejected")
        try:
            current = await self.repository.get_by_id(approval_id, context.tenant_id)
        except NotFoundError as exc:
            logger.debug("Approval %s not found for tenant %s", approval_id, context.tenant_id)
            raise ApprovalNotFoundError(str(exc)) from exc
        except CorruptDataError as exc:
            raise _corrupt_error(approval_id, context.tenant_id, exc) from exc

        if current.status == ApprovalStatus.PENDING and self._clock() >= current.expires_at:
            await self.repository.expire_if_due(approval_id, context.tenant_id)
            raise ApprovalExpiredError(f"Approval {approval_id} expired before a decision was made")

        if current.requester_user_id == principal_user_id:
            raise ApprovalSelfDecisionError(
                f"Approval {approval_id} requester {principal_user_id}"
                " cannot approve or reject their own request"
            )

        performed = await self.repository.decide(
            approval_id, context.tenant_id, decision, principal_user_id
        )
        try:
            if not performed:
                refreshed = await self.repository.get_by_id(approval_id, context.tenant_id)
                if refreshed.status == ApprovalStatus.CONSUMED:
                    raise ApprovalConsumedError(f"Approval {approval_id} was already consumed")
                raise ApprovalStateError(
                    f"Approval {approval_id} is '{refreshed.status.value}' "
                    "and can no longer be decided"
                )
            return await self.repository.get_by_id(approval_id, context.tenant_id)
        except CorruptDataError as exc:
            raise _corrupt_error(approval_id, context.tenant_id, exc) from exc

    # ------------------------------------------------------------------
    # Consumption boundary (single-use; called before execute_tool)
    # ------------------------------------------------------------------
    async def consume_approval(
        self,
        context: TenantContext,
        approval_id: str,
        tool_name: str,
        tool_version: str,
        arguments_digest: str,
    ) -> ApprovalRequest:
        """Atomically consume ONE approved, unexpired, exactly-matching approval.

        Returns the consumed request. Every failure mode raises a precise
        controlled error; concurrent consumers are serialized by the
        single conditional UPDATE — exactly one succeeds, replays fail.
        """
        try:
            # Existence pre-check so an unknown ID surfaces as NotFound
            # rather than a generic consumption failure below.
            await self.repository.get_by_id(approval_id, context.tenant_id)
        except NotFoundError as exc:
            logger.debug("Approval %s not found for tenant %s", approval_id, context.tenant_id)
            raise ApprovalNotFoundError(str(exc)) from exc
        except CorruptDataError as exc:
            raise _corrupt_error(approval_id, context.tenant_id, exc) from exc

        performed = await self.repository.consume(
            approval_id,
            context.tenant_id,
            tool_name,
            tool_version,
            arguments_digest,
        )
        try:
            if performed:
                return await self.repository.get_by_id(approval_id, context.tenant_id)

            # Classify why consumption did not fire (fresh read).
            refreshed = await self.repository.get_by_id(approval_id, context.tenant_id)
        except CorruptDataError as exc:
            raise _corrupt_error(approval_id, context.tenant_id, exc) from exc
        if self._clock() >= refreshed.expires_at and refreshed.status == ApprovalStatus.PENDING:
            await self.repository.expire_if_due(approval_id, context.tenant_id)
            raise ApprovalExpiredError(f"Approval {approval_id} expired")
        if refreshed.status == ApprovalStatus.PENDING:
            raise ApprovalStateError(f"Approval {approval_id} has not been approved yet")
        if refreshed.status == ApprovalStatus.CONSUMED or refreshed.consumed_at is not None:
            raise ApprovalConsumedError(f"Approval {approval_id} was already consumed")
        if refreshed.status == ApprovalStatus.EXPIRED:
            raise ApprovalExpiredError(f"Approval {approval_id} expired")
        raise ApprovalBindingError(
            f"Approval {approval_id} does not match the requested "
            "tool identity/version/arguments binding"
        )

    # ------------------------------------------------------------------
    # Background sweep (PRD §15) — persistence-level expiry cleanup
    # ------------------------------------------------------------------
    async def approved_input_for_resume(
        self, context: TenantContext, approval_id: str
    ) -> Optional[bytes]:
        """Return the stored ciphertext for an APPROVED, unconsumed request.

        Fail-closed at every step, and deliberately narrow: this is the
        only way the exact arguments ever leave storage.

        - The approval is resolved tenant-scoped, so an id belonging to
          another tenant resolves to nothing.
        - It must be APPROVED. Pending, rejected, expired and consumed
          all refuse.
        - Only the original requester may replay their own call. An
          approver deciding an action does not thereby gain the right to
          perform it (V2-ADR-012: approval is not authorization).

        Returns None when no ciphertext is stored, which is the honest
        state for approvals created before this column existed.
        """
        request = await self.get_request(context, approval_id)

        if request.status is not ApprovalStatus.APPROVED:
            raise ApprovalStateError(f"Approval {approval_id} is not approved")
        if request.requester_user_id != context.user_id:
            raise ApprovalBindingError(f"Approval {approval_id} belongs to a different requester")

        stored = await self.repository.get_encrypted_input(approval_id, context.tenant_id)
        if stored is None:
            return None
        ciphertext, _key_version = stored
        return ciphertext

    async def sweep_expired_approvals(self) -> int:
        """Expire all stale pending requests in a single bulk UPDATE.

        This is persistence-maintenance only: it does NOT execute tools,
        grant/consume approvals, or modify authorization state.  Returns
        the number of newly-expired rows for observability logging.
        """
        count = await self.repository.expire_stale_approvals()
        if count > 0:
            logger.info("approval_sweep_expired count=%d", count)
        return count
