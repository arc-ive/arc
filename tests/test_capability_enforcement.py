"""Execution-path integration tests for capability enforcement.

Tests that SkillExecutionService, ToolExecutionService,
AgentExecutionService, and ConnectorSyncService return correct errors
when capabilities are disabled, and proceed normally when enabled.
Uses a fake in-memory repository for pure service-layer gating tests.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from arc.services.capabilities import CapabilityService

from arc.domain.models import TenantContext
from arc.security.authorization import AuthorizationService
from arc.security.models import AuthenticatedPrincipal
from arc.services.agent import AgentExecutionService
from arc.services.connector_sync import ConnectorSyncError, ConnectorSyncService
from arc.services.llm import SkillSelectingLlm
from arc.services.skill_execution import SkillExecutionService
from arc.services.tools import ToolDeniedError, ToolExecutionService, ToolNotFoundError


def _unique(prefix: str) -> str:
    return f"cap-exec-{prefix}-{uuid.uuid4().hex[:8]}"


class FakeCapabilityRepository:
    """In-memory fake for pure service-layer gating tests."""

    def __init__(self):
        self._platform = {}
        self._tenant = {}

    async def get_platform_capability(self, capability_id):
        return self._platform.get(capability_id)

    async def set_platform_capability(self, capability_id, enabled):
        from datetime import datetime, timezone

        from arc.domain.models import PlatformCapability

        pc = PlatformCapability(
            capability_id=capability_id,
            enabled=enabled,
            updated_at=datetime.now(timezone.utc),
        )
        self._platform[capability_id] = pc
        return pc

    async def list_platform_capabilities(self):
        return list(self._platform.values())

    async def get_tenant_capability(self, tenant_id, capability_id):
        return self._tenant.get((tenant_id, capability_id))

    async def set_tenant_capability(self, tenant_id, capability_id, enabled):
        from arc.domain.models import TenantCapability

        tc = TenantCapability(
            tenant_id=tenant_id,
            capability_id=capability_id,
            enabled=enabled,
        )
        self._tenant[(tenant_id, capability_id)] = tc
        return tc

    async def list_tenant_capabilities(self, tenant_id):
        return [tc for (tid, _), tc in self._tenant.items() if tid == tenant_id]


@pytest.fixture
def cap_svc():
    return CapabilityService(FakeCapabilityRepository())


def _mock_context(tenant_id=None):
    ctx = MagicMock(spec=TenantContext)
    ctx.tenant_id = tenant_id or _unique("tenant")
    ctx.is_valid = True
    ctx.user_id = _unique("user")
    return ctx


def _mock_principal():
    p = MagicMock(spec=AuthenticatedPrincipal)
    p.user_id = _unique("user")
    return p


def _mock_authorization():
    auth = MagicMock(spec=AuthorizationService)
    auth.has_permission.return_value = True
    return auth


# ---------------------------------------------------------------------------
# SkillExecutionService enforcement
# ---------------------------------------------------------------------------


class TestSkillExecutionCapability:
    async def test_disabled_blocks_execution(self, cap_svc):
        """Skill execution blocked when skill_execution capability is disabled."""
        await cap_svc.set_platform("skill_execution", False)

        mock_skill_svc = AsyncMock()
        mock_tool_svc = AsyncMock()

        svc = SkillExecutionService(
            skill_service=mock_skill_svc,
            tool_service=mock_tool_svc,
            capability_service=cap_svc,
        )

        ctx = _mock_context()

        result = await svc.execute(
            context=ctx,
            principal=_mock_principal(),
            skill_id="test-skill",
            tool_calls=[{"tool_name": "t", "input": {}}],
            satisfied_conditions=[],
            authorization=_mock_authorization(),
        )
        assert result.error_kind == "capability_disabled"
        mock_skill_svc.get_skill.assert_not_called()

    async def test_enabled_proceeds(self, cap_svc):
        """Skill execution proceeds when skill_execution is enabled."""
        mock_skill_svc = AsyncMock()
        mock_tool_svc = AsyncMock()

        svc = SkillExecutionService(
            skill_service=mock_skill_svc,
            tool_service=mock_tool_svc,
            capability_service=cap_svc,
        )

        ctx = _mock_context()
        await cap_svc.set_platform("skill_execution", True)
        await cap_svc.set_tenant(ctx.tenant_id, "skill_execution", True)

        from arc.db.connection import NotFoundError

        mock_skill_svc.get_skill.side_effect = NotFoundError("not found")

        with pytest.raises(NotFoundError):
            await svc.execute(
                context=ctx,
                principal=_mock_principal(),
                skill_id="test-skill",
                tool_calls=[{"tool_name": "t", "input": {}}],
                satisfied_conditions=[],
                authorization=_mock_authorization(),
            )
        mock_skill_svc.get_skill.assert_called_once()

    async def test_no_capability_service_always_proceeds(self):
        """Without capability_service wired, execution always proceeds."""
        mock_skill_svc = AsyncMock()
        mock_tool_svc = AsyncMock()

        svc = SkillExecutionService(
            skill_service=mock_skill_svc,
            tool_service=mock_tool_svc,
            capability_service=None,
        )

        ctx = _mock_context()

        from arc.db.connection import NotFoundError

        mock_skill_svc.get_skill.side_effect = NotFoundError("not found")

        with pytest.raises(NotFoundError):
            await svc.execute(
                context=ctx,
                principal=_mock_principal(),
                skill_id="test-skill",
                tool_calls=[{"tool_name": "t", "input": {}}],
                satisfied_conditions=[],
                authorization=_mock_authorization(),
            )
        mock_skill_svc.get_skill.assert_called_once()


# ---------------------------------------------------------------------------
# ToolExecutionService enforcement
# ---------------------------------------------------------------------------


class TestToolExecutionCapability:
    async def test_disabled_blocks_execution(self, cap_svc):
        """Tool execution blocked when tool_execution capability is disabled."""
        await cap_svc.set_platform("tool_execution", False)

        mock_registry = MagicMock()
        mock_record_repo = AsyncMock()

        svc = ToolExecutionService(
            registry=mock_registry,
            record_repo=mock_record_repo,
            capability_service=cap_svc,
        )

        ctx = _mock_context()

        with pytest.raises(ToolDeniedError):
            await svc.execute_tool(
                context=ctx,
                principal=_mock_principal(),
                tool_name="test-tool",
                raw_input={},
                authorization=_mock_authorization(),
            )
        mock_registry.get.assert_not_called()

    async def test_enabled_proceeds_to_registry(self, cap_svc):
        """Tool execution proceeds when tool_execution is enabled."""
        mock_registry = MagicMock()
        mock_record_repo = AsyncMock()

        svc = ToolExecutionService(
            registry=mock_registry,
            record_repo=mock_record_repo,
            capability_service=cap_svc,
        )

        ctx = _mock_context()
        await cap_svc.set_platform("tool_execution", True)
        await cap_svc.set_tenant(ctx.tenant_id, "tool_execution", True)

        mock_registry.get.return_value = None

        with pytest.raises(ToolNotFoundError):
            await svc.execute_tool(
                context=ctx,
                principal=_mock_principal(),
                tool_name="unknown-tool",
                raw_input={},
                authorization=_mock_authorization(),
            )
        mock_registry.get.assert_called_once_with("unknown-tool")


# ---------------------------------------------------------------------------
# AgentExecutionService enforcement
# ---------------------------------------------------------------------------


class TestAgentExecutionCapability:
    async def test_disabled_blocks_execution(self, cap_svc):
        """Agent execution blocked when agent_execution capability is disabled."""
        await cap_svc.set_platform("agent_execution", False)

        mock_skill_svc = AsyncMock()
        mock_skill_exec_svc = AsyncMock()
        mock_llm = MagicMock()

        svc = AgentExecutionService(
            skill_service=mock_skill_svc,
            skill_execution_service=mock_skill_exec_svc,
            llm_provider=mock_llm,
            capability_service=cap_svc,
        )

        ctx = _mock_context()

        result = await svc.run(
            context=ctx,
            principal=_mock_principal(),
            goal="do something",
            authorization=_mock_authorization(),
        )
        assert result.status.value == "failed"
        assert result.error_kind == "agent_capability_unavailable"
        mock_skill_svc.list_skills.assert_not_called()

    async def test_enabled_proceeds(self, cap_svc):
        """Agent execution proceeds when agent_execution is enabled."""
        mock_skill_svc = AsyncMock()
        mock_skill_exec_svc = AsyncMock()

        class _FakeSkillSelectingLlm:
            skill_decision_capable = True

            def propose_skill(self, goal, catalog):
                return None

        mock_llm = _FakeSkillSelectingLlm()

        svc = AgentExecutionService(
            skill_service=mock_skill_svc,
            skill_execution_service=mock_skill_exec_svc,
            llm_provider=mock_llm,
            capability_service=cap_svc,
        )

        ctx = _mock_context()
        await cap_svc.set_platform("agent_execution", True)
        await cap_svc.set_tenant(ctx.tenant_id, "agent_execution", True)

        await svc.run(
            context=ctx,
            principal=_mock_principal(),
            goal="do something",
            authorization=_mock_authorization(),
        )
        assert isinstance(mock_llm, SkillSelectingLlm)

    async def test_no_capability_service_always_proceeds(self):
        """Without capability_service wired, agent execution always proceeds."""
        mock_skill_svc = AsyncMock()
        mock_skill_exec_svc = AsyncMock()

        class _FakeSkillSelectingLlm:
            skill_decision_capable = True

            def propose_skill(self, goal, catalog):
                return None

        mock_llm = _FakeSkillSelectingLlm()

        svc = AgentExecutionService(
            skill_service=mock_skill_svc,
            skill_execution_service=mock_skill_exec_svc,
            llm_provider=mock_llm,
            capability_service=None,
        )

        ctx = _mock_context()
        await svc.run(
            context=ctx,
            principal=_mock_principal(),
            goal="do something",
            authorization=_mock_authorization(),
        )
        assert isinstance(mock_llm, SkillSelectingLlm)


# ---------------------------------------------------------------------------
# ConnectorSyncService enforcement
# ---------------------------------------------------------------------------


class TestConnectorSyncCapability:
    async def test_disabled_blocks_sync(self, cap_svc):
        """Connector sync blocked when connector_sync capability is disabled."""
        await cap_svc.set_platform("connector_sync", False)

        mock_connector_repo = AsyncMock()
        mock_sync_repo = AsyncMock()
        mock_registry = MagicMock()
        mock_credential_store = MagicMock()
        mock_knowledge_service = AsyncMock()

        svc = ConnectorSyncService(
            connector_repo=mock_connector_repo,
            sync_repo=mock_sync_repo,
            registry=mock_registry,
            credential_store=mock_credential_store,
            knowledge_service=mock_knowledge_service,
            capability_service=cap_svc,
        )

        ctx = _mock_context()

        with pytest.raises(ConnectorSyncError, match="not enabled"):
            await svc.sync(context=ctx, connector_id="conn-1")
        mock_connector_repo.get_by_id.assert_not_called()

    async def test_enabled_proceeds_to_connector_lookup(self, cap_svc):
        """Connector sync proceeds when connector_sync is enabled."""
        mock_connector_repo = AsyncMock()
        mock_sync_repo = AsyncMock()
        mock_registry = MagicMock()
        mock_credential_store = MagicMock()
        mock_knowledge_service = AsyncMock()

        svc = ConnectorSyncService(
            connector_repo=mock_connector_repo,
            sync_repo=mock_sync_repo,
            registry=mock_registry,
            credential_store=mock_credential_store,
            knowledge_service=mock_knowledge_service,
            capability_service=cap_svc,
        )

        ctx = _mock_context()
        await cap_svc.set_platform("connector_sync", True)
        await cap_svc.set_tenant(ctx.tenant_id, "connector_sync", True)

        from arc.db.connection import NotFoundError

        mock_connector_repo.get_by_id.side_effect = NotFoundError("not found")

        with pytest.raises(NotFoundError):
            await svc.sync(context=ctx, connector_id="conn-1")
        mock_connector_repo.get_by_id.assert_called_once_with("conn-1", ctx.tenant_id)

    async def test_no_capability_service_always_proceeds(self):
        """Without capability_service wired, sync always proceeds."""
        mock_connector_repo = AsyncMock()
        mock_sync_repo = AsyncMock()
        mock_registry = MagicMock()
        mock_credential_store = MagicMock()
        mock_knowledge_service = AsyncMock()

        svc = ConnectorSyncService(
            connector_repo=mock_connector_repo,
            sync_repo=mock_sync_repo,
            registry=mock_registry,
            credential_store=mock_credential_store,
            knowledge_service=mock_knowledge_service,
            capability_service=None,
        )

        ctx = _mock_context()

        from arc.db.connection import NotFoundError

        mock_connector_repo.get_by_id.side_effect = NotFoundError("not found")

        with pytest.raises(NotFoundError):
            await svc.sync(context=ctx, connector_id="conn-1")
        mock_connector_repo.get_by_id.assert_called_once_with("conn-1", ctx.tenant_id)
