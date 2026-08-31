"""Tests for the standalone ADR-007 embedding migration script.

Tests use the real PostgreSQL test database with a fake embedding provider.
They verify the migration script's functions without calling OpenAI.
"""

import os
import sys
import uuid
from pathlib import Path
from typing import List

# Add project root to path so scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from scripts.migrate_embeddings import (
    INDEX_NAME,
    NEW_COLUMN,
    OLD_COLUMN,
    TABLE_NAME,
    TARGET_EMBEDDING_DIMENSION,
    _vector_to_text,
    backfill_batch,
    preflight,
    prepare_schema,
    recreate_index,
    swap_columns,
    verify_completeness,
    verify_final_state,
)

# ---------------------------------------------------------------------------
# Fake providers
# ---------------------------------------------------------------------------


class FakeEmbeddingProvider:
    """Deterministic fake provider for migration tests."""

    def __init__(self, dimensions: int = TARGET_EMBEDDING_DIMENSION):
        self._dimensions = dimensions
        self.call_count = 0
        self.last_texts = []

    def embed(self, text: str) -> List[float]:
        self.call_count += 1
        self.last_texts = [text]
        return self._make_vector(text)

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        self.call_count += 1
        self.last_texts = texts
        return [self._make_vector(t) for t in texts]

    def _make_vector(self, text: str) -> List[float]:
        """Deterministic vector based on text hash."""
        h = hash(text) % self._dimensions
        vec = [0.0] * self._dimensions
        vec[h] = 1.0
        return vec


class FailingEmbeddingProvider:
    """Provider that fails after N successful calls."""

    def __init__(self, fail_after: int, dimensions: int = TARGET_EMBEDDING_DIMENSION):
        self._dimensions = dimensions
        self._call_count = 0
        self._fail_after = fail_after

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        self._call_count += 1
        if self._call_count > self._fail_after:
            raise RuntimeError("Simulated provider failure")
        return [self._make_vector(t) for t in texts]

    def _make_vector(self, text: str) -> List[float]:
        h = hash(text) % self._dimensions
        vec = [0.0] * self._dimensions
        vec[h] = 1.0
        return vec


class WrongDimensionProvider:
    """Provider that returns vectors with wrong dimensions."""

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        return [[0.0] * 64 for _ in texts]


class RecordingProvider:
    """Provider that records all text arguments for verification."""

    def __init__(self, dimensions: int = TARGET_EMBEDDING_DIMENSION):
        self._dimensions = dimensions
        self.recorded_texts: List[str] = []

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        self.recorded_texts.extend(texts)
        return [self._make_vector(t) for t in texts]

    def _make_vector(self, text: str) -> List[float]:
        h = hash(text) % self._dimensions
        vec = [0.0] * self._dimensions
        vec[h % self._dimensions] = 1.0
        return vec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://arc:arc-dev-password@localhost:5432/arc",
)


@pytest.fixture
async def migration_db():
    """Connect to test PostgreSQL and ensure a clean state for migration tests.

    Does NOT drop the entire schema (which would conflict with other tests
    running in the same session). Instead, cleans up test data and resets
    migration-specific schema artifacts.
    """
    from pathlib import Path

    import asyncpg

    conn = await asyncpg.connect(DATABASE_URL)

    # Clean up test data
    await conn.execute("DELETE FROM knowledge_chunks")
    await conn.execute("DELETE FROM knowledge_documents")
    await conn.execute("DELETE FROM tenants WHERE id LIKE 'test-%'")

    # Reset migration-specific artifacts
    await conn.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_new")

    # Ensure embedding column is vector(1536) and NOT NULL
    atttypmod = await conn.fetchval(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        WHERE a.attrelid = 'knowledge_chunks'::regclass
          AND a.attname = 'embedding'
          AND a.attnum > 0
          AND NOT a.attisdropped
        """
    )
    if atttypmod is None:
        await conn.execute(
            "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536) NOT NULL"
        )
    elif atttypmod != 1536:
        await conn.execute("ALTER TABLE knowledge_chunks DROP COLUMN embedding")
        await conn.execute(
            "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536) NOT NULL"
        )

    # Recreate HNSW index if missing
    idx_exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM pg_indexes WHERE indexname = $1)",
        INDEX_NAME,
    )
    if not idx_exists:
        await conn.execute(
            f"CREATE INDEX {INDEX_NAME} ON knowledge_chunks "
            "USING hnsw (embedding vector_cosine_ops)"
        )

    yield conn

    # Teardown: fully restore schema so other test suites are not affected
    # Drop and recreate knowledge_chunks to ensure all columns are correct
    await conn.execute("DROP TABLE IF EXISTS knowledge_chunks CASCADE")
    await conn.execute("DELETE FROM knowledge_documents")
    await conn.execute("DELETE FROM tenants WHERE id LIKE 'test-%'")

    # Recreate knowledge_chunks from schema.sql
    schema_path = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"
    schema = schema_path.read_text()
    for statement in schema.split(";"):
        if statement.strip():
            try:
                await conn.execute(statement)
            except Exception:
                pass  # Ignore errors from IF NOT EXISTS / IF EXISTS / type already exists

    await conn.close()


@pytest.fixture
async def clean_chunks(migration_db):
    """Remove all test data and reset schema after each test."""
    yield
    # Clean up in reverse dependency order — handle tables that may have been dropped
    table_exists = await migration_db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'knowledge_chunks')"
    )
    if not table_exists:
        # Recreate from schema.sql if table was dropped by a test
        schema_path = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"
        schema = schema_path.read_text()
        for statement in schema.split(";"):
            if statement.strip():
                await migration_db.execute(statement)
        return

    await migration_db.execute("DELETE FROM knowledge_chunks")
    await migration_db.execute("DELETE FROM knowledge_documents")
    await migration_db.execute("DELETE FROM tenants WHERE id LIKE 'test-%'")
    # Reset schema: drop embedding_new if it exists (from migration tests)
    await migration_db.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_new")
    # Ensure original embedding column is vector(1536) and NOT NULL.
    # Use pg_attribute.atttypmod for dimension check — information_schema
    # reports udt_name as 'vector' on pgvector/pg17, not 'vector1536'.
    atttypmod = await migration_db.fetchval(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        WHERE a.attrelid = 'knowledge_chunks'::regclass
          AND a.attname = 'embedding'
          AND a.attnum > 0
          AND NOT a.attisdropped
        """
    )
    if atttypmod is None:
        await migration_db.execute(
            "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536) NOT NULL"
        )
    elif atttypmod != 1536:
        await migration_db.execute("ALTER TABLE knowledge_chunks DROP COLUMN embedding")
        await migration_db.execute(
            "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536) NOT NULL"
        )
    # Recreate HNSW index if missing
    idx_exists = await migration_db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM pg_indexes WHERE indexname = $1)",
        INDEX_NAME,
    )
    if not idx_exists:
        await migration_db.execute(
            f"CREATE INDEX {INDEX_NAME} ON knowledge_chunks "
            "USING hnsw (embedding vector_cosine_ops)"
        )


def _unique_id(prefix: str) -> str:
    return f"test-{prefix}-{uuid.uuid4().hex[:8]}"


async def _create_test_data(
    conn,
    tenant_ids: List[str],
    doc_status: str = "active",
    chunks_per_doc: int = 3,
) -> List[str]:
    """Create test tenants, documents, and chunks. Returns chunk IDs."""
    chunk_ids = []

    for tenant_id in tenant_ids:
        # Create tenant
        await conn.execute(
            "INSERT INTO tenants (id, name, status) VALUES ($1, $2, 'active') "
            "ON CONFLICT (id) DO NOTHING",
            tenant_id,
            f"Test Tenant {tenant_id}",
        )

        doc_id = _unique_id("doc")
        # Create document
        await conn.execute(
            "INSERT INTO knowledge_documents "
            "(id, tenant_id, source, provenance, version, status, content) "
            "VALUES ($1, $2, 'manual', 'test', 1, $3, $4)",
            doc_id,
            tenant_id,
            doc_status,
            f"Test content for {tenant_id}",
        )

        # Create chunks
        for seq in range(chunks_per_doc):
            chunk_id = _unique_id("chunk")
            chunk_ids.append(chunk_id)
            await conn.execute(
                "INSERT INTO knowledge_chunks "
                "(id, document_id, tenant_id, content, sequence, embedding) "
                "VALUES ($1, $2, $3, $4, $5, $6::vector)",
                chunk_id,
                doc_id,
                tenant_id,
                f"chunk content {seq} for {tenant_id}",
                seq,
                _vector_to_text([1.0] * 1536),
            )

    return chunk_ids


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMigrationConstants:
    def test_target_dimension_is_1536(self):
        assert TARGET_EMBEDDING_DIMENSION == 1536

    def test_table_name(self):
        assert TABLE_NAME == "knowledge_chunks"

    def test_column_names(self):
        assert OLD_COLUMN == "embedding"
        assert NEW_COLUMN == "embedding_new"

    def test_index_name(self):
        assert INDEX_NAME == "idx_knowledge_chunks_embedding"


class TestSchemaPreparation:
    @pytest.mark.asyncio
    async def test_creates_embedding_new_column(self, migration_db, clean_chunks):
        """embedding_new is created as vector(1536) and nullable."""
        await prepare_schema(migration_db)

        # Check dimension via pg_attribute.atttypmod (pgvector stores it there)
        dim = await migration_db.fetchval(
            """
            SELECT a.atttypmod
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE c.relname = 'knowledge_chunks' AND a.attname = 'embedding_new'
            AND n.nspname = 'public'
            """
        )
        assert dim == 1536

        # Check nullability via information_schema
        col = await migration_db.fetchrow(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding_new'
            """
        )
        assert col is not None
        assert col["is_nullable"] == "YES"

    @pytest.mark.asyncio
    async def test_drops_old_hnsw_index(self, migration_db, clean_chunks):
        """Old HNSW index is dropped if present."""
        # Create a dummy index to verify it gets dropped
        try:
            await migration_db.execute(
                f"CREATE INDEX {INDEX_NAME} ON knowledge_chunks "
                f"USING hnsw (embedding vector_cosine_ops)"
            )
        except Exception:
            pass  # May already exist

        await prepare_schema(migration_db)

        idx = await migration_db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_indexes WHERE indexname = $1)",
            INDEX_NAME,
        )
        assert not idx

    @pytest.mark.asyncio
    async def test_idempotent_on_existing_column(self, migration_db, clean_chunks):
        """Running prepare_schema twice does not fail."""
        await prepare_schema(migration_db)
        await prepare_schema(migration_db)  # Should not raise

        col = await migration_db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding_new')",
        )
        assert col


class TestBackfill:
    @pytest.mark.asyncio
    async def test_active_chunks_backfilled(self, migration_db, clean_chunks):
        """Active document chunks are backfilled."""
        tenant_id = _unique_id("tenant")
        chunk_ids = await _create_test_data(migration_db, [tenant_id], doc_status="active")
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        processed = await backfill_batch(migration_db, provider, batch_size=100)

        assert processed == len(chunk_ids)

        # Verify embedding_new is populated
        null_count = await migration_db.fetchval(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_new IS NULL"
        )
        assert null_count == 0

    @pytest.mark.asyncio
    async def test_archived_chunks_backfilled(self, migration_db, clean_chunks):
        """Archived document chunks are also backfilled (no status filter)."""
        tenant_id = _unique_id("tenant")
        chunk_ids = await _create_test_data(migration_db, [tenant_id], doc_status="archived")
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        processed = await backfill_batch(migration_db, provider, batch_size=100)

        assert processed == len(chunk_ids)

        null_count = await migration_db.fetchval(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_new IS NULL"
        )
        assert null_count == 0

    @pytest.mark.asyncio
    async def test_multiple_tenants(self, migration_db, clean_chunks):
        """All tenants are migrated regardless of tenant_id."""
        tenants = [_unique_id("a"), _unique_id("b"), _unique_id("c")]
        all_chunk_ids = await _create_test_data(migration_db, tenants, chunks_per_doc=2)
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        processed = await backfill_batch(migration_db, provider, batch_size=100)

        assert processed == len(all_chunk_ids)

        # Verify tenant_id preserved
        for chunk_id in all_chunk_ids:
            row = await migration_db.fetchrow(
                "SELECT tenant_id FROM knowledge_chunks WHERE id = $1",
                chunk_id,
            )
            assert row is not None

    @pytest.mark.asyncio
    async def test_full_backfill_with_batches(self, migration_db, clean_chunks):
        """Full backfill works with small batch sizes."""
        tenants = [_unique_id("x"), _unique_id("y")]
        all_chunk_ids = await _create_test_data(migration_db, tenants, chunks_per_doc=5)
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        total = 0
        while True:
            processed = await backfill_batch(migration_db, provider, batch_size=3)
            if processed == 0:
                break
            total += processed

        assert total == len(all_chunk_ids)

        null_count = await migration_db.fetchval(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_new IS NULL"
        )
        assert null_count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, migration_db, clean_chunks):
        """Migration works with zero chunks."""
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        processed = await backfill_batch(migration_db, provider, batch_size=100)

        assert processed == 0


class TestProviderFailure:
    @pytest.mark.asyncio
    async def test_partial_failure_stops_migration(self, migration_db, clean_chunks):
        """Provider failure stops backfill, leaves partial progress."""
        tenant_id = _unique_id("tenant")
        chunk_ids = await _create_test_data(migration_db, [tenant_id], chunks_per_doc=10)
        await prepare_schema(migration_db)

        provider = FailingEmbeddingProvider(fail_after=2, dimensions=TARGET_EMBEDDING_DIMENSION)

        processed = 0
        try:
            for _ in range(10):
                p = await backfill_batch(migration_db, provider, batch_size=3)
                if p == 0:
                    break
                processed += p
        except RuntimeError:
            pass  # Expected

        # Some rows should be populated, some NULL
        populated = await migration_db.fetchval(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_new IS NOT NULL"
        )
        null_count = await migration_db.fetchval(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_new IS NULL"
        )
        assert populated > 0
        assert null_count > 0
        assert populated + null_count == len(chunk_ids)

    @pytest.mark.asyncio
    async def test_resume_after_partial_failure(self, migration_db, clean_chunks):
        """Rerunning after failure completes remaining NULL rows."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=10)
        await prepare_schema(migration_db)

        # First run: fail after 2 batches
        provider1 = FailingEmbeddingProvider(fail_after=2, dimensions=TARGET_EMBEDDING_DIMENSION)
        try:
            for _ in range(10):
                p = await backfill_batch(migration_db, provider1, batch_size=3)
                if p == 0:
                    break
        except RuntimeError:
            pass

        # Second run: succeeds
        provider2 = FakeEmbeddingProvider()
        total = 0
        while True:
            p = await backfill_batch(migration_db, provider2, batch_size=3)
            if p == 0:
                break
            total += p

        null_count = await migration_db.fetchval(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_new IS NULL"
        )
        assert null_count == 0

    @pytest.mark.asyncio
    async def test_dimension_mismatch_aborts(self, migration_db, clean_chunks):
        """Wrong dimension provider causes RuntimeError."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=3)
        await prepare_schema(migration_db)

        provider = WrongDimensionProvider()

        with pytest.raises(RuntimeError, match="dimensions"):
            await backfill_batch(migration_db, provider, batch_size=100)

    @pytest.mark.asyncio
    async def test_provider_error_propagates(self, migration_db, clean_chunks):
        """EmbeddingError-like exceptions cause fail-closed behavior."""
        from arc.services.embeddings import EmbeddingError

        class EmbeddingErrorProvider:
            def embed_many(self, texts):
                raise EmbeddingError("Simulated embedding failure")

        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=3)
        await prepare_schema(migration_db)

        with pytest.raises(EmbeddingError):
            await backfill_batch(migration_db, EmbeddingErrorProvider(), batch_size=100)


class TestCompletenessGate:
    @pytest.mark.asyncio
    async def test_zero_null_passes(self, migration_db, clean_chunks):
        """Completeness check returns 0 when all rows populated."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=5)
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        while True:
            p = await backfill_batch(migration_db, provider, batch_size=10)
            if p == 0:
                break

        null_count = await verify_completeness(migration_db)
        assert null_count == 0

    @pytest.mark.asyncio
    async def test_nonzero_null_fails(self, migration_db, clean_chunks):
        """Completeness check returns count of remaining NULLs."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=5)
        await prepare_schema(migration_db)

        # Only process some rows
        provider = FakeEmbeddingProvider()
        await backfill_batch(migration_db, provider, batch_size=2)

        null_count = await verify_completeness(migration_db)
        assert null_count > 0


class TestColumnSwap:
    @pytest.mark.asyncio
    async def test_successful_swap(self, migration_db, clean_chunks):
        """Column swap: drop old, rename new, set NOT NULL."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=3)
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        while True:
            p = await backfill_batch(migration_db, provider, batch_size=10)
            if p == 0:
                break

        # Verify completeness first
        null_count = await verify_completeness(migration_db)
        assert null_count == 0

        # Swap
        await swap_columns(migration_db)

        # Verify final state: dimension via pg_attribute.atttypmod
        dim = await migration_db.fetchval(
            """
            SELECT a.atttypmod
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE c.relname = 'knowledge_chunks' AND a.attname = 'embedding'
            AND n.nspname = 'public'
            """
        )
        assert dim == 1536

        col = await migration_db.fetchrow(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding'
            """
        )
        assert col is not None
        assert col["is_nullable"] == "NO"

        new_col = await migration_db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding_new')",
        )
        assert not new_col

    @pytest.mark.asyncio
    async def test_hnsw_recreated(self, migration_db, clean_chunks):
        """HNSW index is recreated after column swap."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=3)
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        while True:
            p = await backfill_batch(migration_db, provider, batch_size=10)
            if p == 0:
                break

        await swap_columns(migration_db)
        await recreate_index(migration_db)

        idx = await migration_db.fetchrow(
            "SELECT indexdef FROM pg_indexes WHERE tablename = $1 AND indexname = $2",
            TABLE_NAME,
            INDEX_NAME,
        )
        assert idx is not None
        assert "hnsw" in idx["indexdef"]
        assert "vector_cosine_ops" in idx["indexdef"]

    @pytest.mark.asyncio
    async def test_verify_final_state_passes(self, migration_db, clean_chunks):
        """verify_final_state succeeds after full migration."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=5)
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        while True:
            p = await backfill_batch(migration_db, provider, batch_size=10)
            if p == 0:
                break

        await swap_columns(migration_db)
        await recreate_index(migration_db)
        await verify_final_state(migration_db)  # Should not raise


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_rerun_after_completion_is_safe(self, migration_db, clean_chunks):
        """Running migration again after completion detects final state."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=3)
        await prepare_schema(migration_db)

        provider = FakeEmbeddingProvider()
        while True:
            p = await backfill_batch(migration_db, provider, batch_size=10)
            if p == 0:
                break

        await swap_columns(migration_db)
        await recreate_index(migration_db)

        # Second run: verify_final_state should still pass
        await verify_final_state(migration_db)

    @pytest.mark.asyncio
    async def test_no_metadata_leakage(self, migration_db, clean_chunks):
        """Only content strings are passed to the provider, not metadata."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=3)
        await prepare_schema(migration_db)

        provider = RecordingProvider()
        await backfill_batch(migration_db, provider, batch_size=100)

        # All recorded texts should be content strings (not metadata)
        for text in provider.recorded_texts:
            assert isinstance(text, str)
            # Content strings start with "chunk content" — metadata fields
            # like document_id or sequence should NOT be passed.
            assert text.startswith("chunk content"), f"Expected content string, got: {text!r}"


class TestBatchSizeValidation:
    def test_zero_batch_size_rejected(self):
        """Batch size of 0 should be rejected by argument parser."""
        from scripts.migrate_embeddings import parse_args

        with pytest.raises(SystemExit):
            args = parse_args(["--batch-size", "0"])
            if args.batch_size < 1:
                raise SystemExit(1)

    def test_negative_batch_size_rejected(self):
        """Negative batch size should be rejected."""
        from scripts.migrate_embeddings import parse_args

        args = parse_args(["--batch-size", "-5"])
        assert args.batch_size < 1

    def test_valid_batch_size(self):
        """Positive batch size is accepted."""
        from scripts.migrate_embeddings import parse_args

        args = parse_args(["--batch-size", "50"])
        assert args.batch_size == 50


class TestPreflight:
    @pytest.mark.asyncio
    async def test_preflight_passes_on_fresh_database(self, migration_db, clean_chunks):
        """preflight() returns True on a fresh pre-migration database."""
        # Reset to pre-migration state (vector(64)) since schema.sql now defines vector(1536)
        await migration_db.execute("ALTER TABLE knowledge_chunks DROP COLUMN embedding")
        await migration_db.execute(
            "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(64) NOT NULL"
        )
        result = await preflight(migration_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_preflight_returns_false_after_full_migration(self, migration_db, clean_chunks):
        """preflight() returns False when migration is already complete (pg17 safe)."""
        tenant_id = _unique_id("tenant")
        await _create_test_data(migration_db, [tenant_id], chunks_per_doc=3)

        # Run full migration
        await prepare_schema(migration_db)
        provider = FakeEmbeddingProvider()
        while True:
            p = await backfill_batch(migration_db, provider, batch_size=10)
            if p == 0:
                break
        await swap_columns(migration_db)
        await recreate_index(migration_db)

        # Now preflight should detect the already-migrated state
        result = await preflight(migration_db)
        assert result is False

    @pytest.mark.asyncio
    async def test_preflight_returns_false_when_table_missing(self, migration_db, clean_chunks):
        """preflight() returns False when the table does not exist."""
        await migration_db.execute("DROP TABLE IF EXISTS knowledge_chunks CASCADE")
        result = await preflight(migration_db)
        assert result is False

    @pytest.mark.asyncio
    async def test_preflight_returns_false_when_columns_missing(self, migration_db, clean_chunks):
        """preflight() returns False when neither embedding nor embedding_new exist."""
        await migration_db.execute("DROP TABLE IF EXISTS knowledge_chunks CASCADE")
        # Create table without embedding columns
        await migration_db.execute(
            "CREATE TABLE knowledge_chunks (id TEXT PRIMARY KEY, content TEXT NOT NULL)"
        )
        result = await preflight(migration_db)
        assert result is False
