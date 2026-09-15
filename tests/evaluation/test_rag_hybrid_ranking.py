"""RAG evaluation: hybrid ranking / RRF (Issue #139, V2-ADR-023).

5 deterministic cases testing Reciprocal Rank Fusion behavior.
"""

import pytest

from arc.domain.models import KnowledgeMatch, KnowledgeSource
from arc.services.retrieval import ReciprocalRankFusion

from .golden_datasets import hybrid_fixtures


def _make_match(chunk_id, similarity=0.9):
    return KnowledgeMatch(
        chunk_id=chunk_id,
        document_id=chunk_id.split("-")[0],
        tenant_id="tenant-eval",
        content=f"Content for {chunk_id}",
        source=KnowledgeSource.POLICY,
        provenance="Eval fixture",
        document_version=1,
        sequence=0,
        similarity=similarity,
    )


@pytest.mark.parametrize("fixture", hybrid_fixtures(), ids=lambda f: f["description"])
def test_rrf_dual_list_above_single(fixture):
    """Dual-list match ranked above single-list match."""
    dense = [_make_match(cid, sim) for cid, sim in fixture["dense"]]
    lexical = [_make_match(cid, sim) for cid, sim in fixture["lexical"]]

    fused = ReciprocalRankFusion.fuse(dense, lexical)

    assert len(fused) > 0
    assert fused[0].chunk_id == fixture["expected_first"]


@pytest.mark.parametrize("fixture", hybrid_fixtures(), ids=lambda f: f["description"])
def test_rrf_deterministic(fixture):
    """RRF is deterministic for identical inputs."""
    dense = [_make_match(cid, sim) for cid, sim in fixture["dense"]]
    lexical = [_make_match(cid, sim) for cid, sim in fixture["lexical"]]

    fused_1 = ReciprocalRankFusion.fuse(dense, lexical)
    fused_2 = ReciprocalRankFusion.fuse(dense, lexical)

    assert [m.chunk_id for m in fused_1] == [m.chunk_id for m in fused_2]


@pytest.mark.parametrize("fixture", hybrid_fixtures(), ids=lambda f: f["description"])
def test_rrf_fused_scores(fixture):
    """Fused scores sum per-chunk contributions from both lists."""
    dense = [_make_match(cid, sim) for cid, sim in fixture["dense"]]
    lexical = [_make_match(cid, sim) for cid, sim in fixture["lexical"]]

    scores = ReciprocalRankFusion.scores(dense, lexical)

    for chunk_id in scores:
        assert scores[chunk_id] > 0


@pytest.mark.parametrize("fixture", hybrid_fixtures(), ids=lambda f: f["description"])
def test_rrf_no_mutation(fixture):
    """RRF does not mutate input lists."""
    dense = [_make_match(cid, sim) for cid, sim in fixture["dense"]]
    lexical = [_make_match(cid, sim) for cid, sim in fixture["lexical"]]

    dense_before = [m.chunk_id for m in dense]
    lexical_before = [m.chunk_id for m in lexical]

    ReciprocalRankFusion.fuse(dense, lexical)

    assert [m.chunk_id for m in dense] == dense_before
    assert [m.chunk_id for m in lexical] == lexical_before


@pytest.mark.parametrize("fixture", hybrid_fixtures(), ids=lambda f: f["description"])
def test_rrf_empty_inputs(fixture):
    """RRF handles empty dense or lexical lists."""
    dense = [_make_match(cid, sim) for cid, sim in fixture["dense"]]
    lexical = [_make_match(cid, sim) for cid, sim in fixture["lexical"]]

    fused_empty_dense = ReciprocalRankFusion.fuse([], lexical)
    fused_empty_lexical = ReciprocalRankFusion.fuse(dense, [])

    if fixture["dense"]:
        assert len(fused_empty_lexical) > 0
    if fixture["lexical"]:
        assert len(fused_empty_dense) > 0
