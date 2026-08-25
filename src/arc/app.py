"""Application setup and initialization."""

import os

from arc.db.connection import ArcDatabase
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
from arc.services.chunking import KnowledgeChunker
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
from arc.services.retrieval import RetrievalService
from arc.services.skills import SkillService
from arc.services.tools import ToolExecutionService, build_platform_tool_registry
from arc.services.webhook_config import WebhookEndpointStore
from arc.services.webhook_ingestion import WebhookIngestionService


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

        # Initialize knowledge service (Company Brain foundation) with the
        # shared PII Guard boundary applied during ingestion. The Secure
        # RAG foundation indexes sanitized content through the same
        # KnowledgeService: the retrieval service is injected as the
        # indexer so ingestion and retrieval always agree on the source of
        # truth (sanitized content only). The embedding provider is
        # selected from environment configuration (EMBEDDING_PROVIDER /
        # EMBEDDING_MODEL); only the deterministic local provider is
        # currently supported, and unknown providers fail closed at
        # startup. Production provider selection is a deferred decision.
        retrieval_service = RetrievalService(
            chunk_repo=self.repositories["knowledge_chunk"],
            chunker=KnowledgeChunker(),
            embedding_provider=build_embedding_provider(get_embedding_settings()),
        )
        self.services["retrieval_service"] = retrieval_service
        self.services["knowledge_service"] = KnowledgeService(
            self.repositories["knowledge"], indexer=retrieval_service
        )

        # Initialize Unified Intelligence service (first slice: reasoning
        # over the Approved Context Contract). The ONLY retrieval path is
        # the retrieval service's approved_search; the LLM provider is
        # selected from environment configuration (LLM_PROVIDER /
        # LLM_MODEL). Only the deterministic local provider is currently
        # supported; unknown providers fail closed at startup. Production
        # LLM provider/model selection (OpenRouter primary per TRD 34) is
        # a deferred decision.
        self.services["intelligence_service"] = UnifiedIntelligenceService(
            retrieval=retrieval_service,
            llm_provider=build_llm_provider(get_llm_settings()),
        )

        # Initialize skill service
        self.services["skill_service"] = SkillService(self.repositories["skill"])

        # Initialize AI Tool execution service (platform-owned catalog).
        self.services["tool_service"] = ToolExecutionService(
            build_platform_tool_registry(),
            self.repositories["tool_execution"],
        )

        # Initialize observability (PRD 17, TRD 17/28/31): aggregation/
        # read layer over AUTHORITATIVE subsystem records plus the HTTP
        # telemetry table this layer owns. Telemetry writes are best
        # effort and never fail a business operation; reads fail closed.
        self.services["observability_service"] = ObservabilityService(
            repository=self.repositories["observability"],
        )

        # Initialize connector synchronization (provider integrations):
        # the provider catalog is code-defined (GitHub, Slack, Linear per
        # ADR-002); simulated mode uses the deterministic controlled/fake
        # clients, live mode uses the httpx adapters. Credentials are read
        # lazily from the environment and never logged or returned.
        connector_settings = get_connector_settings()
        self.services["connector_sync_service"] = ConnectorSyncService(
            connector_repo=self.repositories["connector"],
            sync_repo=self.repositories["connector_sync"],
            registry=build_provider_registry(connector_settings),
            credential_store=ConnectorCredentialStore(),
            knowledge_service=KnowledgeService(
                self.repositories["knowledge"], indexer=retrieval_service
            ),
        )

        # Initialize webhook ingestion (Webhooks foundation, PRD 16 /
        # TRD 16 / ADR-001 webhook security boundary): inbound-only,
        # HMAC-authenticated per environment-configured endpoint. The
        # tenant binding and signing secret come exclusively from the
        # WEBHOOK_INGESTION_ENDPOINTS environment configuration; secrets
        # are never logged, returned, or persisted.
        self.services["webhook_ingestion_service"] = WebhookIngestionService(
            endpoint_store=WebhookEndpointStore(),
            repository=self.repositories["webhook_events"],
        )

        # Register services in app context
        from arc.api.controllers import app_context

        app_context.register_services(self.services)

        self._is_initialized = True
        print("Application initialized successfully!")

    async def shutdown(self) -> None:
        """Shutdown the application."""
        if self.db:
            await self.db.disconnect()
        self._is_initialized = False


# Global application instance
app = Application()
