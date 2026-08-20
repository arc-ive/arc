"""Application setup and initialization."""

import os

from arc.db.connection import ArcDatabase
from arc.repositories.connectors import PostgreSQLConnectorRepository
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.services.chunking import KnowledgeChunker
from arc.services.connectors import ConnectorService
from arc.services.domain import ServiceFactory
from arc.services.embeddings import DeterministicEmbeddingProvider
from arc.services.knowledge import KnowledgeService
from arc.services.retrieval import RetrievalService
from arc.services.skills import SkillService


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
            "knowledge": PostgreSQLKnowledgeRepository(self.db),
            "knowledge_chunk": PostgreSQLKnowledgeChunkRepository(self.db),
            "skill": PostgreSQLSkillRepository(self.db),
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
        # truth (sanitized content only). The embedding provider is the
        # deterministic local provider; production provider selection is a
        # deferred decision.
        retrieval_service = RetrievalService(
            chunk_repo=self.repositories["knowledge_chunk"],
            chunker=KnowledgeChunker(),
            embedding_provider=DeterministicEmbeddingProvider(),
        )
        self.services["retrieval_service"] = retrieval_service
        self.services["knowledge_service"] = KnowledgeService(
            self.repositories["knowledge"], indexer=retrieval_service
        )

        # Initialize skill service
        self.services["skill_service"] = SkillService(self.repositories["skill"])

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
