# ADR-007: Production Embedding Provider and Vector Representation

## Status

Proposed

## Date

2026-08-28

## Decision Owners

- Bala — Engineering and AI architecture review
- Bharath — Platform, Docker, CI, and delivery review
- Joe — Product scope and requirements

## Context

Arc's Company Brain and Secure RAG foundation are implemented and merged
(PRs #26, #29). The retrieval pipeline ingests knowledge documents,
chunks them, embeds the chunks, and stores vectors in PostgreSQL with
pgvector. Queries are embedded and matched against stored vectors using
cosine similarity.

The current embedding provider is `DeterministicEmbeddingProvider`
(`src/arc/services/embeddings.py:136-171`): a local, deterministic
word-hash histogram that produces 64-dimensional L2-normalized vectors.
This provider is explicitly documented as a development/test placeholder,
not a production semantic model.

The retrieval infrastructure is production-ready:
- `EmbeddingProvider` Protocol with `embed()` and `embed_many()` methods
- `RetrievalService` with `prepare_index()`, `persist_index()`, `search()`, and `approved_search()`
- `PostgreSQLKnowledgeChunkRepository` with tenant-scoped cosine similarity search
- HNSW index on `knowledge_chunks.embedding vector(64)`
- Atomic document+chunk+embedding persistence
- PII guard enforced before embedding (sanitized content only)
- Tenant isolation at SQL level with runtime cross-tenant defense

The remaining gap is replacing the deterministic placeholder with a
production semantic embedding model.

## Problem

The deterministic word-hash embedding provider produces vectors that are
not semantically meaningful. The Secure RAG pipeline retrieves results
based on word overlap, not semantic similarity. This defeats the purpose
of the Company Brain: a query for "employee termination procedure" would
not match a document titled "workforce reduction guidelines" even though
they are semantically related.

Production embeddings are required for the retrieval pipeline to produce
meaningful results. However, the current dimension (64) is coupled to the
placeholder provider and hard-coded in the database schema, the Python
application, configuration validation, runtime checks, and tests. A
dimension change requires coordinated updates across all layers.

## Decision

Arc will adopt **OpenAI `text-embedding-3-small` at 1536 dimensions** as
the production embedding provider, with a **single authoritative
embedding-dimension configuration** that flows from the database schema
through the application layer.

### 1. Provider/model selection

**OpenAI `text-embedding-3-small`** is selected as the V1 production
embedding provider, routed through the project's AI gateway.

ADR-001 establishes the Arc AI path as
`Arc → OmniRoute → OpenRouter → configurable LLM`. Embeddings follow
the same routing principle: the `OpenAIEmbeddingProvider` sends requests
through the project's OpenAI-compatible endpoint (which may be
OmniRoute, OpenRouter, or a direct OpenAI key depending on deployment).
The provider class accepts a configurable `base_url`, making the gateway
choice a deployment decision, not an architecture change.

Rationale:
- High semantic quality (MTEB benchmark leader for cost-performance)
- 1536 dimensions (default; also supports 512 via `dimensions` parameter)
- Mature Python SDK (`openai>=1.0`)
- Well-documented API with batch embedding support
- Reasonable cost (~$0.02/1M tokens)
- Widely adopted; proven in production RAG systems
- Compatible with OmniRoute/OpenRouter gateway pattern

Provider-specific facts requiring verification before deployment:
- Exact API key provisioning and rotation process
- Data retention and processing policies for the selected tier
- Rate limits for the expected ingestion/query volume
- Whether OpenAI's data usage policy requires opt-out for enterprise

### 2. Dimension: 1536

1536 is the default dimension for `text-embedding-3-small`. This is a
V1 engineering decision, not a claim of optimal retrieval quality.

**No benchmark evidence exists in the repository** to justify 1536 over
smaller supported dimensions (e.g., 512 via `dimensions` parameter). The
choice is based on:
- 1536 is the model's native dimension (no truncation/reduction)
- Avoids quality loss from dimension reduction
- Matches the most common production deployment pattern
- The model supports configurable dimensions for future optimization

Storage impact: 1536 × 4 bytes = 6.1 KB per vector (vs. 256 bytes at
64-dim). For 10K documents × 5 chunks = 50K vectors × 6.1 KB = ~300 MB
embedding storage. Acceptable for V1 scale (~3 tenants, synthetic data).

If storage or latency becomes a concern, the model supports
`dimensions=512` via the API parameter without changing the model. This
is a future optimization, not a V1 requirement.

### 3. Source-of-truth design

The current architecture has dimension hard-coded in **8 distinct
locations** across 3 layers (verified against repository):

**Application layer** (Python):
| # | File | Line | What | Coupling Type |
|---|------|------|------|---------------|
| 1 | `embeddings.py` | 28 | `EMBEDDING_DIMENSIONS = 64` | Python constant (source of truth for app) |
| 2 | `embeddings.py` | 89 | `if self.dimensions != EMBEDDING_DIMENSIONS` | Configuration validation |
| 3 | `retrieval.py` | 103 | `if len(embedding) != EMBEDDING_DIMENSIONS` | Runtime validation (ingestion) |
| 4 | `retrieval.py` | 134 | `if len(query_embedding) != EMBEDDING_DIMENSIONS` | Runtime validation (query) |

**Database layer** (SQL):
| # | File | Line | What | Coupling Type |
|---|------|------|------|---------------|
| 5 | `schema.sql` | 135 | `embedding vector(64) NOT NULL` | Schema definition |

**Configuration layer**:
| # | File | Line | What | Coupling Type |
|---|------|------|------|---------------|
| 6 | `.env.example` | 80 | `EMBEDDING_DIMENSION=64` | Documentation |

**Test layer** (all reference `EMBEDDING_DIMENSIONS` constant):
| # | File | Lines | What | Coupling Type |
|---|------|-------|------|---------------|
| 7 | `test_embeddings.py` | 31,62,95,106,135 | Assertions against `EMBEDDING_DIMENSIONS` | Test assertions (auto-update via constant) |
| 8 | `test_retrieval_service.py` | 83,192 | `FakeProvider` default + `[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)` | Test assertions (auto-update via constant) |
| 9 | `test_approved_context.py` | 54,190 | `DeterministicFakeProvider` + `[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)` | Test assertions (auto-update via constant) |

All test files import `EMBEDDING_DIMENSIONS` from `arc.services.embeddings`.
When the constant changes to 1536, all test assertions update
automatically — no manual test changes required.

**Proposed source-of-truth model**:

```text
Schema (schema.sql)
  embedding vector(N) NOT NULL
        │
        ▼
EMBEDDING_DIMENSIONS = N    ← application constant derived from schema
        │
        ▼
EmbeddingSettings.dimensions = N   ← validated against constant
        │
        ▼
EmbeddingProvider.embed() / embed_many()
        │
        ▼
RetrievalService runtime validation
```

The database schema is the authoritative source. The Python constant
`EMBEDDING_DIMENSIONS` is the application's binding to that schema. A
dimension change requires:
1. Update `EMBEDDING_DIMENSIONS` in `embeddings.py`
2. Update `vector(N)` in `schema.sql`
3. Update `EMBEDDING_DIMENSION` in `.env.example`
4. Test assertions update automatically (they reference the constant)

The existing validation in `EmbeddingSettings.__post_init__` (line 89)
ensures the environment variable matches the Python constant at startup.
This remains correct: it prevents runtime mismatch between configuration
and application code.

### 4. Metadata strategy

**V1: No metadata table or per-document columns.**

Rationale:
- All documents in V1 use the same provider/model/dimension
- A configuration table adds migration and runtime complexity without
  benefit in V1 (single provider, no multi-model transitions)
- Provider/model/dimension are documented in `EMBEDDING_DIMENSIONS` and
  `.env.example` — sufficient for V1 operational visibility
- Future multi-model support can add `embedding_config` table or
  per-document metadata when the need is concrete

### 5. Migration strategy

**Schema migration + full re-embedding (maintenance window)**.

The current database contains vectors generated by
`DeterministicEmbeddingProvider`. These are word-hash histograms, NOT
semantic embeddings. They MUST be discarded and replaced.

The column is currently `embedding vector(64) NOT NULL`
(`schema.sql:135`). PostgreSQL/pgvector cannot implicitly cast
`vector(64)` to `vector(1536)` — the ALTER TABLE statement fails with
`column "embedding" cannot be cast automatically to type vector(1536)`.
There is no automatic zero-padding or resizing. The correct approach is
a column-swap: add a new `vector(1536)` column, backfill, then swap.

The existing HNSW index (`idx_knowledge_chunks_embedding` using
`vector_cosine_ops`) is tied to the old column. It must be dropped
before the column swap and recreated on the new column.

**Pre-migration backup requirement**: Before beginning the migration,
a verified database backup or snapshot MUST be created. This backup is
the recovery mechanism if the migration fails after the old embedding
column has been dropped (step 6). The 64-dimensional vectors in the
old column cannot be reconstructed from the new 1536-dimensional
vectors. Do not proceed past step 6 without a confirmed backup.

**Migration procedure (maintenance window):**

The migration runs as a standalone script (not through the
application) while the application is stopped. The script must
instantiate the production embedding provider from the provider
class itself (not through the application's composition root),
but MUST route all embedding API requests through the project's
configured gateway (OmniRoute/OpenRouter) consistent with ADR-001.
The script is independent of the application's
`EMBEDDING_DIMENSIONS` constant.

1. Stop application ingestion and vector search.
2. Drop the existing HNSW index:
   `DROP INDEX IF EXISTS idx_knowledge_chunks_embedding;`
3. Add a new embedding column:
   `ALTER TABLE knowledge_chunks ADD COLUMN embedding_new vector(1536);`
4. For each tenant, for each active document:
   a. Read each existing chunk's content from `knowledge_chunks.content`
      (already sanitized — PII guard ran at original ingestion time)
   b. Re-embed each existing chunk with the production provider (1536-dim)
   c. `UPDATE knowledge_chunks SET embedding_new = $1::vector WHERE id = $2`

   Existing chunk boundaries remain unchanged. The migration does NOT
   re-run the chunker — only embeddings are regenerated from the stored
   sanitized content.
5. Verify completeness:
   `SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_new IS NULL;`
   Must return 0 before proceeding.
6. Drop the old embedding column:
   `ALTER TABLE knowledge_chunks DROP COLUMN embedding;`
7. Rename the new column:
   `ALTER TABLE knowledge_chunks RENAME COLUMN embedding_new TO embedding;`
8. Add the NOT NULL constraint:
   `ALTER TABLE knowledge_chunks ALTER COLUMN embedding SET NOT NULL;`
9. Recreate the HNSW index:
   `CREATE INDEX idx_knowledge_chunks_embedding ON knowledge_chunks
   USING hnsw (embedding vector_cosine_ops);`
10. Update `EMBEDDING_DIMENSIONS = 1536` in `embeddings.py`
11. Update `schema.sql` to `vector(1536)`
12. Update `.env.example`

**Why this order**: Step 3 (add new column) avoids the impossible
`ALTER TYPE` cast. The old `vector(64)` column and the new `vector(1536)`
column coexist during steps 3–4. Step 5 (completeness check) ensures no
rows were missed before the old column is dropped. Steps 6–8 finalize
the swap. Step 9 (index creation) must follow step 8 because HNSW
requires a NOT NULL column.

**What happens to old vectors**: The 64-dimensional deterministic
vectors remain in the old `embedding` column until step 6 drops it.
They are never converted — they are discarded entirely when the old
column is dropped. The new `embedding_new` column starts NULL and is
populated with 1536-dimensional semantic embeddings in step 4.

**Availability during migration**:

| Phase | Application state |
|-------|------------------|
| Before migration | Fully operational (64-dim deterministic) |
| Steps 1–9 (migration script) | **Unavailable** for ingestion and vector search. Application is stopped. |
| After migration | Fully operational (1536-dim semantic) |

V1 does NOT provide partial search availability during migration.
The application is stopped for the duration of the migration script.

**Failure/recovery**: If the migration script fails before step 6
(dropping the old column), the database is in a safe state: the old
`embedding` column (64-dim) is unchanged, and the new `embedding_new`
column is partially populated. The application can be restarted
against the old column (revert steps 10–12 if applied). To resume,
re-run the migration script — step 4 is idempotent (re-embedding a
chunk that was already re-embedded simply overwrites it). The operator
can resume from the last successfully re-embedded tenant. The
completeness check in step 5 will confirm when all rows are populated.

If the migration script fails after step 6 (old column dropped),
recovery requires restoring from the pre-migration backup created
before step 1. The old 64-dimensional vectors are gone and cannot be
reconstructed.

**Rollback**: Before step 6 (dropping the old column), rollback is
straightforward: drop `embedding_new`, recreate the HNSW index on
`embedding`, restart the application with the old code. No backup
restoration is needed. After step 6, rollback requires restoring from
the pre-migration backup (the old 64-dim vectors are gone and cannot
be reconstructed from the new 1536-dim vectors). The ADR recommends
completing the migration in a single script run to minimize the window
where rollback requires backup restoration.

### 6. Failure/fallback behavior

**Fail closed. No fallback.**

| Failure Mode | V1 Behavior |
|--------------|-------------|
| Provider unavailable | `EmbeddingError` → abort operation, nothing persisted |
| Provider timeout | `EmbeddingError` → abort operation |
| Authentication failure (4xx) | `EmbeddingConfigurationError` at startup |
| Rate limiting (429) | `EmbeddingError` → abort operation |
| 5xx server error | `EmbeddingError` → abort operation |
| Malformed response | `EmbeddingError` → abort operation |
| Dimension mismatch | `EmbeddingError` → abort operation |
| Partial ingestion | Impossible (atomic transaction) |

**Why no deterministic fallback**: Falling back to the deterministic
provider when the production provider fails would create two incompatible
vector spaces. Deterministic word-hash vectors and semantic embedding
vectors do not share a meaningful similarity space. A cosine similarity
score between a semantic query vector and a word-hash document vector is
meaningless. Silent fallback would degrade retrieval quality without any
visible error, making the failure undetectable.

**Retry policy**: V1 has no automatic retry. Transient errors (5xx,
timeout) are visible as `EmbeddingError` in logs. A retry-with-backoff
policy for the SAME provider (not a fallback) may be added in a later
phase.

## Options Considered

### Option 1 — OpenAI `text-embedding-3-small` (1536-dim)

Description: Cloud-hosted embedding API via OpenAI.

Advantages:
- High semantic quality, proven in production RAG
- Mature SDK, well-documented
- 1536 dimensions (native, no reduction)
- Batch API available
- Reasonable cost

Disadvantages:
- External API dependency
- Text leaves ARC environment
- API key management required
- Provider lock-in (switching requires re-embedding)

### Option 2 — Voyage AI `voyage-3` (1024-dim)

Description: Cloud-hosted embedding API via Voyage AI.

Advantages:
- High semantic quality (competitive benchmarks)
- Enterprise-focused (data processing guarantees)
- 1024 dimensions (lower storage than 1536)

Disadvantages:
- Smaller ecosystem than OpenAI
- Less mature SDK
- Requires separate API key management
- Provider lock-in

### Option 3 — Self-hosted `sentence-transformers` (configurable)

Description: Local embedding model via Hugging Face.

Advantages:
- No external API dependency
- No data leaves ARC
- No per-token cost
- Configurable dimensions

Disadvantages:
- GPU requirements for throughput
- Model hosting/versioning complexity
- Docker image size increase
- Infrastructure overhead for Foundation Phase

### Option 4 — Continue deterministic placeholder

Description: Keep word-hash embeddings.

Advantages:
- Zero cost, zero dependency

Disadvantages:
- Non-meaningful retrieval results
- Unacceptable for production

## Rationale

Option 1 is selected because:
- OpenAI has the largest ecosystem and most documentation for RAG
- `text-embedding-3-small` is cost-effective and high-quality
- 1536 native dimensions avoid reduction quality loss
- The `openai` Python package is mature and well-maintained
- The existing `EmbeddingProvider` Protocol makes the integration
  straightforward (new class + factory update)

The dimension (1536) is a V1 engineering decision. If storage or latency
becomes a concern, the model supports `dimensions=512` via API parameter.
This is a future optimization documented as a known capability.

## PII/Security Boundary

### What reaches the embedding provider

- **Document ingestion**: Sanitized chunks only. PII guard runs BEFORE
  embedding (`knowledge.py:114` → `retrieval.py:101`). Raw content
  never reaches the provider.
- **Query embedding**: Raw query text. This is the user's own input;
  they already know it. The provider's data handling is a deployment
  decision.

### Data flow

```text
raw human content
      ↓
PiiGuardService.sanitize()
      ↓
sanitized content (KnowledgeDocument.content)
      ↓
KnowledgeChunker.chunk()
      ↓
EmbeddingProvider.embed_many(chunks)
      ↓
vector persistence (knowledge_chunks.embedding)
```

No raw persisted content is introduced by the provider integration.

### Provider data handling

**Deployment decision** — Requires provider-specific verification:
- OpenAI API data: opt-out of training available for API users
- Data retention: 30 days for abuse monitoring (can be reduced for
  enterprise)
- DPA: available for enterprise customers
- When routed through OmniRoute/OpenRouter, the gateway's data handling
  policies also apply

These are not architectural decisions. The ADR establishes that
sanitized text reaches the provider; the provider's data handling is
evaluated during deployment.

### Tenant isolation

Embedding generation is stateless — no tenant context in the provider.
Each request is independent. Cross-tenant embedding mixing is impossible.

### Secrets

API key follows existing ARC patterns (consistent with ADR-001):
- Environment variable (`OPENAI_API_KEY`) — used when connecting directly
  to OpenAI
- When routing through OmniRoute/OpenRouter, the gateway manages the
  provider credential; the application only needs the gateway endpoint
- Never logged, returned, or committed
- `.env.example` documents the variable name with safe placeholder
- Key rotation: update the environment variable and restart the
  application (direct) or update the gateway config (OmniRoute)

## Query/Document Compatibility

Query embeddings and document embeddings MUST use the same
provider/model/dimension. This is guaranteed by:
1. Single `EmbeddingProvider` instance in `RetrievalService`
2. Same instance used for `prepare_index()` (ingestion) and `search()` (query)
3. Dimension validated at runtime (`retrieval.py:103,134`)

If the provider is changed between ingestion and query, stored vectors
and query vectors would be incompatible. Runtime dimension validation
detects this mismatch and fails closed.

## Consequences

### Positive

- Retrieval results become semantically meaningful
- Existing `EmbeddingProvider` abstraction preserved (no protocol changes)
- Clean provider switching for future transitions
- Dev/test experience unchanged (deterministic provider)
- Minimal code change: new `OpenAIEmbeddingProvider` class, factory
  update, schema migration, env config

### Negative

- External API dependency (OpenAI availability affects ingestion/query)
- API key management required
- Schema migration requires column-swap (add new column, backfill,
  drop old) because pgvector cannot implicitly cast between vector
  dimensions; requires maintenance window
- Full re-embedding of all existing chunks
- Storage increase (256 bytes → 6.1 KB per vector)
- Cost: ~$0.02/1M tokens (negligible at V1 scale)

### Risks

- Provider outage blocks ingestion and query (mitigated by fail-closed;
  no data loss, just temporary unavailability)
- Provider data policies require verification before deployment
- Dimension choice locks in storage layout (mitigated by model's
  `dimensions` parameter for future optimization)

## Operational Considerations

- **API key rotation**: Direct — update `OPENAI_API_KEY` env var and
  restart. Gateway — update OmniRoute/OpenRouter config as applicable.
- **Provider outage**: Fail closed (no ingestion/queries until recovery;
  no data loss)
- **Migration**: Requires a maintenance window and a standalone
  migration/backfill script. The application is stopped during
  migration. The script instantiates the production embedding provider
  from the provider class (not through the application's composition
  root) but MUST route embedding API requests through the project's
  configured gateway (OmniRoute/OpenRouter) consistent with ADR-001.
  A verified database backup MUST be created before beginning the
  migration. Duration depends on document count and provider latency
  (~$0.20 per full re-ingestion at V1 scale). The migration uses a
  column-swap pattern (add new column, backfill, drop old) because
  pgvector cannot implicitly cast between different vector dimensions.
  The script is idempotent and can be re-run on failure.
- **Gateway alignment**: Embeddings route through the project's AI
  gateway (OmniRoute/OpenRouter) consistent with ADR-001. The
  `OpenAIEmbeddingProvider` base URL is configurable.
- **Monitoring**: DEBUG-level embedding metrics in V1. No persistent
  embedding telemetry.
- **Cost**: ~$0.02/1M tokens. For 10K docs × 5 chunks × 200 tokens =
  ~10M tokens = ~$0.20 per full ingestion. Negligible.

## Non-Goals (V1)

- Provider fallback / redundant embedding providers
- Hybrid retrieval (lexical + semantic)
- Reranking
- Query expansion
- Embedding caching
- Persistent embedding telemetry/cost tracking
- Multi-model support (per-document provider/model metadata)
- `embedding_config` metadata table (deferred until multi-model needed)
- Production LLM provider selection (separate ADR)
- Agent/Skill orchestration (ADR-006)
- Human Intervention approval gate (ADR-005)

## Implementation Sequencing

Once this ADR is accepted:

1. Create branch `feature/embedding-production-provider`
2. Implement `OpenAIEmbeddingProvider` class in `embeddings.py`
3. Update `build_embedding_provider()` factory
4. Write provider contract tests
5. Write dimension validation tests
6. Write error mapping tests
7. Run focused test suite (deterministic provider, no schema change yet)
8. Implement standalone migration/backfill script (instantiates
   `OpenAIEmbeddingProvider` from the provider class, routes API
   requests through the project's configured gateway per ADR-001,
   reads `knowledge_chunks.content`, re-embeds existing chunks,
   performs column-swap)
9. **Pre-migration**: create and verify a database backup/snapshot
10. **Maintenance window**: run migration script
    (stop app → drop index → add column → backfill → verify →
    drop old column → rename → set NOT NULL → recreate index)
11. Update `EMBEDDING_DIMENSIONS = 1536`
12. Update `schema.sql` to `vector(1536)`
13. Update `.env.example` / add `OPENAI_API_KEY`
14. Run full test suite
15. Run ruff check/format
16. Commit, push, create PR
17. Adversarial review
18. Merge

Steps 2–7 are code-only changes that do not touch the database.
Step 8 implements the migration utility. Step 9 creates the
pre-migration backup. Step 10 is the maintenance-window migration.
Steps 11–13 update documentation and configuration to match the
post-migration state.

## Related Documents

- ADR-001: Unified Intelligence architecture (AI provider routing)
- TRD 11: Embeddings layer responsibilities
- TRD 12: Secure RAG retrieval flow
- TRD 34: OpenRouter/AI provider selection
- ADR-003: Company Brain document identity
- PRD 12: Secure RAG requirements
- PR #26: Company Brain knowledge storage
- PR #29: Secure RAG retrieval foundation

## Supersedes

None

## Superseded By

None
