"""Security evaluation: data exfiltration (Issue #139, V2-ADR-023).

5 deterministic cases testing that prompt construction leaks no
sensitive data (tenant IDs, user IDs, vectors, repo details, auth state).
"""

import pytest

from arc.domain.models import (
    ApprovedContextItem,
    KnowledgeSource,
    RetrievalMethod,
    TenantContext,
    UserRole,
)
from arc.services.intelligence import UnifiedIntelligenceService

from .golden_datasets import exfiltration_fixtures


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _item(index=0):
    return ApprovedContextItem(
        document_id=f"doc-exfil-{index}",
        chunk_id=f"doc-exfil-{index}-c0",
        content="Approved content for exfiltration test.",
        source=KnowledgeSource.POLICY,
        provenance="Eval fixture",
        document_version=1,
        sequence=0,
        relevance_score=0.9,
        citation_reference=f"doc-exfil-{index}#c0",
    )


class _ApprovedContext:
    def __init__(self, items, query):
        self.request_id = "req-eval"
        self.tenant_id = "tenant-eval"
        self.principal_id = "user-eval"
        self.query = query
        self.retrieval_method = RetrievalMethod.HYBRID_RRF
        self.items = items
        self.security_metadata = None


@pytest.mark.parametrize("fixture", exfiltration_fixtures(), ids=lambda f: f["description"])
def test_prompt_contains_no_sensitive_data(fixture):
    """Prompt does not contain sensitive data."""
    items = [_item() for _ in range(2)]
    approved = _ApprovedContext(items, "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    for absent in fixture["prompt_absent"]:
        assert absent.lower() not in prompt.lower(), f"Prompt contains sensitive data: {absent}"


@pytest.mark.parametrize("fixture", exfiltration_fixtures(), ids=lambda f: f["description"])
def test_prompt_no_tenant_id(fixture):
    """Prompt contains no tenant_id."""
    items = [_item()]
    approved = _ApprovedContext(items, "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    assert "tenant-eval" not in prompt
    assert "tenant_id" not in prompt.lower()


@pytest.mark.parametrize("fixture", exfiltration_fixtures(), ids=lambda f: f["description"])
def test_prompt_no_user_id(fixture):
    """Prompt contains no user_id or principal_id."""
    items = [_item()]
    approved = _ApprovedContext(items, "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    assert "user-eval" not in prompt
    assert "principal_id" not in prompt.lower()


@pytest.mark.parametrize("fixture", exfiltration_fixtures(), ids=lambda f: f["description"])
def test_prompt_no_vectors_or_scores(fixture):
    """Prompt contains no vectors or scores."""
    items = [_item()]
    approved = _ApprovedContext(items, "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    assert "embedding" not in prompt.lower()
    assert "vector" not in prompt.lower()
    assert "similarity" not in prompt.lower()


@pytest.mark.parametrize("fixture", exfiltration_fixtures(), ids=lambda f: f["description"])
def test_prompt_no_authorization_state(fixture):
    """Prompt contains no authorization state."""
    items = [_item()]
    approved = _ApprovedContext(items, "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    assert "GRANTED" not in prompt
    assert "DENIED" not in prompt
    assert "authorization" not in prompt.lower()
