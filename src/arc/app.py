"""Application setup and initialization."""

import os

from arc.db.connection import ArcDatabase
from arc.repositories.connectors import PostgreSQLConnectorRepository
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.services.agent import AgentExecutionService
from arc.services.connectors import ConnectorService
from arc.services.domain import ServiceFactory
from arc.services.llm import build_llm_provider, get_llm_settings
from arc.services.skill_execution import SkillExecutionService
from arc.services.skills import SkillService
from arc.services.tools import ToolExecutionService, build_platform_tool_registry


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

        # Initialize skill service
        self.services["skill_service"] = SkillService(self.repositories["skill"])

        # Initialize the AI Tool execution stack (Skills Engine slice):
        # the platform-owned registry is the only tool whitelist, and every
        # execution attempt is audited to the tenant-scoped record repo.
        self.repositories["tool_execution"] = PostgreSQLToolExecutionRepository(self.db)
        self.services["tool_service"] = ToolExecutionService(
            build_platform_tool_registry(),
            self.repositories["tool_execution"],
        )

        # Initialize the skill execution engine (delegates ALL actions to
        # the tool service above).
        self.services["skill_execution_service"] = SkillExecutionService(
            skill_service=self.services["skill_service"],
            tool_service=self.services["tool_service"],
        )

        # Initialize the bounded Agent orchestration layer (ADR-005). It
        # sits strictly ABOVE SkillExecutionService and holds no tool
        # registry or handlers of its own.
        self.services["agent_service"] = AgentExecutionService(
            skill_service=self.services["skill_service"],
            skill_execution_service=self.services["skill_execution_service"],
            llm_provider=build_llm_provider(get_llm_settings()),
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
