# ARC Ask Arc / RAG Evaluation Baseline — CURRENT Implementation (no prod change)

> This is the trustworthy baseline before any retrieval / prompt / generation / citation / frontend changes. All measurements use the **current production code path**: `KnowledgeService → RetrievalService (dense + lexical + RRF) → ApprovedContext → UnifiedIntelligenceService (DeterministicLlmProvider) → IntelligenceAnswer → _intelligence_answer_response → frontend`. No fake RAG, no parallel implementation.

## A. Current ARC RAG Architecture as Actually Implemented

**Intelligence Controller** `src/arc/api/controllers.py:1377`
- `POST /tenants/{tenant_id}/intelligence/query` requires `KNOWLEDGE_READ` via `require_tenant_permission`, trusted `TenantContext` (X-10), `AuthenticatedPrincipal`, `AuthorizationService`.
- Delegates to `UnifiedIntelligenceService.answer_query`. Returns `_intelligence_answer_response(answer)` JSON with `request_id, tenant_id, principal_id, query, answer, citations, retrieval_method, context_used, tool_executions`. No prompt leak.

**UnifiedIntelligenceService** `src/arc/services/intelligence.py:197`
- Input: trusted `TenantContext`, `query`, `limit`, `principal`, `authorization`, `source_type`.
- Step 1: `retrieval.approved_search(context, query, limit=5)` — ONLY retrieval path, holds no repo.
- Step 2: If `approved.items` empty → `answer=None, context_used=False`, LLM never invoked (no invention) `intelligence.py:261`.
- Step 3: Optional single tool proposal `LLM.propose_tool` if `ToolProposingLlm` + `tool_service` + `principal/authorization` present. Proposal via `ToolProposal.parse` (strict), executed via `ToolExecutionService.execute_tool` (registry, auth, policy, validation, audit). Bounded observation folded into prompt.
- Step 4: `_build_prompt(approved, query, observation, budget=8192)` `intelligence.py:427` — system line, `APPROVED CONTEXT:` block with `[N] citation: ref` + sanitized `content`, `QUERY:`, optional `TOOL OBSERVATION (untrusted data)`. Only `content`+`citation_reference` cross into prompt; tenant/principal/vectors/scores/authorization never.
- Step 5: `llm.complete(prompt)` → `answer` then `_extract_grounded_citations(answer, approved.items)` `intelligence.py:145` — resolves `[N]` and verbatim `citation_reference` against approved set only; deduplicated by first appearance; fabricated refs dropped.
- Returns `IntelligenceAnswer` with `request_id` (new uuid), `tenant_id`, `principal_id`, `query`, `answer`, `citations`, `retrieval_method=HYBRID_RRF`, `context_used`, `tool_executions`.
- Fail-closed: embedding/LLM errors propagate, no partial answer. One iteration only.

**RetrievalService** `src/arc/services/retrieval.py:179`
- `chunk_repo: PostgreSQLKnowledgeChunkRepository`, `chunker: KnowledgeChunker (max 1000, overlap 150)`, `embedding_provider: DeterministicEmbeddingProvider (dimensions 1536, word-hash crc32 bucket, L2 norm) or OpenAI`.
- `prepare_index` chunks sanitized content (PII already stripped by `KnowledgeService`), embeds, validates dims.
- `search` (dense): embed query, `chunk_repo.search(tenant_id, embedding, limit)` — cosine via pgvector, tenant-scoped `WHERE tenant_id=$1`.
- `lexical_search`: `chunk_repo.lexical_search(tenant_id, query, limit)` via `plainto_tsquery` + `ts_rank` on `search_vector`.
- `approved_search` `retrieval.py:307` — **hybrid**: `dense + lexical → RRF fuse (k=60)` `ReciprocalRankFusion.fuse` sums `1/(k+rank)`, merges scores, sorted by fused score + `chunk_id` tie-break. Then `_dedup_by_lineage` (keep highest `document_version` per `(tenant, external_id, source)`), then relevance floor: `dense_score >= MIN_RELEVANCE_SCORE` (env, default 0.0 deterministic → disabled), lexical-only bypass floor, then `[:limit]` truncation, then map to `ApprovedContextItem` with `citation_reference=f"{doc_id}#c{seq}"`, `relevance_score=RRF`. Returns `ApprovedContext` with `tenant_id`, `principal_id`, `query`, `retrieval_method=HYBRID_RRF`, `items`, `security_metadata`.

**Dense retrieval** `retrieval.py:241` — deterministic word-hash histogram, L2 norm. Production would be OpenAI `text-embedding-3-small` 1536 via `OpenAIEmbeddingProvider`.

**Lexical retrieval** `retrieval.py:277` — `search_vector` GIN, `plainto_tsquery`.

**RRF** `retrieval.py:62` — stateless, deterministic.

**ApprovedContext** `src/arc/domain/models.py:608` — `request_id, tenant_id, principal_id, query, retrieval_method, items, security_metadata`. Each `ApprovedContextItem` sanitized content + `citation_reference`.

**LLM invocation** `src/arc/services/llm.py:133` — `DeterministicLlmProvider` (dev/CI) echoes `[N] citation: ref` lines; `OpenRouterProvider` (prod) via OmniRoute `https://openrouter.ai/api/v1/chat/completions`.

**Answer/citation construction** — `intelligence.py:146` + `311`.

**API response** — `controllers.py:1356` serialization.

**Frontend rendering** — `frontend/src/pages/knowledge/KnowledgePage.jsx` etc. renders `answer` text and `citations` array as `[doc#cN]` chips; no extra processing. Failure there would be missing `citations` field or `answer=null` not handled.

**Information available per stage (to distinguish failures):**
- After `retrieval.approved_search`: `ApprovedContext.items` (doc_id, chunk_id, content, citation_reference, relevance_score, source). Check expected doc present → retrieval failure vs not.
- After `_build_prompt`: prompt string contains approved content + citations + query + observation. Check truncation → context failure.
- After `answer_query`: `IntelligenceAnswer.answer, citations, context_used, retrieval_method`. Check answer correctness vs expected facts, faithfulness vs approved facts, relevance vs query → generation failure. Check citations subset of approved and includes expected → citation failure.
- After `_intelligence_answer_response`: JSON fields → frontend failure if missing.
- Security: `retrieval.approved_search` re-validates `match.tenant_id == context.tenant_id` else `RuntimeError`; `chunk_repo.search` SQL `WHERE tenant_id`. Check cross-tenant leak → security failure.

## B. Evaluation Dataset Summary

- **Isolated eval tenant:** `eval-tenant-<uuid>` + `other-tenant-<uuid>` per run, unique, 10 controlled docs + 1 other-tenant secret doc ingested via canonical `KnowledgeService.ingest_document` (chunked, embedded). No reference data used for ground truth precision.
- **Docs (10):** vacation-policy, remote-work-policy, expense-reimbursement, security-incident, office-access, benefits-enrollment, code-review-guidelines, oncall-rotation, long-policy (multi-chunk, >1000 chars), distractor-lunch.
- **Cases: 38** (30-50 required, 38 chosen):
  - factual (6): F01-F06
  - multipart (5): M01-M05
  - overview (4): O01-O04
  - multichunk (5): C01-C05
  - distractor (4): D01-D04
  - unanswerable (6): U01-U06
  - citation (5): CIT01-CIT05
  - isolation (3): ISO01-ISO03
- **Ground truth per case:** `expected_external_ids` → resolved to `document_id` after ingestion, `expected_facts` substrings (lowercased check, not LLM-judged), `answerable` bool, `security` expectation (`no_leak`/`refuse`), `category` for grouping. Deterministic files: `tests/evaluation/golden_datasets.py` not used for this baseline; dataset inline in `tests/evaluation/test_rag_baseline.py:22`.

## C. Baseline Metrics (current production path, DeterministicLlmProvider, MIN_RELEVANCE_SCORE=0)

```
Total cases: 38  Passed: 27  Failed: 11
Recall@5: 93.10%  (27/29 answerable with expected doc in top5)
Recall@10: 100.00% (29/29 answerable in top10)
Answer correctness (deterministic proxy: answer not None + citation has expected for answerable; answer is None or refusal for unanswerable): 71.05% (27/38)
Citation subset OK (citations ⊆ approved): 100.00%
Citation has expected (answerable): 93.10%
Security isolation (no cross-tenant leak): 100.00%
Frontend serialization OK: 100.00%
```

- Recall@5 misses are only 2 answerable cases (M02, CIT03) where expected doc rank 7-8, but within top10.
- All unanswerable correctly fail answer correctness (deterministic provider never refuses, always returns citations) — expected baseline failure.

## D. Top Failure Categories

- **By layer:** GENERATION 9 (all unanswerable + isolation that is unanswerable) , RETRIEVAL 2 (M02, CIT03). No CONTEXT (prompt budget not hit), no CITATION (subset always OK), no SECURITY (0 leaks), no FRONTEND (100% OK).
- **By category:** unanswerable 6/6 fail, multipart 1/5 fail (M02), citation 1/5 fail (CIT03), isolation 3/3 considered GENERATION in this proxy because isolation is unanswerable but retrieval correctly does not leak — failure is generation not refusing. All factual, overview, multichunk, distractor pass except M02/CIT03.

## E. 5-10 Representative Failures with Diagnosis

1. **M02 [multipart] RETRIEVAL** `What is expense limit and what is required for reimbursement?` Expected `expense-reimbursement` doc rank 7 (recall5 false, recall10 true). Root: dense word-hash overlap sparse; lexical should catch “reimbursement” but RRF ranking placed it 7th behind 5 unrelated docs. **Layer: RETRIEVAL** (ranking, not security).

2. **CIT03 [citation] RETRIEVAL** `What is the office visitor policy?` Expected `office-access` rank 6, top5 were lunch/distractor-like docs with “policy” word overlap. **Layer: RETRIEVAL** (keyword “visitor” lexical hit rank 6, not top5).

3. **U01 [unanswerable] GENERATION** `What is the stock price of Acme?` Retrieval returned 5 unrelated docs (MIN_RELEVANCE_SCORE=0, no filtering), `answer` is deterministic `Deterministic response using 5 ...` with citations, should be `None` + “does not contain”. **Layer: GENERATION** (grounding failure) + **CONTEXT** (relevance floor disabled for deterministic).

4. **U02 [unanswerable] GENERATION** `Who won the 1998 World Cup final?` Same as U01, unrelated retrieval + no refusal. **Layer: GENERATION**.

5. **U03 [unanswerable] GENERATION** `What is the airspeed velocity of an unladen swallow?` Nonsense query still retrieves top5 docs via word-hash collision (“work”, “policy” overlap). **Layer: GENERATION** (should be empty context).

6. **U04 [unanswerable] GENERATION** `What is the CEO's favorite color?` Same. **Layer: GENERATION**.

7. **U05 [unanswerable] GENERATION** `Best recipe for sourdough bread with rye flour` Contains “recipe” not in corpus, yet retrieves docs with “policy” overlap. **Layer: GENERATION**.

8. **U06 [unanswerable] GENERATION** `zzzz qqqq xyzzy plugh frobnicate` Nonsense words, still retrieves 5 docs (deterministic hash still maps to buckets, cosine>0). **Layer: GENERATION**.

9. **ISO01 [isolation] GENERATION (security OK, generation fail)** `What is Project Falcon budget?` Secret only in other tenant, retrieval correctly returns 0 other-tenant docs (security OK, `security_ok` true), but generation still answers with 5 unrelated eval-tenant docs instead of `None`. No leak, but wrong to answer. **Layer: GENERATION** (should refuse), **SECURITY: OK**.

10. **ISO02/ISO03 similar** — isolation queries correctly not leaking, but generation fails to refuse.

## F. What Should Be Fixed First and Why

1. **Unanswerable / relevance floor (GENERATION + CONTEXT)** — 6/6 unanswerable fail, 3 isolation fail same root. With `MIN_RELEVANCE_SCORE=0` deterministic cannot distinguish off-corpus; production with real embeddings must tune `MIN_RELEVANCE_SCORE` to measured threshold so `approved_search` returns empty `items` and `answer_query` returns `answer=None` without invoking LLM. This is the single biggest baseline failure (9 of 11) and is load-bearing for faithfulness. Fix before retrieval ranking: even perfect recall would still hallucinate.

2. **Retrieval ranking at k=5 (RETRIEVAL)** — M02, CIT03 recall@5 miss but recall@10 100% shows RRF is correct but top5 ordering weak for deterministic hashing. With real embeddings + lexical, measure and tune RRF weight or `limit` (e.g., promote lexical for keyword queries like “reimbursement”, “visitor”). Do not change algorithm yet — first set relevance floor, then measure again.

3. **Prompt budget / context truncation (CONTEXT)** — not failing now (budget 8192, docs small), but long-policy multi-chunk case will hit budget when corpus grows. Keep as regression guard.

## G. What Should NOT Be Changed Because It Is Already Working

- **Tenant isolation / security boundary:** 100% isolation, no cross-tenant chunks returned, `security_ok` 100%, defensive re-validation `match.tenant_id != context.tenant_id` → RuntimeError never leaked. Do not weaken `WHERE tenant_id` or add client-supplied tenant.
- **Hybrid RRF + lineage dedup + closed whitelist:** Recall@10 100% shows RRF correctly finds expected doc within 10; dedup preserves sibling chunks; `ToolRegistry` closed. Do not add new RAG framework.
- **ApprovedContext → prompt → citation pipeline:** `citation subset OK` 100%, prompt contains only `content`+`citation_reference`, no tenant/principal/vectors/scores leak (verified in `tests/test_intelligence_service.py`). `_extract_grounded_citations` correctly drops fabricated `[99]`. Do not rewrite prompts.
- **Audit and API serialization:** `frontend_ok` 100%, `_intelligence_answer_response` preserves `citations` exactly. Do not redesign API.
- **Deterministic provider as CI baseline:** Keep deterministic for reproducible CI; do not switch CI to OpenRouter until relevance floor tuned. Production LLM (OpenRouter) already correct for real semantic queries per `golden_datasets` fixtures.

---

**Reproducibility**
- Dataset inline, isolated tenants per run, real `RetrievalService.approved_search` + `UnifiedIntelligenceService.answer_query` + `_intelligence_answer_response`.
- Metrics deterministic string checks, no LLM-as-judge; judge criteria explicit in `tests/evaluation/test_rag_baseline.py:300`.
- Commands:
```
DATABASE_URL=postgresql://arc:arc-dev-password@localhost:5432/arc_test PYTHONPATH=src uv run pytest tests/evaluation/test_rag_baseline.py -v
# report: tests/evaluation/baseline_report.json/.md
DATABASE_URL=... PYTHONPATH=src uv run pytest tests/test_retrieval_service.py tests/test_intelligence_service.py tests/test_intelligence_api.py tests/evaluation -q
uv run ruff check . && uv run ruff format --check .
```
- Production code unchanged: `git diff origin/main...HEAD -- src/` = 0.
