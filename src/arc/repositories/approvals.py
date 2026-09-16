"""PostgreSQL implementation of the ApprovalRequestRepository contract.

Human Intervention approval gate (V1 foundation). Conventions follow the
other repositories: raw asyncpg over the shared pool, every query
enforcing ``tenant_id`` at the SQL level.

Lifecycle safety is enforced by ATOMIC conditional UPDATEs that only fire
from the exact allowed source state:

- pending -> approved/rejected   (decide; terminal afterwards)
- pending -> expired             (only when past ``expires_at``; lazy)
- approved -> consumed           (single-use; exact tool/version/digest
                                  binding must match and the row must be
                                  unexpired at mutation time)

Because each statement re-derives its own precondition inside one atomic
UPDATE, concurrent calls can never double-transition a row: exactly one
caller observes a changed-row count of 1. Reads return physical state;
lazy-expiry derivation lives in the domain (``effective_status``) and the
service layer. Raw tool arguments are never stored anywhere.
"""

from typing import List, Optional

import asyncpg

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import ApprovalRequest, ApprovalStatus

_COLUMNS = """
    id, tenant_id, requester_user_id, tool_name, tool_version,
    risk_level, input_summary, arguments_digest, status,
    created_at, expires_at, decided_at, decided_by_user_id, consumed_at
"""


class PostgreSQLApprovalRequestRepository:
    """PostgreSQL implementation of the ApprovalRequestRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    @staticmethod
    def _from_row(row) -> ApprovalRequest:
        return ApprovalRequest(
            id=row["id"],
            tenant_id=row["tenant_id"],
            requester_user_id=row["requester_user_id"],
            tool_name=row["tool_name"],
            tool_version=row["tool_version"],
            risk_level=row["risk_level"],
            input_summary=row["input_summary"],
            arguments_digest=row["arguments_digest"].strip(),
            status=ApprovalStatus(row["status"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            decided_at=row["decided_at"],
            decided_by_user_id=row["decided_by_user_id"],
            consumed_at=row["consumed_at"],
        )

    async def create(self, request: ApprovalRequest) -> ApprovalRequest:
        try:
            async with self.db.transaction() as conn:
                await conn.execute(
                    """
                    INSERT INTO approval_requests
                        (id, tenant_id, requester_user_id, tool_name,
                         tool_version, risk_level, input_summary,
                         arguments_digest, status, created_at, expires_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    request.id,
                    request.tenant_id,
                    request.requester_user_id,
                    request.tool_name,
                    request.tool_version,
                    request.risk_level,
                    request.input_summary,
                    request.arguments_digest,
                    request.status.value,
                    request.created_at,
                    request.expires_at,
                )
        except (DuplicateKeyError, asyncpg.UniqueViolationError):
            # Concurrent creation raced: the unique partial index on
            # (tenant, tool, version, digest) WHERE status='pending' fired.
            # Return the existing open row — caller treats this as
            # idempotent (same logical approval already exists).
            existing = await self.find_open(
                request.tenant_id,
                request.tool_name,
                request.tool_version,
                request.arguments_digest,
            )
            if existing is not None:
                return existing
            # Defensive: index says a row exists but find_open missed it
            # (should not happen). Re-raise so the caller sees the error.
            raise
        return request

    async def get_by_id(self, approval_id: str, tenant_id: str) -> ApprovalRequest:
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {_COLUMNS}
                FROM approval_requests
                WHERE id = $1 AND tenant_id = $2
                """,
                approval_id,
                tenant_id,
            )
        if not row:
            raise NotFoundError(f"Approval request {approval_id} not found in tenant {tenant_id}")
        return self._from_row(row)

    async def list_for_tenant(self, tenant_id: str, limit: int = 100) -> List[ApprovalRequest]:
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_COLUMNS}
                FROM approval_requests
                WHERE tenant_id = $1
                ORDER BY created_at DESC, id ASC
                LIMIT $2
                """,
                tenant_id,
                limit,
            )
        return [self._from_row(row) for row in rows]

    async def list_for_tenant_paginated(self, tenant_id: str, limit: int, offset: int) -> tuple:
        """List approval requests with LIMIT/OFFSET and total count."""
        async with self.db._connection_pool.acquire() as conn:
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM approval_requests WHERE tenant_id = $1",
                tenant_id,
            )
            total = count_row["cnt"]
            rows = await conn.fetch(
                f"""
                SELECT {_COLUMNS}
                FROM approval_requests
                WHERE tenant_id = $1
                ORDER BY created_at DESC, id ASC
                LIMIT $2 OFFSET $3
                """,
                tenant_id,
                limit,
                offset,
            )
        items = [self._from_row(row) for row in rows]
        return items, total

    async def find_open(
        self, tenant_id: str, tool_name: str, tool_version: str, arguments_digest: str
    ) -> Optional[ApprovalRequest]:
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {_COLUMNS}
                FROM approval_requests
                WHERE tenant_id = $1 AND tool_name = $2 AND tool_version = $3
                  AND arguments_digest = $4 AND status = 'pending'
                  AND expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT 1
                """,
                tenant_id,
                tool_name,
                tool_version,
                arguments_digest,
            )
        return self._from_row(row) if row else None

    async def expire_if_due(self, approval_id: str, tenant_id: str) -> bool:
        async with self.db.transaction() as conn:
            status = await conn.execute(
                """
                UPDATE approval_requests
                SET status = 'expired', decided_at = CURRENT_TIMESTAMP
                WHERE id = $1 AND tenant_id = $2
                  AND status = 'pending'
                  AND expires_at <= CURRENT_TIMESTAMP
                """,
                approval_id,
                tenant_id,
            )
        return status.endswith("1")

    async def expire_stale_approvals(self) -> int:
        """Atomically expire ALL pending requests past their TTL.

        Single bulk UPDATE — no SELECT+UPDATE N+1.  Safe under concurrency:
        the WHERE clause only matches rows still in ``pending`` state, so
        concurrent lazy-expiry or consumption naturally races without
        double-transition.  Returns the count of newly-expired rows.
        """
        async with self.db.transaction() as conn:
            result = await conn.execute(
                """
                UPDATE approval_requests
                SET status = 'expired', decided_at = CURRENT_TIMESTAMP
                WHERE status = 'pending'
                  AND expires_at <= CURRENT_TIMESTAMP
                """
            )
        # asyncpg execute returns "UPDATE N" — extract the count.
        return int(result.split()[-1])

    async def decide(
        self,
        approval_id: str,
        tenant_id: str,
        decision: ApprovalStatus,
        decider_user_id: str,
    ) -> bool:
        if decision not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            raise ValueError("decide() only transitions to approved or rejected")
        async with self.db.transaction() as conn:
            status = await conn.execute(
                """
                UPDATE approval_requests
                SET status = $3, decided_at = CURRENT_TIMESTAMP,
                    decided_by_user_id = $4
                WHERE id = $1 AND tenant_id = $2 AND status = 'pending'
                  AND expires_at > CURRENT_TIMESTAMP
                """,
                approval_id,
                tenant_id,
                decision.value,
                decider_user_id,
            )
        return status.endswith("1")

    async def consume(
        self,
        approval_id: str,
        tenant_id: str,
        tool_name: str,
        tool_version: str,
        arguments_digest: str,
    ) -> bool:
        async with self.db.transaction() as conn:
            status = await conn.execute(
                """
                UPDATE approval_requests
                SET status = 'consumed', consumed_at = CURRENT_TIMESTAMP
                WHERE id = $1 AND tenant_id = $2
                  AND status = 'approved'
                  AND tool_name = $3 AND tool_version = $4
                  AND arguments_digest = $5
                  AND expires_at > CURRENT_TIMESTAMP
                  AND consumed_at IS NULL
                """,
                approval_id,
                tenant_id,
                tool_name,
                tool_version,
                arguments_digest,
            )
        return status.endswith("1")
