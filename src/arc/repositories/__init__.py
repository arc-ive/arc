"""Repository interfaces for Arc domain."""

from datetime import datetime
from typing import List, Optional, Protocol

from arc.domain.models import (
    ApiRequestRecord,
    ApprovalRequest,
    ApprovalStatus,
    ConnectorConfig,
    ConnectorCredential,
    ConnectorCredentialAudit,
    ConnectorSyncActivityMetrics,
    ConnectorSyncRecord,
    HttpUsageMetrics,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeMatch,
    KnowledgeSource,
    Membership,
    PlatformCapability,
    Skill,
    SkillExecutionRecord,
    Tenant,
    TenantCapability,
    ToolExecutionActivityMetrics,
    ToolExecutionRecord,
    User,
    WebhookEvent,
    WebhookEventActivityMetrics,
)

# Default safety bound for repository list methods (Issue #183,
# V2-ADR-022). Listing methods accept an explicit ``limit`` and fall
# back to this value so no repository query fetches unbounded rows.
# API-layer pagination (``PaginationParams``) clamps to much smaller
# page sizes before these methods are reached.
DEFAULT_LIST_LIMIT = 1000


class TenantRepository(Protocol):
    """Repository for Tenant entities."""

    async def create(self, tenant: Tenant) -> Tenant:
        """Create a new tenant."""
        ...

    async def get_by_id(self, tenant_id: str) -> Tenant:
        """Get tenant by ID."""
        ...

    async def list_all(self, limit: int = DEFAULT_LIST_LIMIT) -> List[Tenant]:
        """List all tenants (platform-scoped, no membership filter)."""
        ...

    async def update(self, tenant: Tenant) -> Tenant:
        """Update tenant."""
        ...

    async def exists(self, tenant_id: str) -> bool:
        """Check if tenant exists."""
        ...

    async def delete(self, tenant_id: str) -> None:
        """Delete tenant."""
        ...


class UserRepository(Protocol):
    """Repository for User entities."""

    async def create(self, user: User) -> User:
        """Create a new user."""
        ...

    async def get_by_id(self, user_id: str) -> User:
        """Get user by ID."""
        ...

    async def get_by_email(self, email: str) -> User:
        """Get user by email."""
        ...

    async def get_by_tenant(self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT) -> List[User]:
        """Get all users for a tenant."""
        ...

    async def list_all(self, limit: int = DEFAULT_LIST_LIMIT) -> List[User]:
        """List all users."""
        ...

    async def exists(self, user_id: str) -> bool:
        """Check if user exists."""
        ...

    async def delete(self, user_id: str) -> None:
        """Delete user."""
        ...


class MembershipRepository(Protocol):
    """Repository for Membership entities."""

    async def create(self, membership: Membership) -> Membership:
        """Create a new membership."""
        ...

    async def get_by_user_and_tenant(self, user_id: str, tenant_id: str) -> Membership:
        """Get membership by user and tenant IDs."""
        ...

    async def exists(self, user_id: str, tenant_id: str) -> bool:
        """Check if membership exists."""
        ...

    async def delete(self, membership_id: str) -> None:
        """Delete membership."""
        ...

    async def get_tenants_for_user(
        self, user_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[Tenant]:
        """Get all tenants for a user."""
        ...

    async def get_users_for_tenant(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[User]:
        """Get all users for a tenant."""
        ...

    async def get_memberships_for_user(
        self, user_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[Membership]:
        """Get all memberships for a user."""
        ...

    async def get_memberships_for_tenant(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[Membership]:
        """Get all memberships for a tenant."""
        ...


class ConnectorRepository(Protocol):
    """Repository for ConnectorConfig entities."""

    async def create(self, connector: ConnectorConfig) -> ConnectorConfig:
        """Create a new connector configuration."""
        ...

    async def get_by_id(self, connector_id: str, tenant_id: str) -> ConnectorConfig:
        """Get a connector configuration by ID, scoped to a tenant."""
        ...

    async def list_for_tenant(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[ConnectorConfig]:
        """List all connector configurations for a tenant."""
        ...

    async def exists(self, connector_id: str, tenant_id: str) -> bool:
        """Check if a connector configuration exists within a tenant."""
        ...

    async def delete(self, connector_id: str, tenant_id: str) -> None:
        """Delete a connector configuration, scoped to a tenant."""
        ...


class ConnectorSyncRepository(Protocol):
    """Repository for ConnectorSyncRecord audit entities.

    Every operation is tenant scoped: callers pass the trusted tenant ID
    and the repository enforces it in SQL. Records never contain provider
    credentials or raw external payloads.
    """

    async def create_record(self, record: ConnectorSyncRecord) -> ConnectorSyncRecord:
        """Persist a connector synchronization record."""
        ...

    async def list_for_tenant(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[ConnectorSyncRecord]:
        """List all connector synchronization records for a tenant."""
        ...


class ConnectorCredentialRepository(Protocol):
    """Repository for tenant-scoped connector credential storage (V2-ADR-015).

    Every operation is tenant scoped. Credentials are stored encrypted;
    the repository never handles plaintext. One credential per
    (tenant_id, provider) is enforced by a unique constraint.
    """

    async def get_by_tenant_and_provider(
        self, tenant_id: str, provider: str
    ) -> Optional[ConnectorCredential]:
        """Return the encrypted credential for a tenant/provider, or None."""
        ...

    async def create(self, credential: ConnectorCredential) -> ConnectorCredential:
        """Persist a new encrypted credential."""
        ...

    async def update(self, credential: ConnectorCredential) -> ConnectorCredential:
        """Update an existing encrypted credential (rotation)."""
        ...

    async def delete(self, tenant_id: str, provider: str) -> None:
        """Delete the credential for a tenant/provider."""
        ...

    async def create_audit(self, audit: ConnectorCredentialAudit) -> ConnectorCredentialAudit:
        """Persist a credential lifecycle audit record."""
        ...

    async def list_audit_for_tenant(
        self,
        tenant_id: str,
        provider: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> List[ConnectorCredentialAudit]:
        """List audit records for a tenant, optionally filtered by provider."""
        ...


class KnowledgeRepository(Protocol):
    """Repository for KnowledgeDocument entities.

    Every operation is tenant scoped: callers pass the trusted tenant ID
    and the repository enforces it in SQL. A document created by tenant A
    must never be retrievable or listable by tenant B.
    """

    async def create(self, document: KnowledgeDocument) -> KnowledgeDocument:
        """Create a new knowledge document."""
        ...

    async def create_document_with_chunks(
        self,
        document: KnowledgeDocument,
        chunks: List[KnowledgeChunk],
        embeddings: List[List[float]],
    ) -> KnowledgeDocument:
        """Create a knowledge document and all its chunks atomically.

        The document row and every chunk row are inserted in ONE
        transaction: if the document insert or any chunk insert fails,
        the entire operation rolls back. There is never a document
        without its complete retrieval index, nor a partial chunk set.
        """
        ...

    async def get_by_external_id(
        self, external_id: str, source: KnowledgeSource, tenant_id: str
    ) -> KnowledgeDocument:
        """Resolve one logical document by its ADR-003 identity.

        Identity is ``(tenant_id, source, external_id)`` and is resolved
        strictly within the trusted tenant: the same external identifier
        under a different tenant or source never matches. Raises
        ``NotFoundError`` when no such logical document exists.
        """
        ...

    async def find_legacy_duplicate_candidates(self, tenant_id: Optional[str] = None) -> List[dict]:
        """Read-only discovery of pre-ADR-003 duplicate groups.

        Returns one dict per candidate row with ``is_winner`` marking the
        per-group newest row. Never mutates state. ``tenant_id`` optionally
        narrows the sweep; grouping never spans tenants.
        """
        ...

    async def archive_legacy_duplicates(self, tenant_id: Optional[str] = None) -> int:
        """Archive non-winner legacy duplicates; return archived count.

        Archive-only lifecycle operation: re-checks the exact safety
        predicate at mutation time, preserves winners/content/chunks/
        external_id values, and is idempotent. ``tenant_id`` optionally
        narrows the sweep.
        """
        ...

    async def update_document_with_chunks(
        self,
        document: KnowledgeDocument,
        chunks: List[KnowledgeChunk],
        embeddings: List[List[float]],
        expected_version: Optional[int] = None,
    ) -> KnowledgeDocument:
        """Apply an accepted content change to an existing logical document.

        Atomically in ONE transaction: updates content/version/updated_at
        on the existing row (matched by id AND tenant), deletes the old
        chunk set, and inserts the new prepared chunk set. A failure at
        any point rolls back so the prior document version and its complete
        old index remain intact.

        When ``expected_version`` is provided, the row is additionally
        matched on its current version (optimistic locking): if another
        writer committed first, no row matches and ``ConcurrentUpdateError``
        is raised instead of silently overwriting the newer version. With
        ``expected_version=None`` the update is unconditional and a missing
        row raises ``NotFoundError``.
        """
        ...

    async def get_by_id(self, document_id: str, tenant_id: str) -> KnowledgeDocument:
        """Get a knowledge document by ID, scoped to a tenant."""
        ...

    async def delete_by_id(self, document_id: str, tenant_id: str) -> None:
        """Delete a knowledge document by ID, scoped to a tenant."""
        ...

    async def list_for_tenant(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[KnowledgeDocument]:
        """List all knowledge documents for a tenant."""
        ...


class KnowledgeChunkRepository(Protocol):
    """Repository for KnowledgeChunk entities and vector retrieval.

    Every operation is tenant scoped: callers pass the trusted tenant ID
    and the repository enforces it in SQL. Chunks created for tenant A
    must never be retrievable or searchable by tenant B.

    Embedding vectors are passed alongside chunks as opaque
    ``List[float]`` values; the repository is agnostic to the embedding
    provider (Secure RAG foundation).
    """

    async def create_many(
        self, chunks: List[KnowledgeChunk], embeddings: List[List[float]]
    ) -> List[KnowledgeChunk]:
        """Persist chunks atomically with their embedding vectors."""
        ...

    async def search(
        self,
        tenant_id: str,
        query_embedding: List[float],
        limit: int = 5,
        source_type: Optional[KnowledgeSource] = None,
    ) -> List[KnowledgeMatch]:
        """Return tenant-scoped chunk matches ordered by cosine similarity."""
        ...

    async def lexical_search(
        self,
        tenant_id: str,
        query_text: str,
        limit: int = 5,
        source_type: Optional[KnowledgeSource] = None,
    ) -> List[KnowledgeMatch]:
        """Return tenant-scoped chunk matches ordered by lexical relevance."""
        ...


class SkillRepository(Protocol):
    """Repository for Skill entities."""

    async def create(self, skill: Skill) -> Skill:
        """Create a new skill."""
        ...

    async def get_by_id(self, skill_id: str, tenant_id: str) -> Skill:
        """Get a skill by ID, scoped to a tenant."""
        ...

    async def list_for_tenant(self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT) -> List[Skill]:
        """List all skills for a tenant."""
        ...

    async def exists(self, skill_id: str, tenant_id: str) -> bool:
        """Check if a skill exists within a tenant."""
        ...

    async def update(self, skill: Skill) -> Skill:
        """Update an existing skill, scoped to a tenant."""
        ...

    async def delete(self, skill_id: str, tenant_id: str) -> None:
        """Delete a skill, scoped to a tenant."""
        ...


class ToolExecutionRepository(Protocol):
    """Repository for ToolExecutionRecord entities.

    Every operation is tenant scoped: callers pass the trusted tenant ID
    and the repository enforces it in SQL. A record created for tenant A
    must never be retrievable or listable by tenant B.
    """

    async def create_record(self, record: ToolExecutionRecord) -> ToolExecutionRecord:
        """Persist a tool execution record."""
        ...

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> List[ToolExecutionRecord]:
        """List the most recent tool execution records for a tenant."""
        ...

    async def find_successful_by_idempotency_key(
        self, idempotency_key: str, tenant_id: str
    ) -> Optional[ToolExecutionRecord]:
        """Find a prior successful execution by idempotency key.

        Returns the existing successful record if one exists for the
        given key and tenant, or None. Used by the webhook retry
        pipeline to prevent duplicate side effects (V2-ADR-019).
        """
        ...


class SkillExecutionRecordRepository(Protocol):
    """Repository for SkillExecutionRecord entities (Issue #208).

    Every operation is tenant scoped: callers pass the trusted tenant ID
    and the repository enforces it in SQL. A record created for tenant A
    must never be retrievable or listable by tenant B.

    Records are append-oriented audit artifacts: each
    ``SkillExecutionService.execute()`` call produces exactly one row,
    created before execution and updated with the terminal state.
    """

    async def create_record(self, record: SkillExecutionRecord) -> SkillExecutionRecord:
        """Persist a skill execution record (initial state, typically started)."""
        ...

    async def update_record(self, record: SkillExecutionRecord) -> SkillExecutionRecord:
        """Update a skill execution record with terminal state."""
        ...

    async def get_record(self, record_id: str, tenant_id: str) -> Optional[SkillExecutionRecord]:
        """Read one skill execution record within the trusted tenant."""
        ...

    async def list_for_tenant(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[SkillExecutionRecord]:
        """List the most recent skill execution records for a tenant."""
        ...

    async def list_for_skill(
        self, tenant_id: str, skill_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[SkillExecutionRecord]:
        """List the most recent skill execution records for a specific skill."""
        ...

    async def list_for_agent_run(
        self, agent_run_id: str, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[SkillExecutionRecord]:
        """List skill execution records linked to a specific agent run."""
        ...


class WebhookEventRepository(Protocol):
    """Repository for WebhookEvent entities (Webhooks foundation).

    Every operation is tenant scoped: callers pass the trusted tenant ID
    and the repository enforces it in SQL. An event ingested for tenant A
    must never be retrievable or listable by tenant B. Records never
    contain raw external payloads.
    """

    async def create(self, event: WebhookEvent) -> WebhookEvent:
        """Persist a webhook event.

        Raises ``DuplicateKeyError`` when the same ``(tenant_id,
        event_id)`` pair already exists (duplicate handling, PRD 16).
        """
        ...

    async def get_by_event_id(self, event_id: str, tenant_id: str) -> WebhookEvent:
        """Get an event by its sender-supplied identifier, scoped to a tenant.

        Raises ``NotFoundError`` when no such event exists for the tenant.
        """
        ...

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> List[WebhookEvent]:
        """List the most recent webhook events for a tenant."""

    async def claim_for_processing(self, event_id: str, tenant_id: str) -> WebhookEvent:
        """Atomically transition an event from 'received' to 'processing'.

        Returns the updated event. Raises ``NotFoundError`` if the event
        does not exist, is not in 'received' status, or belongs to a
        different tenant. At most one caller can successfully claim a
        given event.
        """
        ...

    async def mark_processed(self, event_id: str, tenant_id: str) -> None:
        """Mark a 'processing' event as 'processed' with a timestamp.

        The event must already be in 'processing' status for this tenant.
        """
        ...

    async def mark_failed(self, event_id: str, tenant_id: str, error_kind: str) -> None:
        """Mark a 'processing' event as 'failed' with an error category.

        The event must already be in 'processing' status for this tenant.
        The ``error_kind`` is a safe hardcoded string constant, never
        user-provided text.
        """
        ...

    async def mark_retrying(
        self, event_id: str, tenant_id: str, retry_count: int, next_retry_at: datetime
    ) -> None:
        """Mark a 'processing' event as 'retrying' with a schedule.

        The event must already be in 'processing' status for this tenant.
        ``retry_count`` is the attempt number (1-based); ``next_retry_at``
        is the earliest time the event should be retried.
        """
        ...

    async def claim_for_retry(self, tenant_id: str, limit: int = 10) -> List[WebhookEvent]:
        """Atomically claim events in 'retrying' status whose next_retry_at has passed.

        Returns the claimed events (transitioned to 'processing').
        At most ``limit`` events are claimed per call. Each claim is
        atomic: at most one processor wins a given event.
        """
        ...

    async def list_due_retrying(self, tenant_id: str, limit: int = 10) -> List[WebhookEvent]:
        """List due retryable events WITHOUT claiming them (Issue #178).

        Returns events in 'retrying' status whose next_retry_at has
        passed, without modifying state. Callers process each event
        through the pipeline, which performs the atomic claim itself,
        so concurrent workers cannot double-process: at most one
        claimant wins and the rest observe NotFoundError.
        """
        ...

    async def claim_single_for_retry(self, event_id: str, tenant_id: str) -> Optional[WebhookEvent]:
        """Atomically claim a single retrying event by event_id.

        Transitions the event from 'retrying' to 'processing' if its
        next_retry_at has passed. Returns the claimed event, or None if
        the event does not exist, is not in 'retrying' status, or its
        next_retry_at is in the future. At most one caller wins.
        """
        ...

    async def mark_dead_letter(self, event_id: str, tenant_id: str, error_kind: str) -> None:
        """Transition a 'retrying' or 'processing' event to 'dead_letter'.

        Used when all retry attempts are exhausted or the failure is
        permanent. The ``error_kind`` is a safe hardcoded string constant.
        """
        ...

    async def sweep_stuck_processing(
        self, tenant_id: str, stuck_threshold_seconds: int = 600
    ) -> List[WebhookEvent]:
        """Find events stuck in 'processing' longer than the threshold.

        Returns the stuck events (still in processing status) for
        operator visibility. Does NOT modify state; the caller decides
        whether to transition to dead_letter or retry.
        """
        ...


class ObservabilityRepository(Protocol):
    """Repository for Observability aggregates (PRD 17, TRD 17/28/31).

    One write path only: HTTP telemetry records this layer owns. All
    other methods are READ-SIDE aggregations issued against the
    authoritative subsystem tables (tool executions, connector syncs,
    webhook events) which are never duplicated.

    Scope contract: ``tenant_id=None`` selects the PLATFORM view —
    strictly tenant-agnostic operational totals; no method returns
    per-tenant breakdowns or raw rows. Every tenant-scoped query
    enforces ``tenant_id`` at the SQL level.
    """

    async def create_api_request_record(self, record: ApiRequestRecord) -> ApiRequestRecord:
        """Persist one HTTP telemetry record (metadata-only)."""
        ...

    async def api_request_summary(self, tenant_id: Optional[str], hours: int) -> HttpUsageMetrics:
        """Aggregate HTTP usage for a tenant, or platform-wide when None."""
        ...

    async def tool_execution_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> ToolExecutionActivityMetrics:
        """Aggregate authoritative AI Tool execution records in place."""
        ...

    async def connector_sync_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> ConnectorSyncActivityMetrics:
        """Aggregate authoritative connector sync records in place."""
        ...

    async def webhook_event_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> WebhookEventActivityMetrics:
        """Aggregate webhook events when the source table exists.

        While the Webhooks foundation (PR #34) is unmerged the source is
        legitimately absent on main: implementations must report it as
        unavailable (never fabricate or duplicate it).
        """
        ...

    async def database_reachable(self) -> bool:
        """Component health probe for the database."""
        ...

    async def create_llm_usage_record(self, record) -> None:
        """Persist one LLM usage telemetry record (metadata-only)."""
        ...

    async def llm_usage_activity(self, tenant_id: Optional[str], hours: int):
        """Aggregate LLM usage for a tenant, or platform-wide when None."""
        ...

    async def llm_usage_records_page(
        self, tenant_id: str, hours: int, call_type: Optional[str], limit: int, offset: int
    ) -> tuple:
        """Return (records, total_count) for paginated LLM usage records."""
        ...


class ApprovalRequestRepository(Protocol):
    """Repository for Human Intervention approval requests (V1 gate).

    Every operation is tenant scoped: callers pass the trusted tenant ID
    and the repository enforces it in SQL. An approval request created for
    tenant A must never be retrievable or listable by tenant B.

    An approval is consumed at most once. Expiry is lazy: ``pending`` rows
    past their ``expires_at`` read as EXPIRED without mutation.
    """

    async def create(self, request: ApprovalRequest) -> ApprovalRequest:
        """Persist one approval request exactly as provided.

        Raises ``DuplicateKeyError`` when an identical logical binding
        ``(tenant_id, tool_name, tool_version, arguments_digest)`` already
        has a ``pending`` request (unique partial index, race-safe).
        """
        ...

    async def get_by_id(self, approval_id: str, tenant_id: str) -> ApprovalRequest:
        """Get an approval request by ID, scoped to a tenant.

        Raises ``NotFoundError`` when no such request exists for the tenant.
        """
        ...

    async def list_for_tenant(self, tenant_id: str, limit: int = 100) -> List[ApprovalRequest]:
        """List approval requests for a tenant, most recent first."""
        ...

    async def find_open_by_binding(
        self, tenant_id: str, tool_name: str, tool_version: str, arguments_digest: str
    ) -> Optional[ApprovalRequest]:
        """Find the existing OPEN (pending) request for a logical binding.

        Returns ``None`` when no pending request matches. Expired rows are
        NOT returned here; they are lazily expired at decision/consumption
        time.
        """
        ...

    async def expire_if_due(self, approval_id: str, tenant_id: str) -> bool:
        """Mark a pending request as EXPIRED if it is past its TTL.

        Returns ``True`` when the row was transitioned, ``False`` when the
        row was already decided or not found.
        """
        ...

    async def decide_request(
        self, approval_id: str, tenant_id: str, decision: ApprovalStatus, decided_by_user_id: str
    ) -> ApprovalRequest:
        """Apply an APPROVED or REJECTED decision to a pending request.

        Transitions ``pending`` to the requested decision. Returns the
        updated request. Raises ``ApprovalError`` if the request is not in
        ``pending`` status (fail-closed, no partial transitions).
        """
        ...

    async def consume_if_approved(
        self, approval_id: str, tenant_id: str
    ) -> Optional[ApprovalRequest]:
        """Atomically consume exactly one approved request.

        Transitions ``approved`` to ``consumed`` and returns the updated
        request. Returns ``None`` when the request is not in ``approved``
        status (already consumed, expired, or rejected -- fail-closed).
        """
        ...


class CapabilityRepository(Protocol):
    """Repository for platform and tenant capability state (V2-ADR-004).

    Platform operations are global (not tenant-scoped). Tenant
    operations are tenant-scoped. Every query is grounded in the
    database; capability state is never cached or guessed.
    """

    async def get_platform_capability(self, capability_id: str) -> Optional[PlatformCapability]:
        """Return the platform state for a capability, or None if not seeded."""
        ...

    async def list_platform_capabilities(
        self, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[PlatformCapability]:
        """Return all platform capability states."""
        ...

    async def set_platform_capability(
        self, capability_id: str, enabled: bool
    ) -> PlatformCapability:
        """Upsert the platform state for a capability. Returns the updated record."""
        ...

    async def get_tenant_capability(
        self, tenant_id: str, capability_id: str
    ) -> Optional[TenantCapability]:
        """Return the tenant config for a capability, or None if not configured."""
        ...

    async def list_tenant_capabilities(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[TenantCapability]:
        """Return all capability configs for a tenant."""
        ...

    async def set_tenant_capability(
        self, tenant_id: str, capability_id: str, enabled: bool
    ) -> TenantCapability:
        """Upsert the tenant config for a capability. Returns the updated record.

        Raises ``NotFoundError`` when the tenant does not exist.
        """
        ...


class RepositoryFactory:
    """Factory for creating repository instances."""

    @staticmethod
    def create_tenancy_repositories(db_instance):
        """Create the tenancy repository instances for a database.

        Returns a list ordered as (tenant, user, membership) for direct use
        with ServiceFactory.create_domain_services.
        """
        from arc.repositories.tenancy import (
            PostgreSQLMembershipRepository,
            PostgreSQLTenantRepository,
            PostgreSQLUserRepository,
        )

        return [
            PostgreSQLTenantRepository(db_instance),
            PostgreSQLUserRepository(db_instance),
            PostgreSQLMembershipRepository(db_instance),
        ]
