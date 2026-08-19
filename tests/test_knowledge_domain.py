"""Domain validation tests for Company Brain knowledge models.

These tests are pure unit tests: they never touch a database, Presidio,
or the FastAPI app. They verify that invalid knowledge documents are
rejected at the model boundary.
"""

import pytest

from arc.domain.models import (
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeStatus,
    TenantContext,
    UserRole,
)


def _valid_document(**overrides):
    values = dict(
        id="doc-1",
        tenant_id="tenant-1",
        source=KnowledgeSource.POLICY,
        provenance="Policy handbook 2026 edition",
        content="Approved remote work policy.",
    )
    values.update(overrides)
    return KnowledgeDocument(**values)


class TestKnowledgeDocumentValidation:
    def test_valid_document_is_accepted(self):
        doc = _valid_document()
        assert doc.id == "doc-1"
        assert doc.tenant_id == "tenant-1"
        assert doc.source == KnowledgeSource.POLICY
        assert doc.status == KnowledgeStatus.ACTIVE
        assert doc.version == 1

    def test_empty_id_is_rejected(self):
        with pytest.raises(ValueError):
            _valid_document(id="")

    def test_empty_tenant_id_is_rejected(self):
        with pytest.raises(ValueError):
            _valid_document(tenant_id="")

    def test_non_enum_source_is_rejected(self):
        with pytest.raises(ValueError):
            _valid_document(source="policy")

    def test_unknown_source_value_is_rejected(self):
        with pytest.raises(ValueError):
            KnowledgeSource("unknown_source")

    def test_empty_provenance_is_rejected(self):
        with pytest.raises(ValueError):
            _valid_document(provenance="")

    def test_empty_content_is_rejected(self):
        with pytest.raises(ValueError):
            _valid_document(content="")

    def test_non_enum_status_is_rejected(self):
        with pytest.raises(ValueError):
            _valid_document(status="active")

    def test_zero_version_is_rejected(self):
        with pytest.raises(ValueError):
            _valid_document(version=0)

    def test_negative_version_is_rejected(self):
        with pytest.raises(ValueError):
            _valid_document(version=-1)

    def test_non_integer_version_is_rejected(self):
        with pytest.raises(ValueError):
            _valid_document(version="1")

    def test_archived_status_is_accepted(self):
        doc = _valid_document(status=KnowledgeStatus.ARCHIVED)
        assert doc.status == KnowledgeStatus.ARCHIVED


class TestKnowledgeSourceEnum:
    def test_all_sources_are_valid(self):
        assert {
            KnowledgeSource.POLICY,
            KnowledgeSource.PROCEDURE,
            KnowledgeSource.INCIDENT_REPORT,
            KnowledgeSource.TROUBLESHOOTING,
            KnowledgeSource.INTERNAL_KNOWLEDGE,
            KnowledgeSource.SOLUTION,
        }


class TestTenantContextForKnowledge:
    def test_valid_context_is_accepted(self):
        context = TenantContext(
            tenant_id="tenant-1",
            tenant_name="Acme",
            user_id="user-1",
            role=UserRole.MEMBER,
        )
        assert context.is_valid is True
        assert context.tenant_id == "tenant-1"
