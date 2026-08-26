# ADR-003: Company Brain Document Identity and Re-ingestion Semantics

## Status

Accepted

## Date

2026-08-24

## Decision Owners

- Bala (Person A) — Company Brain / PII / Secure RAG primary; author
- Joe — Skills Engine / Unified Intelligence primary; consumer reviewer
- Bharath — Webhooks / Connectors primary; ingestion-writer reviewer

## Context

The merged Company Brain foundation (PR #26) stores knowledge documents
with a per-ingestion UUID primary key and an explicitly metadata-only
`version` column. The foundation deliberately claimed no logical document
identity or revision semantics (`KnowledgeDocument`, `src/arc/domain/models.py`;
CURRENT_STATE Company Brain section).

Downstream ingestion writers now exist that can re-deliver the same
logical document:

- Connector synchronization (PR #32) loops provider records into
  `KnowledgeService.ingest_document`; every re-sync of the same source
  record therefore creates a NEW document row with a new UUID and a new
  chunk set (`src/arc/services/connector_sync.py:140-146`). Repeated
  synchronization duplicates the retrieval corpus.
- Inbound Webhooks (PR #34, Person C) will become another ingestion
  writer with redelivery semantics.

Duplicate logical documents pollute Secure RAG results, waste embedding
storage, and skew relevance. ADR-001 intentionally keeps the Company
Brain schema open; this ADR defines the missing identity model as the
smallest compatible design.

## Decision

### Logical identity

A knowledge document's logical identity is the triple:

```text
(tenant_id, source, external_id)
```

- `tenant_id`: identity is ALWAYS tenant-scoped. The same external
  identifier in two tenants is two distinct documents.
- `source`: the existing `KnowledgeSource` enum value.
- `external_id`: a new optional `VARCHAR(255)` column holding the
  writer's stable identifier for the logical document. Connector
  synchronization binds `external_id = "{provider}:{record.source_id}"`
  (matching its provenance suffix). Manual/API ingestion without an
  external identity persists `external_id = NULL`.

Identity is enforced by the database, not only by application code:

```sql
ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS external_id VARCHAR(255);
CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_documents_identity
    ON knowledge_documents (tenant_id, source, external_id)
    WHERE external_id IS NOT NULL;
```

Both statements are idempotent under the existing bootstrap
(`schema.sql`) and safe against existing data: pre-existing rows have
`external_id IS NULL` and are excluded by the partial index.

Documents without an external identity keep today's behavior: each
ingestion creates a new document (manual/API writes are not re-deliveries).

### Re-ingestion semantics (documents WITH an external identity)

Ingestion runs in this strict order — the PII boundary is never bypassed,
including on re-delivery:

```text
untrusted content
    ↓ PII sanitization (fail closed)
identity resolution (tenant-scoped)
    ↓ no existing document → create (version = 1)
existing document found:
    sanitized content identical  → return existing unchanged (idempotent)
    sanitized content differs    → prepare new chunks/embeddings IN MEMORY
                                   (embedding failure aborts before any write)
                                   then atomically: version = version + 1,
                                   content updated, all old chunks replaced
```

- Identical redelivery returns the existing document with no version bump
  and no chunk churn.
- Content changes update the SAME row (same id, provenance, created_at)
  and increment `version` by exactly 1. There is no revision-history
  table; `version` records how many accepted content changes occurred.
- Chunks are replaced wholesale inside the same transaction as the
  document update: a document is never left with stale or partial chunks.
- Provenance is immutable once assigned; it is attribution, not identity
  input beyond the initial creation.

### Concurrency

Races are resolved by the database invariant, following the established
repository pattern (constraint violation → controlled error → tenant-
scoped refetch), not by check-then-insert:

- Two concurrent first deliveries of one identity: exactly one INSERT
  wins; the loser observes the uniqueness index, re-resolves the
  identity, and continues through the identical/changed-content logic.
- Concurrent updates of one identity serialize on the row UPDATE inside
  the transaction; the final state is always exactly one row per
  identity.

### Failure behavior (unchanged invariants)

- PII failure → nothing persisted, `PiiGuardError` propagates (also true
  when the document already exists).
- Embedding failure on a content change → nothing persisted; the existing
  document/version/chunks remain untouched.
- Any mid-transaction failure rolls back document update and chunk
  replacement together.

## Alternatives Considered

1. Parse the writer identity out of the `provenance` string — rejected:
   stringly-typed, non-queryable, breaks if provenance wording evolves.
2. Global identity without tenant participation — rejected: would let a
   cross-tenant collision deny a legitimate write; identity must be
   tenant-scoped.
3. Full revision history (append-only versions with a revisions table) —
   rejected for now: no product requirement exists; smallest compatible
   design preferred; revisitable via future ADR without breaking the
   identity triple.
4. Application-only deduplication without a database constraint —
   rejected: concurrent writers could still create duplicates; correctness
   must be DB-enforced.

## Consequences

### Positive

- Connector re-syncs become idempotent: one logical document per source
  record per tenant, with clean version progression.
- Future ingestion writers (Webhooks) inherit correct deduplication by
  supplying an `external_id`; no Company Brain changes needed per writer.
- Retrieval corpus integrity improves immediately (no duplicate chunks).
- Existing manual ingestion and all existing security invariants are
  preserved unchanged.

### Negative

- Documents created before this change have `external_id IS NULL` and are
  NOT retroactively deduplicated; a one-time cleanup/migration of
  duplicated legacy rows remains open follow-up work (deliberately not
  done here to avoid destructive operations).
- Writers MUST supply stable external identifiers; unstable ids would
  reintroduce duplication at the writer's responsibility.

## Security Considerations

- Identity resolution queries are tenant-scoped in SQL; a tenant can never
  match, read, update, or collide with another tenant's document.
- Sanitization precedes both the identity comparison and any persistence;
  raw content never reaches storage, logs, or comparisons.
- No secrets or unsanitized content are introduced to logs or errors.

## Testing / Validation

- Service-level: first-create, idempotent redelivery (guard invoked every
  time), changed-content version bump with atomic chunk replacement,
  embedding-failure aborts before update, missing external_id keeps
  legacy create behavior, cross-tenant independence.
- Repository-level (real PostgreSQL): partial unique index enforcement,
  NULL exclusion, cross-tenant same-identity allowance, atomic chunk
  replacement including rollback preserving the prior state, concurrent
  first-delivery producing exactly one row.
- Connector-level: sync passes `external_id = "{provider}:{source_id}"`;
  repeated sync does not create duplicates end-to-end.

## Related Documents

- ADR-001 (Company Brain schema kept open — item resolved here)
- PRD §11/§23 (Knowledge, Provenance), TRD §9.1 (version as structured info)
- PR #26 (knowledge foundation), PR #29 (chunks), PR #32 (connector sync deferral note)

## Supersedes

None (resolves an explicitly open point recorded in CURRENT_STATE and
PR #32).

## Superseded By

None.
