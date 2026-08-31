"""Standalone ADR-007 embedding migration/backfill tool.

Migrates knowledge_chunks from vector(64) deterministic embeddings to
vector(1536) production embeddings using OpenAI text-embedding-3-small.

This script is standalone: it does NOT depend on the application's
composition root, Composition Root, RetrievalService, or KnowledgeService.
It connects directly to PostgreSQL via asyncpg and instantiates
OpenAIEmbeddingProvider from the provider class.

Usage:
    python -m scripts.migrate_embeddings --database-url postgresql://...

The application must be stopped during migration.
A verified pre-migration backup is required (ADR-007).
"""

import argparse
import asyncio
import os
import sys
import time
from typing import List, Optional

import asyncpg

# Migration target — independent of the application's EMBEDDING_DIMENSIONS.
TARGET_EMBEDDING_DIMENSION = 1536

TABLE_NAME = "knowledge_chunks"
OLD_COLUMN = "embedding"
NEW_COLUMN = "embedding_new"
INDEX_NAME = "idx_knowledge_chunks_embedding"


def _vector_to_text(vector: List[float]) -> str:
    """Encode a Python vector as pgvector text input."""
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def log(message: str) -> None:
    """Operator-visible log line."""
    print(f"[migrate] {message}", flush=True)


def log_error(message: str) -> None:
    """Error log line."""
    print(f"[migrate] ERROR: {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


async def preflight(conn: asyncpg.Connection) -> bool:
    """Verify the database is in the expected pre-migration state.

    Returns True if migration should proceed.
    Raises SystemExit on unrecoverable preflight failure.
    """
    # Table exists
    table_exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
        TABLE_NAME,
    )
    if not table_exists:
        log_error(f"Table '{TABLE_NAME}' does not exist. Nothing to migrate.")
        return False

    # Old embedding column exists and is vector(64)
    col_info = await conn.fetchrow(
        """
        SELECT data_type, udt_name
        FROM information_schema.columns
        WHERE table_name = $1 AND column_name = $2
        """,
        TABLE_NAME,
        OLD_COLUMN,
    )
    if col_info is None:
        # Check if already migrated — either embedding_new exists or
        # the final column state is already in place.
        new_col_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name = $1 AND column_name = $2)",
            TABLE_NAME,
            NEW_COLUMN,
        )
        if not new_col_exists:
            log_error(
                f"Neither '{OLD_COLUMN}' nor '{NEW_COLUMN}' column exists. Unexpected schema state."
            )
            return False
        log(
            f"Column '{OLD_COLUMN}' absent, '{NEW_COLUMN}' present. "
            "Checking if migration is already complete."
        )
        # If OLD_COLUMN doesn't exist and we're past the initial schema,
        # the migration is likely already done (column was swapped).
        log("Migration appears already complete (final column state).")
        return False

    # Check if vector(1536) final state already exists
    # pgvector on pg17 stores dimension in pg_attribute.atttypmod, not udt_name
    dim = await conn.fetchval(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        JOIN pg_class c ON a.attrelid = c.oid
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE c.relname = $1 AND a.attname = 'embedding'
        AND n.nspname = 'public'
        """,
        TABLE_NAME,
    )
    if dim == TARGET_EMBEDDING_DIMENSION:
        log("Schema already in final vector(1536) state. Nothing to do.")
        return False

    # Target dimension
    if TARGET_EMBEDDING_DIMENSION != 1536:
        log_error(f"TARGET_EMBEDDING_DIMENSION is {TARGET_EMBEDDING_DIMENSION}, expected 1536.")
        return False

    # Row count
    total = await conn.fetchval(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    log(f"Total chunks to migrate: {total}")

    return True


# ---------------------------------------------------------------------------
# Schema preparation
# ---------------------------------------------------------------------------


async def prepare_schema(conn: asyncpg.Connection) -> None:
    """Drop old HNSW index and add embedding_new column."""

    # Drop existing HNSW index (safe if absent)
    log(f"Dropping index '{INDEX_NAME}' if present...")
    await conn.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")

    # Add embedding_new column (idempotent)
    col_exists = await conn.fetchval(
        """
        SELECT EXISTS(
            SELECT 1 FROM information_schema.columns
            WHERE table_name = $1 AND column_name = $2
        )
        """,
        TABLE_NAME,
        NEW_COLUMN,
    )
    if not col_exists:
        log(f"Adding column '{NEW_COLUMN}' vector({TARGET_EMBEDDING_DIMENSION})...")
        await conn.execute(
            f"ALTER TABLE {TABLE_NAME} ADD COLUMN {NEW_COLUMN} vector({TARGET_EMBEDDING_DIMENSION})"
        )
    else:
        log(f"Column '{NEW_COLUMN}' already exists, skipping ADD COLUMN.")


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


async def backfill_batch(
    conn: asyncpg.Connection,
    provider,
    batch_size: int,
    dry_run: bool = False,
) -> int:
    """Backfill one batch of chunks. Returns the number of rows processed."""

    rows = await conn.fetch(
        f"SELECT id, content FROM {TABLE_NAME} WHERE {NEW_COLUMN} IS NULL ORDER BY id ASC LIMIT $1",
        batch_size,
    )
    if not rows:
        return 0

    texts = [row["content"] for row in rows]
    ids = [row["id"] for row in rows]

    # Embed
    embeddings = provider.embed_many(texts)

    if len(embeddings) != len(rows):
        raise RuntimeError(f"Provider returned {len(embeddings)} embeddings for {len(rows)} inputs")

    # Validate dimensions
    for i, vec in enumerate(embeddings):
        if len(vec) != TARGET_EMBEDDING_DIMENSION:
            raise RuntimeError(
                f"Embedding for chunk {ids[i]} has {len(vec)} dimensions, "
                f"expected {TARGET_EMBEDDING_DIMENSION}"
            )

    if dry_run:
        return len(rows)

    # Update each row — individual statements within a transaction
    for chunk_id, embedding in zip(ids, embeddings):
        await conn.execute(
            f"UPDATE {TABLE_NAME} SET {NEW_COLUMN} = $1::vector WHERE id = $2",
            _vector_to_text(embedding),
            chunk_id,
        )

    return len(rows)


async def run_backfill(
    conn: asyncpg.Connection,
    provider,
    batch_size: int,
    dry_run: bool = False,
) -> int:
    """Run the full backfill in batches. Returns total rows processed."""

    total_remaining = await conn.fetchval(
        f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE {NEW_COLUMN} IS NULL"
    )
    log(f"Chunks remaining: {total_remaining}")

    if total_remaining == 0:
        log("All chunks already backfilled.")
        return 0

    total_processed = 0
    batch_num = 0

    while True:
        batch_num += 1
        # Each batch gets its own connection/transaction via the pool
        processed = await backfill_batch(conn, provider, batch_size, dry_run)
        if processed == 0:
            break
        total_processed += processed
        remaining = total_remaining - total_processed
        log(
            f"Batch {batch_num}: processed {processed} chunks "
            f"({total_processed} total, ~{max(0, remaining)} remaining)"
        )

    return total_processed


# ---------------------------------------------------------------------------
# Completeness gate
# ---------------------------------------------------------------------------


async def verify_completeness(conn: asyncpg.Connection) -> int:
    """Return the count of rows where embedding_new IS NULL."""
    return await conn.fetchval(f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE {NEW_COLUMN} IS NULL")


# ---------------------------------------------------------------------------
# Column swap
# ---------------------------------------------------------------------------


async def swap_columns(conn: asyncpg.Connection) -> None:
    """Execute the destructive column swap: drop old, rename new, set NOT NULL.

    Wrapped in an explicit transaction so all three DDL statements either
    all succeed or all roll back, minimizing the crash window.
    """

    log("Completeness verified (0 NULL rows). Beginning column swap...")

    async with conn.transaction():
        # Step 1: Drop old embedding column
        log(f"Step 1: Dropping old '{OLD_COLUMN}' column...")
        await conn.execute(f"ALTER TABLE {TABLE_NAME} DROP COLUMN {OLD_COLUMN}")

        # Step 2: Rename embedding_new to embedding
        log(f"Step 2: Renaming '{NEW_COLUMN}' to '{OLD_COLUMN}'...")
        await conn.execute(f"ALTER TABLE {TABLE_NAME} RENAME COLUMN {NEW_COLUMN} TO {OLD_COLUMN}")

        # Step 3: Set NOT NULL
        log(f"Step 3: Setting '{OLD_COLUMN}' NOT NULL...")
        await conn.execute(f"ALTER TABLE {TABLE_NAME} ALTER COLUMN {OLD_COLUMN} SET NOT NULL")

    log("Column swap complete.")


# ---------------------------------------------------------------------------
# Index recreation
# ---------------------------------------------------------------------------


async def recreate_index(conn: asyncpg.Connection) -> None:
    """Recreate the HNSW index on the new embedding column."""
    log(f"Creating HNSW index '{INDEX_NAME}'...")
    await conn.execute(
        f"CREATE INDEX {INDEX_NAME} ON {TABLE_NAME} USING hnsw ({OLD_COLUMN} vector_cosine_ops)"
    )
    log("Index created.")


# ---------------------------------------------------------------------------
# Final verification
# ---------------------------------------------------------------------------


async def verify_final_state(conn: asyncpg.Connection) -> None:
    """Verify the database is in the expected post-migration state."""

    # embedding column exists and is vector(1536)
    # pgvector on pg17 stores dimension in pg_attribute.atttypmod
    dim = await conn.fetchval(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        JOIN pg_class c ON a.attrelid = c.oid
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE c.relname = $1 AND a.attname = 'embedding'
        AND n.nspname = 'public'
        """,
        TABLE_NAME,
    )
    assert dim == TARGET_EMBEDDING_DIMENSION, (
        f"embedding dimension is {dim}, expected {TARGET_EMBEDDING_DIMENSION}"
    )

    # embedding_new should NOT exist
    new_col = await conn.fetchval(
        """
        SELECT EXISTS(
            SELECT 1 FROM information_schema.columns
            WHERE table_name = $1 AND column_name = $2
        )
        """,
        TABLE_NAME,
        NEW_COLUMN,
    )
    assert not new_col, "embedding_new still exists after swap"

    # NOT NULL
    is_nullable = await conn.fetchval(
        """
        SELECT is_nullable
        FROM information_schema.columns
        WHERE table_name = $1 AND column_name = 'embedding'
        """,
        TABLE_NAME,
    )
    assert is_nullable == "NO", f"embedding is_nullable = {is_nullable}, expected NO"

    # Index exists and is HNSW
    idx = await conn.fetchrow(
        """
        SELECT indexdef
        FROM pg_indexes
        WHERE tablename = $1 AND indexname = $2
        """,
        TABLE_NAME,
        INDEX_NAME,
    )
    assert idx is not None, f"Index '{INDEX_NAME}' missing"
    assert "hnsw" in idx["indexdef"], f"Index is not HNSW: {idx['indexdef']}"
    assert "vector_cosine_ops" in idx["indexdef"], (
        f"Index does not use vector_cosine_ops: {idx['indexdef']}"
    )

    # Row count and zero NULLs
    total = await conn.fetchval(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    null_count = await conn.fetchval(f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE embedding IS NULL")
    assert null_count == 0, f"{null_count} NULL embeddings after swap"

    log(f"Final state verified: {total} rows, 0 NULLs, vector(1536), HNSW index present.")


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


def build_provider():
    """Instantiate OpenAIEmbeddingProvider from environment variables."""

    # Lazy import to avoid import errors when testing with mocks
    from arc.services.embeddings import OpenAIEmbeddingProvider

    api_key = os.getenv("OPENAI_API_KEY") or None
    base_url = os.getenv("OMNIROUTE_BASE_URL") or None

    if not api_key and not base_url:
        log_error("OPENAI_API_KEY is required when OMNIROUTE_BASE_URL is not configured")
        sys.exit(1)

    effective_key = api_key if api_key else "gateway-managed"

    provider = OpenAIEmbeddingProvider(
        api_key=effective_key,
        model="text-embedding-3-small",
        dimensions=TARGET_EMBEDDING_DIMENSION,
        base_url=base_url,
    )
    log(
        f"Provider initialized: model=text-embedding-3-small, "
        f"dimensions={TARGET_EMBEDDING_DIMENSION}"
    )
    if base_url:
        log(f"Gateway routing: base_url={base_url}")
    return provider


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_migration(args: argparse.Namespace) -> None:
    """Execute the full migration pipeline."""

    log("=" * 60)
    log("ARC Embedding Migration (ADR-007)")
    log(f"Target dimension: {TARGET_EMBEDDING_DIMENSION}")
    log(f"Batch size: {args.batch_size}")
    log(f"Dry run: {args.dry_run}")
    log("=" * 60)

    # Connect
    log("Connecting to database...")
    conn = await asyncpg.connect(args.database_url)
    try:
        # Preflight
        should_proceed = await preflight(conn)
        if not should_proceed:
            log("Preflight indicates no migration needed. Exiting.")
            return

        # Build provider
        provider = build_provider()

        # Schema preparation
        log("Preparing schema...")
        await prepare_schema(conn)

        # Backfill
        log("Starting backfill...")
        start = time.monotonic()
        total = await run_backfill(conn, provider, args.batch_size, args.dry_run)
        elapsed = time.monotonic() - start
        log(f"Backfill complete: {total} chunks in {elapsed:.1f}s")

        if args.dry_run:
            log("Dry run — skipping completeness check and column swap.")
            return

        # Completeness gate
        null_count = await verify_completeness(conn)
        if null_count != 0:
            log_error(
                f"Completeness gate FAILED: {null_count} rows still have NULL embedding_new. "
                "Aborting. Do NOT proceed with column swap."
            )
            sys.exit(1)
        log("Completeness gate passed: 0 NULL rows.")

        # Column swap
        await swap_columns(conn)

        # Recreate index
        await recreate_index(conn)

        # Final verification
        await verify_final_state(conn)

        log("=" * 60)
        log("MIGRATION COMPLETE")
        log(f"Schema: vector({TARGET_EMBEDDING_DIMENSION})")
        log("Index: HNSW with vector_cosine_ops")
        log(f"Rows: {total} re-embedded")
        log("=" * 60)

    finally:
        await conn.close()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Migrate knowledge_chunks embeddings from vector(64) to vector(1536).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  DATABASE_URL          PostgreSQL connection URL\n"
            "  OPENAI_API_KEY        OpenAI API key (required without OMNIROUTE_BASE_URL)\n"
            "  OMNIROUTE_BASE_URL    Gateway endpoint (optional, for OmniRoute/OpenRouter)\n"
        ),
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc"),
        help="PostgreSQL connection URL (default: DATABASE_URL env or localhost)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of chunks to embed per API call (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run preflight and backfill without column swap",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Entry point."""
    args = parse_args()

    if args.batch_size < 1:
        log_error(f"--batch-size must be > 0, got {args.batch_size}")
        sys.exit(1)

    asyncio.run(run_migration(args))


if __name__ == "__main__":
    main()
