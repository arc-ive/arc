"""Application setup and initialization."""

import logging
import os

from arc.db.connection import ArcDatabase
from arc.repositories.approvals import PostgreSQLApprovalRequestRepository
from arc.repositories.capabilities import PostgreSQLCapabilityRepository
from arc.repositories.connector_credentials import (
    PostgreSQLConnectorCredentialRepository,
)
from arc.repositories.connector_sync import PostgreSQLConnectorSyncRepository
from arc.repositories.connectors import PostgreSQLConnectorRepository
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.observability import PostgreSQLObservabilityRepository
from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.repositories.webhook_events import PostgreSQLWebhookEventRepository
from arc.security.encryption import EncryptionError, EncryptionService
from arc.services.agent import AgentExecutionService
from arc.services.approvals import HumanApprovalService
from arc.services.capabilities import CapabilityService
from arc.services.chunking import KnowledgeChunker
from arc.services.connector_credentials import ConnectorCredentialService
from arc.services.connector_providers import (
    ConnectorCredentialStore,
    build_provider_registry,
    get_connector_settings,
)
from arc.services.connector_sync import ConnectorSyncService
from arc.services.connectors import ConnectorService
from arc.services.domain import ServiceFactory
from arc.services.embeddings import build_embedding_provider, get_embedding_settings
from arc.services.intelligence import UnifiedIntelligenceService
from arc.services.knowledge import KnowledgeService
from arc.services.llm import build_llm_provider, get_llm_settings
from arc.services.observability import ObservabilityService
from arc.services.pii import PiiGuardService
from arc.services.retrieval import RetrievalService
from arc.services.skill_execution import SkillExecutionService
from arc.services.skills import SkillService
from arc.services.tools import ToolExecutionService, build_platform_tool_registry
from arc.services.webhook_config import WebhookEndpointStore
from arc.services.webhook_ingestion import WebhookIngestionService
from arc.services.webhook_pipeline import WebhookPipelineService

logger = logging.getLogger(__name__)


class Application:
    """Main application class for Arc."""

    def __init__(self):
        self.db = None
        self.repositories = {}
        self.services = {}
        self._is_initialized = False

    async def initialize(self) -> None:
        """Initialize the application."""
        if self._is_initialized:
            return

        print("Initializing Arc application...")

        # Get database URL from environment or use default
        database_url = os.getenv(
            "DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc"
        )

        # Initialize database
        self.db = ArcDatabase(database_url)
        await self.db.connect()

        # Provision the full schema from src/arc/db/schema.sql (single
        # source of truth, Issue #207). Idempotent: safe to run on
        # every startup against an already-provisioned database. Must
        # happen before any query that touches application tables.
        await self.db.ensure_schema()

        # Initialize repositories
        self.repositories = {
            "tenant": PostgreSQLTenantRepository(self.db),
            "user": PostgreSQLUserRepository(self.db),
            "membership": PostgreSQLMembershipRepository(self.db),
            "connector": PostgreSQLConnectorRepository(self.db),
            "connector_sync": PostgreSQLConnectorSyncRepository(self.db),
            "knowledge": PostgreSQLKnowledgeRepository(self.db),
            "knowledge_chunk": PostgreSQLKnowledgeChunkRepository(self.db),
            "skill": PostgreSQLSkillRepository(self.db),
            "tool_execution": PostgreSQLToolExecutionRepository(self.db),
            "webhook_events": PostgreSQLWebhookEventRepository(self.db),
            "observability": PostgreSQLObservabilityRepository(self.db),
            "approval_requests": PostgreSQLApprovalRequestRepository(self.db),
            "connector_credentials": PostgreSQLConnectorCredentialRepository(self.db),
            "capability": PostgreSQLCapabilityRepository(self.db),
        }

        # Initialize services
        tenancy_repos = [
            self.repositories["tenant"],
            self.repositories["user"],
            self.repositories["membership"],
        ]
        self.services = ServiceFactory.create_domain_services(tenancy_repos)

        # Initialize connector service
        self.services["connector_service"] = ConnectorService(self.repositories["connector"])

        # Initialize capability service (V2-ADR-004, Issue #144): central
        # capability resolution for platform/tenant enable/disable. This
        # service is wired BEFORE execution services so they can consume it.
        self.services["capability_service"] = CapabilityService(
            self.repositories["capability"],
        )

        # Initialize knowledge service (Company Brain foundation) with the
        # shared PII Guard boundary applied during ingestion. The Secure
        # RAG foundation indexes sanitized content through the same
        # KnowledgeService: the retrieval service is injected as the
        # indexer so ingestion and retrieval always agree on the source of
        # truth (sanitized content only). The embedding provider is
        # selected from environment configuration (EMBEDDING_PROVIDER /
        # EMBEDDING_MODEL); supported providers are ``deterministic``
        # (development/tests) and ``openai`` (production, ADR-007). Unknown
        # providers fail closed at startup.
        retrieval_service = RetrievalService(
            chunk_repo=self.repositories["knowledge_chunk"],
            chunker=KnowledgeChunker(),
            embedding_provider=build_embedding_provider(get_embedding_settings()),
        )
        self.services["retrieval_service"] = retrieval_service
        pii_guard = PiiGuardService()
        self.services["knowledge_service"] = KnowledgeService(
            self.repositories["knowledge"], pii_guard=pii_guard, indexer=retrieval_service
        )

        # Initialize Unified Intelligence service (first slice: reasoning
        # over the Approved Context Contract). The ONLY retrieval path is
        # the retrieval service's approved_search; the LLM provider is
        # selected from environment configuration (LLM_PROVIDER /
        # LLM_MODEL). Only the deterministic local provider is currently
        # supported; unknown providers fail closed at startup. Production
        # LLM provider/model selection (OpenRouter primary per TRD 34) is
        # a deferred decision.
        # Initialize AI Tool execution service (platform-owned catalog)
        # BEFORE Unified Intelligence so the ADR-004 V1 contract can reuse
        # it as the single authorization/execution/audit choke point.
        # Fail-open for PII guard: unlike Knowledge/Skill services which
        # fail closed on PII errors, tool audit must never be lost. A
        # PiiGuardError during sanitization preserves the redacted summary.
        self.services["tool_service"] = ToolExecutionService(
            build_platform_tool_registry(),
            self.repositories["tool_execution"],
            pii_guard=pii_guard,
            capability_service=self.services["capability_service"],
        )

        # Initialize skill service
        self.services["skill_service"] = SkillService(
            self.repositories["skill"], pii_guard=pii_guard
        )

        # Initialize the skill execution engine (delegates ALL actions to
        # the tool service above).
        self.services["skill_execution_service"] = SkillExecutionService(
            skill_service=self.services["skill_service"],
            tool_service=self.services["tool_service"],
            capability_service=self.services["capability_service"],
        )

        # Initialize Human Intervention approval service (V1 foundation,
        # ADR-005). The approval gate is optional: when wired, the
        # ToolExecutionService creates pending approvals for
        # REQUIRE_HUMAN_APPROVAL tools; consumption happens only through
        # an authorized execute_tool call with an approval_id.
        self.services["human_approval_service"] = HumanApprovalService(
            repository=self.repositories["approval_requests"],
        )

        # Wire approval service to tool execution service
        self.services["tool_service"].approval_service = self.services["human_approval_service"]
        # Wire approval service to skill execution service for
        # skill-level resume verification (V2-ADR-011)
        self.services["skill_execution_service"].approval_service = self.services[
            "human_approval_service"
        ]

        # Initialize observability (PRD 17, TRD 17/28/31): aggregation/
        # read layer over AUTHORITATIVE subsystem records plus the HTTP
        # telemetry table this layer owns. Telemetry writes are best
        # effort and never fail a business operation; reads fail closed.
        # BEFORE services that depend on it for LLM usage telemetry
        # (V2-ADR-024, Issue #141).
        observability_service = ObservabilityService(
            repository=self.repositories["observability"],
        )
        self.services["observability_service"] = observability_service

        self.services["intelligence_service"] = UnifiedIntelligenceService(
            retrieval=retrieval_service,
            llm_provider=build_llm_provider(get_llm_settings()),
            tool_service=self.services["tool_service"],
            observability_service=observability_service,
        )

        # Initialize the bounded Agent orchestration layer (ADR-006). It
        # sits strictly ABOVE SkillExecutionService and holds no tool
        # registry or handlers of its own. Observability is injected so
        # trace persistence is owned by the service layer (Issue #143).
        self.services["agent_service"] = AgentExecutionService(
            skill_service=self.services["skill_service"],
            skill_execution_service=self.services["skill_execution_service"],
            llm_provider=build_llm_provider(get_llm_settings()),
            observability_service=self.services["observability_service"],
            capability_service=self.services["capability_service"],
            pii_guard=pii_guard,
        )

        # Initialize connector synchronization (provider integrations):
        # the provider catalog is code-defined (GitHub, Slack, Linear per
        # ADR-002); simulated mode uses the deterministic controlled/fake
        # clients, live mode uses the httpx adapters. Credentials are read
        # lazily from the environment and never logged or returned.
        connector_settings = get_connector_settings()

        # Initialize connector credential management (V2-ADR-015, TRD 20):
        # encrypted-at-rest credential storage with key versioning. The
        # encryption key is loaded from CONNECTOR_ENCRYPTION_KEY; if
        # unconfigured, credential management is skipped and ENV fallback
        # remains the only credential source.
        try:
            encryption_service = EncryptionService()
            credential_service = ConnectorCredentialService(
                credential_repo=self.repositories["connector_credentials"],
                encryption_service=encryption_service,
            )
            self.services["connector_credential_service"] = credential_service
        except EncryptionError:
            logger.info(
                "Connector encryption key not configured; "
                "DB credential management disabled, ENV fallback active"
            )
            credential_service = None

        self.services["connector_sync_service"] = ConnectorSyncService(
            connector_repo=self.repositories["connector"],
            sync_repo=self.repositories["connector_sync"],
            registry=build_provider_registry(connector_settings),
            credential_store=ConnectorCredentialStore(),
            knowledge_service=KnowledgeService(
                self.repositories["knowledge"], indexer=retrieval_service
            ),
            connector_credential_service=credential_service,
            capability_service=self.services["capability_service"],
        )

        # Initialize webhook ingestion (Webhooks foundation, PRD 16 /
        # TRD 16 / ADR-001 webhook security boundary): inbound-only,
        # HMAC-authenticated per environment-configured endpoint. The
        # tenant binding and signing secret come exclusively from the
        # WEBHOOK_INGESTION_ENDPOINTS environment configuration; secrets
        # are never logged, returned, or persisted.
        webhook_endpoint_store = WebhookEndpointStore()
        self.services["webhook_ingestion_service"] = WebhookIngestionService(
            endpoint_store=webhook_endpoint_store,
            repository=self.repositories["webhook_events"],
            pii_guard=pii_guard,
        )

        # Initialize webhook downstream processing pipeline (Issue #102,
        # PRD 16). Routes received webhook events through the existing
        # SkillExecutionService. Shares the same WebhookEndpointStore
        # instance with the ingestion service so configuration is loaded
        # once. PII Guard is shared with KnowledgeService.
        self.services["webhook_pipeline_service"] = WebhookPipelineService(
            webhook_repository=self.repositories["webhook_events"],
            endpoint_store=webhook_endpoint_store,
            tenant_repository=self.repositories["tenant"],
            skill_execution_service=self.services["skill_execution_service"],
            pii_guard=pii_guard,
        )

        # Seed reference data (production-like multi-tenant environment).
        # Idempotent: uses WHERE NOT EXISTS so re-runs after fresh DB,
        # existing data, or partial state are all safe.
        await self._seed_reference_data()

        # Register services in app context
        from arc.api.controllers import app_context

        app_context.register_services(self.services)

        self._is_initialized = True
        print("Application initialized successfully!")

    async def _seed_reference_data(self) -> None:
        """Idempotent reference data provisioning.

        Seeds a production-like multi-tenant reference environment with
        4 tenants, 17 users, 17 memberships, connectors, knowledge
        documents, and skills. Uses ``WHERE NOT EXISTS`` guards so the
        operation is safe on fresh databases, databases with existing
        data, or repeated startups.
        """
        from arc.setup.reference_data import seed_reference_data

        async with self.db._connection_pool.acquire() as conn:
            await seed_reference_data(conn)

    async def shutdown(self) -> None:
        """Shutdown the application."""
        if self.db:
            await self.db.disconnect()
        self._is_initialized = False


# Global application instance
app = Application()
