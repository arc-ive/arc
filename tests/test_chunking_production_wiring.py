"""Production chunking wiring regression tests (Issue #227).

The chunker is only useful if the instance the APPLICATION builds carries
the configured overlap. These tests exercise the real composition root and
the real ingestion -> retrieval path, not the chunker in isolation:

- the ``RetrievalService`` wired by ``Application`` has a non-zero overlap;
- a ``RetrievalService`` built without an explicit chunker still gets the
  configured policy rather than the bare mechanism default;
- a fact deliberately straddling a chunk boundary survives ingestion and is
  retrievable afterwards.
"""

import uuid

import pytest

from arc.domain.models import KnowledgeSource, TenantContext, UserRole
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository
from arc.services.chunking import DEFAULT_CHUNK_MAX_CHARS, DEFAULT_CHUNK_OVERLAP_CHARS
from arc.services.embeddings import build_embedding_provider, get_embedding_settings
from arc.services.knowledge import KnowledgeService
from arc.services.pii import PiiGuardService
from arc.services.retrieval import RetrievalService

# A fact long enough to be destroyed by a boundary cut, short enough to fit
# inside the configured overlap window.
BOUNDARY_FACT = (
    "Escalate every severity one incident to the on-call engineer within fifteen minutes."
)
_FILLER = "Background policy text that pads the document to length. "


def _document_with_fact_on_boundary() -> str:
    """Place BOUNDARY_FACT so it straddles the first chunk boundary."""
    prefix = (_FILLER * 40)[: DEFAULT_CHUNK_MAX_CHARS - 40]
    return prefix + BOUNDARY_FACT + " " + (_FILLER * 40)


async def _chunks_for(db, document_id: str, tenant_id: str):
    """Persisted chunk contents for a document, in sequence order."""
    async with db._connection_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT content FROM knowledge_chunks "
            "WHERE document_id = $1 AND tenant_id = $2 ORDER BY sequence",
            document_id,
            tenant_id,
        )
    return [row["content"] for row in rows]


class TestCompositionRootWiring:
    """AC 1: overlap is configured at the composition root, not defaulted."""

    def test_application_wires_a_non_zero_overlap(self, client):
        """The chunker the running application actually uses."""
        from arc.app import app as arc_app

        chunker = arc_app.services["retrieval_service"].chunker
        assert chunker.overlap_chars == DEFAULT_CHUNK_OVERLAP_CHARS
        assert chunker.overlap_chars > 0, "production ingestion must not run with zero overlap"
        assert chunker.max_chars == DEFAULT_CHUNK_MAX_CHARS
        assert chunker.overlap_chars < chunker.max_chars

    def test_retrieval_service_without_explicit_chunker_uses_configured_policy(self):
        """The second construction site named in #227 also gets the policy."""
        service = RetrievalService(
            chunk_repo=object(),
            embedding_provider=build_embedding_provider(get_embedding_settings()),
        )
        assert service.chunker.overlap_chars == DEFAULT_CHUNK_OVERLAP_CHARS
        assert service.chunker.overlap_chars > 0


@pytest.fixture
async def ingestion(db):
    """Real ingestion stack with deterministic embeddings (no external API)."""
    chunk_repo = PostgreSQLKnowledgeChunkRepository(db)
    retrieval = RetrievalService(
        chunk_repo=chunk_repo,
        embedding_provider=build_embedding_provider(get_embedding_settings()),
    )
    service = KnowledgeService(
        knowledge_repo=PostgreSQLKnowledgeRepository(db),
        pii_guard=PiiGuardService(),
        indexer=retrieval,
    )
    return service, retrieval, db


@pytest.fixture
async def tenant_context(db):
    tenant_id = f"chunk227-{uuid.uuid4().hex[:8]}"
    tenants = PostgreSQLTenantRepository(db)
    from arc.domain.models import Tenant

    await tenants.create(Tenant(id=tenant_id, name="Chunking 227"))
    yield TenantContext(
        tenant_id=tenant_id,
        tenant_name="Chunking 227",
        user_id="system:test",
        role=UserRole.OWNER,
    )
    await tenants.delete(tenant_id)


class TestBoundaryFactSurvivesIngestion:
    """AC 3: an eval proving boundary-spanning facts remain retrievable."""

    @pytest.mark.asyncio
    async def test_fact_on_a_chunk_boundary_is_retrievable(self, ingestion, tenant_context):
        service, retrieval, db = ingestion
        document = await service.ingest_document(
            tenant_context,
            KnowledgeSource.PROCEDURE,
            "issue-227-eval",
            _document_with_fact_on_boundary(),
        )

        stored = await _chunks_for(db, document.id, tenant_context.tenant_id)
        assert len(stored) > 1, "fixture must span more than one chunk"
        assert any(BOUNDARY_FACT in chunk for chunk in stored), (
            "the boundary-spanning fact was split across chunks with no redundancy"
        )

        matches = await retrieval.search(
            tenant_context, "severity one incident escalation on-call engineer", limit=5
        )
        assert matches, "ingested content must be retrievable"
        assert any(BOUNDARY_FACT in match.content for match in matches), (
            "the boundary-spanning fact was not retrievable after ingestion"
        )

    @pytest.mark.asyncio
    async def test_ingestion_does_not_explode_chunk_count(self, ingestion, tenant_context):
        """Overlap adds redundancy; it must not multiply persisted chunks."""
        service, _retrieval, db = ingestion
        content = _document_with_fact_on_boundary()
        document = await service.ingest_document(
            tenant_context, KnowledgeSource.PROCEDURE, "issue-227-eval", content
        )

        stored = await _chunks_for(db, document.id, tenant_context.tenant_id)
        upper_bound = (len(content) // DEFAULT_CHUNK_MAX_CHARS + 1) * 2
        assert len(stored) <= upper_bound
        for chunk in stored:
            assert len(chunk) <= DEFAULT_CHUNK_MAX_CHARS
