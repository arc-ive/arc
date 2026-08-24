"""Repository interfaces for Arc domain."""

from typing import List, Optional, Protocol

from arc.domain.models import (
    ApiRequestRecord,
    ConnectorConfig,
    ConnectorSyncActivityMetrics,
    ConnectorSyncRecord,
    HttpUsageMetrics,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeMatch,
    Membership,
    Skill,
    Tenant,
    ToolExecutionActivityMetrics,
    ToolExecutionRecord,
    User,
    WebhookEventActivityMetrics,
)


class TenantRepository(Protocol):
    """Repository for Tenant entities."""

    async def create(self, tenant: Tenant) -> Tenant:
        """Create a new tenant."""
        ...

    async def get_by_id(self, tenant_id: str) -> Tenant:
        """Get tenant by ID."""
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

    async def get_by_tenant(self, tenant_id: str) -> List[User]:
        """Get all users for a tenant."""
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

    async def get_tenants_for_user(self, user_id: str) -> List[Tenant]:
        """Get all tenants for a user."""
        ...

    async def get_users_for_tenant(self, tenant_id: str) -> List[User]:
        """Get all users for a tenant."""
        ...

    async def get_memberships_for_user(self, user_id: str) -> List[Membership]:
        """Get all memberships for a user."""
        ...

    async def get_memberships_for_tenant(self, tenant_id: str) -> List[Membership]:
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

    async def list_for_tenant(self, tenant_id: str) -> List[ConnectorConfig]:
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

    async def list_for_tenant(self, tenant_id: str) -> List[ConnectorSyncRecord]:
        """List all connector synchronization records for a tenant."""
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

    async def get_by_id(self, document_id: str, tenant_id: str) -> KnowledgeDocument:
        """Get a knowledge document by ID, scoped to a tenant."""
        ...

    async def list_for_tenant(self, tenant_id: str) -> List[KnowledgeDocument]:
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
        self, tenant_id: str, query_embedding: List[float], limit: int = 5
    ) -> List[KnowledgeMatch]:
        """Return tenant-scoped chunk matches ordered by similarity."""
        ...


class SkillRepository(Protocol):
    """Repository for Skill entities."""

    async def create(self, skill: Skill) -> Skill:
        """Create a new skill."""
        ...

    async def get_by_id(self, skill_id: str, tenant_id: str) -> Skill:
        """Get a skill by ID, scoped to a tenant."""
        ...

    async def list_for_tenant(self, tenant_id: str) -> List[Skill]:
        """List all skills for a tenant."""
        ...

    async def exists(self, skill_id: str, tenant_id: str) -> bool:
        """Check if a skill exists within a tenant."""
        ...

    async def delete(self, skill_id: str, tenant_id: str) -> None:
        """Delete a skill, scoped to a tenant."""
        ...
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
