"""Issue #180: repository not-found errors must not disclose tenant identifiers.

Negative lookups only — no seeding required. Each test uses a bogus
tenant id and asserts the raised message is generic and contains no
tenant identifier.
"""

import uuid

import pytest

from arc.db.connection import NotFoundError
from arc.domain.models import ConnectorCredential, ConnectorProvider
from arc.repositories.approvals import PostgreSQLApprovalRequestRepository
from arc.repositories.capabilities import PostgreSQLCapabilityRepository
from arc.repositories.connector_credentials import PostgreSQLConnectorCredentialRepository
from arc.repositories.connectors import PostgreSQLConnectorRepository
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.webhook_events import PostgreSQLWebhookEventRepository


def _tenant() -> str:
    return f"disc-{uuid.uuid4().hex[:10]}"


def _assert_generic(exc_info, tenant_id: str, expected: str) -> None:
    assert exc_info.value.args[0] == expected
    assert tenant_id not in str(exc_info.value)


class TestNotFoundMessagesDiscloseNoTenant:
    async def test_missing_connector(self, db):
        tenant_id = _tenant()
        with pytest.raises(NotFoundError) as exc_info:
            await PostgreSQLConnectorRepository(db).get_by_id("nope", tenant_id)
        _assert_generic(exc_info, tenant_id, "Connector not found")

    async def test_missing_skill(self, db):
        tenant_id = _tenant()
        with pytest.raises(NotFoundError) as exc_info:
            await PostgreSQLSkillRepository(db).get_by_id("nope", tenant_id)
        _assert_generic(exc_info, tenant_id, "Skill not found")

    async def test_missing_knowledge_document(self, db):
        tenant_id = _tenant()
        with pytest.raises(NotFoundError) as exc_info:
            await PostgreSQLKnowledgeRepository(db).get_by_id("nope", tenant_id)
        _assert_generic(exc_info, tenant_id, "Knowledge document not found")

    async def test_missing_approval_request(self, db):
        tenant_id = _tenant()
        with pytest.raises(NotFoundError) as exc_info:
            await PostgreSQLApprovalRequestRepository(db).get_by_id("nope", tenant_id)
        _assert_generic(exc_info, tenant_id, "Approval request not found")

    async def test_missing_webhook_event(self, db):
        tenant_id = _tenant()
        with pytest.raises(NotFoundError) as exc_info:
            await PostgreSQLWebhookEventRepository(db).get_by_event_id("nope", tenant_id)
        _assert_generic(exc_info, tenant_id, "Webhook event not found")

    async def test_missing_credential_update(self, db):
        tenant_id = _tenant()
        credential = ConnectorCredential(
            id="nope",
            tenant_id=tenant_id,
            provider=ConnectorProvider.GITHUB,
            encrypted_credential=b"x",
        )
        with pytest.raises(NotFoundError) as exc_info:
            await PostgreSQLConnectorCredentialRepository(db).update(credential)
        _assert_generic(exc_info, tenant_id, "Connector credential not found")

    async def test_missing_credential_delete(self, db):
        tenant_id = _tenant()
        with pytest.raises(NotFoundError) as exc_info:
            await PostgreSQLConnectorCredentialRepository(db).delete(
                tenant_id, ConnectorProvider.GITHUB.value
            )
        _assert_generic(exc_info, tenant_id, "Connector credential not found")

    async def test_missing_tenant_capability(self, db):
        tenant_id = _tenant()
        with pytest.raises(NotFoundError) as exc_info:
            await PostgreSQLCapabilityRepository(db).set_tenant_capability(
                tenant_id, "agent_execution", True
            )
        _assert_generic(exc_info, tenant_id, "Tenant not found")
