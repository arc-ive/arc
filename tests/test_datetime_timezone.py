"""Regression tests for Issue #145 — timezone-aware UTC timestamps."""

from datetime import timezone

from arc.domain.models import (
    ConnectorSyncRecord,
    ConnectorSyncStatus,
    ConnectorProvider,
    KnowledgeDocument,
    KnowledgeSource,
    Skill,
    ToolExecutionRecord,
    ToolExecutionStatus,
    ToolRiskLevel,
)


class TestModelDefaultFactoriesProduceTimezoneAwareUTC:
    """Verify representative model default_factory timestamps are timezone-aware UTC."""

    def test_skill_created_at_is_aware_utc(self):
        skill = Skill(
            id="s1", tenant_id="t", name="s", purpose="p", allowed_tools=[]
        )
        assert skill.created_at.tzinfo is not None
        assert skill.created_at.utcoffset() is not None
        assert skill.created_at.utcoffset().total_seconds() == 0

    def test_knowledge_document_timestamps_are_aware_utc(self):
        doc = KnowledgeDocument(
            id="d1",
            tenant_id="t",
            source=KnowledgeSource.POLICY,
            provenance="test",
            content="c",
        )
        assert doc.created_at.tzinfo is not None
        assert doc.created_at.utcoffset().total_seconds() == 0
        assert doc.updated_at.tzinfo is not None
        assert doc.updated_at.utcoffset().total_seconds() == 0

    def test_tool_execution_record_created_at_is_aware_utc(self):
        rec = ToolExecutionRecord(
            id="t1",
            tenant_id="t",
            user_id="u",
            tool_name="t",
            tool_version="1",
            status=ToolExecutionStatus.SUCCESS,
            risk_level=ToolRiskLevel.LOW,
            input_summary="s",
        )
        assert rec.created_at.tzinfo is not None
        assert rec.created_at.utcoffset().total_seconds() == 0

    def test_connector_sync_record_created_at_is_aware_utc(self):
        rec = ConnectorSyncRecord(
            id="c1",
            tenant_id="t",
            connector_id="c",
            provider=ConnectorProvider.GITHUB,
            status=ConnectorSyncStatus.SUCCESS,
        )
        assert rec.created_at.tzinfo is not None
        assert rec.created_at.utcoffset().total_seconds() == 0
