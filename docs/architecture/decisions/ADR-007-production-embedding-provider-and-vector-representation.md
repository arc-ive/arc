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
embedding provider.

Rationale:
- High semantic quality (MTEB benchmark leader for cost-performance)
- 1536 dimensions (default; also supports 512 via `dimensions` parameter)
- Mature Python SDK (`openai>=1.0`)
- Well-documented API with batch embedding support
- Reasonable cost (~$0.02/1M tokens)
- Widely adopted; proven in production RAG systems

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

**Test layer**:
| # | File | Lines | What | Coupling Type |
|---|------|-------|------|---------------|
| 7 | `test_embeddings.py` | 31,62,95,106,135 | Assertions against `EMBEDDING_DIMENSIONS` | Test assertions |
| 8 | `test_retrieval_service.py` | 83,192 | `FakeProvider` default + assertions | Test assertions |
| 9 | `test_approved_context.py` | 54,190 | Test vector construction | Test assertions |

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

**V1: Store provider/model/dimension in a configuration table, not per
document.**

Rationale:
- All documents in V1 use the same provider/model/dimension
- Per-document metadata adds storage overhead and query complexity
- A configuration table is simpler and sufficient for V1
- Future multi-model support can add per-document metadata later

Schema addition (idempotent, non-breaking):

```sql
CREATE TABLE IF NOT EXISTS embedding_config (
    id VARCHAR(255) PRIMARY KEY,
    provider VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    dimensions INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

This table stores the CURRENT embedding configuration. On provider
change, a new row is inserted (old rows retained for audit). The
application reads the latest row to validate compatibility.

**Alternative considered and rejected for V1**: Per-document columns
(`embedding_provider`, `embedding_model` on `knowledge_documents`).
Rejected because: (a) adds column to every document row, (b) requires
updating every document on provider change, (c) V1 has only one
provider. Can be added later if multi-model support is needed.

### 5. Migration strategy

**Schema migration + full re-embedding (per-tenant)**.

The current database contains vectors generated by
`DeterministicEmbeddingProvider`. These are word-hash histograms, NOT
semantic embeddings. They MUST be discarded and replaced.

Migration steps:
1. Add `embedding_config` table
2. Insert V1 config row (`openai`, `text-embedding-3-small`, 1536)
3. For each tenant:
   a. Read all active documents
   b. For each document: re-chunk, re-embed with production provider
   c. `UPDATE knowledge_chunks SET embedding = $1::vector WHERE id = $2`
   d. After all chunks updated: `REINDEX INDEX idx_knowledge_chunks_embedding`
4. Update `EMBEDDING_DIMENSIONS = 1536` in `embeddings.py`
5. Update `schema.sql` to `vector(1536)`
6. Update `.env.example`

During migration:
- Documents remain readable (content is in `knowledge_documents.content`)
- Vector search returns partial results (only re-embedded chunks match)
- No downtime for document reads
- Ingestion of new documents uses production provider after step 4

Rollback: Re-embed all chunks with deterministic provider (reversible).
The deterministic provider is stateless and deterministic, so rollback
produces identical vectors to the original.

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

These are not architectural decisions. The ADR establishes that
sanitized text reaches the provider; the provider's data handling is
evaluated during deployment.

### Tenant isolation

Embedding generation is stateless — no tenant context in the provider.
Each request is independent. Cross-tenant embedding mixing is impossible.

### Secrets

API key follows existing ARC patterns:
- Environment variable (`OPENAI_API_KEY`)
- Never logged, returned, or committed
- `.env.example` documents the variable name with safe placeholder

## Query/Document Compatibility

Query embeddings and document embeddings MUST use the same
provider/model/dimension. This is guaranteed by:
1. Single `EmbeddingProvider` instance in `RetrievalService`
2. Same instance used for `prepare_index()` (ingestion) and `search()` (query)
3. Dimension validated at runtime (`retrieval.py:103,134`)

If the provider is changed between ingestion and query, stored vectors
and query vectors would be incompatible. The `embedding_config` table
detects this: the application validates that the current provider matches
the config used for stored vectors.

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
- Schema migration from 64 → 1536 dimensions
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

- **API key rotation**: Update environment variable, restart application
- **Provider outage**: Fail closed (no ingestion/queries until recovery;
  no data loss)
- **Migration**: Per-tenant, documented procedure. Can be performed
  during maintenance window.
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
- Production LLM provider selection (separate ADR)
- Agent/Skill orchestration (ADR-006)
- Human Intervention approval gate (ADR-005)

## Implementation Sequencing

Once this ADR is accepted:

1. Create branch `feature/embedding-production-provider`
2. Implement `OpenAIEmbeddingProvider` class in `embeddings.py`
3. Update `build_embedding_provider()` factory
4. Add `embedding_config` table to `schema.sql`
5. Update `EMBEDDING_DIMENSIONS = 1536`
6. Update `schema.sql` to `vector(1536)`
7. Update `.env.example`
8. Add `OPENAI_API_KEY` to `.env.example`
9. Write provider contract tests
10. Write dimension validation tests
11. Write error mapping tests
12. Write migration tests
13. Run focused test suite
14. Run full test suite
15. Run ruff check/format
16. Commit, push, create PR
17. Adversarial review
18. Merge

## Related Documents

- TRD 11: Embeddings layer responsibilities
- TRD 12: Secure RAG retrieval flow
- TRD 34: OpenRouter/AI provider selection
- ADR-001: Unified Intelligence architecture
- ADR-003: Company Brain document identity
- PRD 12: Secure RAG requirements
- PR #26: Company Brain knowledge storage
- PR #29: Secure RAG retrieval foundation

## Supersedes

None

## Superseded By

None
