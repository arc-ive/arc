"""RAG evaluation: citation correctness, application-level (Issue #139).

5 deterministic cases testing citation reference construction, format
validity, and prompt integrity. Does NOT test model output.
"""

import pytest

from arc.domain.models import (
    ApprovedContextItem,
    ApprovedContextSecurityMetadata,
    KnowledgeSource,
    RetrievalMethod,
    TenantContext,
    UserRole,
)
from arc.services.intelligence import UnifiedIntelligenceService

from .golden_datasets import citation_application_fixtures


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _item(document_id, sequence, citation_reference):
    return ApprovedContextItem(
        document_id=document_id,
        chunk_id=f"{document_id}-c{sequence}",
        content=f"Content for {document_id} chunk {sequence}.",
        source=KnowledgeSource.POLICY,
        provenance="Evaluation fixture",
        document_version=1,
        sequence=sequence,
        relevance_score=0.9,
        citation_reference=citation_reference,
    )


def _approved(items, query="test query"):
    return _ApprovedContext(
        request_id="req-eval",
        tenant_id="tenant-eval",
        principal_id="user-eval",
        query=query,
        retrieval_method=RetrievalMethod.HYBRID_RRF,
        items=items,
        security_metadata=ApprovedContextSecurityMetadata(tenant_id="tenant-eval"),
    )


class _ApprovedContext:
    """Minimal ApprovedContext for prompt construction tests."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.mark.parametrize("fixture", citation_application_fixtures(), ids=lambda f: f["description"])
def test_citation_references_follow_format(fixture):
    """Citation references follow doc_id#seq format."""
    for item_data in fixture["items"]:
        ref = item_data["citation_reference"]
        doc_id = item_data["document_id"]
        seq = item_data["sequence"]
        assert ref == f"{doc_id}#c{seq}"


@pytest.mark.parametrize("fixture", citation_application_fixtures(), ids=lambda f: f["description"])
def test_citation_references_match_source(fixture):
    """Citation references correspond to source document IDs."""
    for item_data in fixture["items"]:
        assert item_data["document_id"] in item_data["citation_reference"]


@pytest.mark.parametrize("fixture", citation_application_fixtures(), ids=lambda f: f["description"])
def test_citation_references_distinct(fixture):
    """Multiple items produce distinct citation references."""
    refs = [item["citation_reference"] for item in fixture["items"]]
    assert len(refs) == len(set(refs))


@pytest.mark.parametrize("fixture", citation_application_fixtures(), ids=lambda f: f["description"])
def test_prompt_contains_only_approved_citations(fixture):
    """Prompt contains only approved citation references, no extraneous refs."""
    items = [
        _item(i["document_id"], i["sequence"], i["citation_reference"]) for i in fixture["items"]
    ]
    approved = _approved(items)
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    for item_data in fixture["items"]:
        assert item_data["citation_reference"] in prompt

    forbidden = fixture.get("prompt_excludes", [])
    for ref in forbidden:
        assert ref not in prompt


@pytest.mark.parametrize("fixture", citation_application_fixtures(), ids=lambda f: f["description"])
def test_citation_indices_are_sequential(fixture):
    """Citation references are indexed sequentially in the prompt."""
    items = [
        _item(i["document_id"], i["sequence"], i["citation_reference"]) for i in fixture["items"]
    ]
    approved = _approved(items)
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    for index, item_data in enumerate(fixture["items"], start=1):
        assert f"[{index}] citation: {item_data['citation_reference']}" in prompt
