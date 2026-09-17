"""RAG evaluation: adversarial content (Issue #139, V2-ADR-023).

5 deterministic cases testing that adversarial content in retrieved
documents is properly contained in the prompt.
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

from .golden_datasets import adversarial_fixtures


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _item(content, index=0):
    return ApprovedContextItem(
        document_id=f"doc-adv-{index}",
        chunk_id=f"doc-adv-{index}-c0",
        content=content,
        source=KnowledgeSource.POLICY,
        provenance="Eval fixture",
        document_version=1,
        sequence=0,
        relevance_score=0.9,
        citation_reference=f"doc-adv-{index}#c0",
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


@pytest.mark.parametrize("fixture", adversarial_fixtures(), ids=lambda f: f["description"])
def test_injection_in_context_labeled_untrusted(fixture):
    """Injection in retrieved content is enclosed in APPROVED CONTEXT block."""
    item = _item(fixture["content"])
    approved = _ApprovedContext([item], "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    assert "APPROVED CONTEXT:" in prompt
    assert fixture["content"] in prompt


@pytest.mark.parametrize("fixture", adversarial_fixtures(), ids=lambda f: f["description"])
def test_prompt_separates_instructions_from_content(fixture):
    """Prompt structurally separates system instructions from retrieved content."""
    item = _item(fixture["content"])
    approved = _ApprovedContext([item], "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    instruction_pos = prompt.find("You are Arc")
    context_pos = prompt.find("APPROVED CONTEXT:")
    assert instruction_pos < context_pos, "Instructions must come before context block"


@pytest.mark.parametrize("fixture", adversarial_fixtures(), ids=lambda f: f["description"])
def test_adversarial_labeled_untrusted(fixture):
    """Adversarial content labeled as untrusted data in prompt."""
    item = _item(fixture["content"])
    approved = _ApprovedContext([item], "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    assert fixture["expected_label"] in prompt


@pytest.mark.parametrize("fixture", adversarial_fixtures(), ids=lambda f: f["description"])
def test_injection_does_not_alter_system_instructions(fixture):
    """Injection attempt does not modify system instructions."""
    item = _item(fixture["content"])
    approved = _ApprovedContext([item], "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    assert "Answer using ONLY the approved context" in prompt
    assert "Cite sources with their citation references" in prompt


@pytest.mark.parametrize("fixture", adversarial_fixtures(), ids=lambda f: f["description"])
def test_prompt_boundary_visible(fixture):
    """Prompt boundary between instructions and content is visible."""
    item = _item(fixture["content"])
    approved = _ApprovedContext([item], "test query")
    prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

    lines = prompt.split("\n")
    context_line_idx = next(i for i, line in enumerate(lines) if "APPROVED CONTEXT:" in line)
    instruction_lines = lines[:context_line_idx]
    content_lines = lines[context_line_idx:]

    assert any("You are Arc" in line for line in instruction_lines)
    content_section = "\n".join(content_lines)
    assert fixture["content"] in content_section
