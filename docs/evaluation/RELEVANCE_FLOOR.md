# Relevance floors: what they gate, and how to set them honestly

## The short version

ARC has two relevance floors, not one:

| Variable | Applies to | Scale | Default |
|---|---|---|---|
| `MIN_RELEVANCE_SCORE` | matches with a dense hit | pgvector cosine, roughly 0–1 | `0.0` (disabled) |
| `MIN_LEXICAL_RELEVANCE_SCORE` | lexical-only matches | PostgreSQL `ts_rank` | `0.0` (disabled) |

**Set both or neither.** Setting only the dense floor leaves the gate
bypassable, which is the defect this document exists to explain.

Neither has a non-zero default, and that is deliberate — see
[Why no default](#why-there-is-no-shipped-default).

## Why there are two floors

Retrieval is hybrid: dense (pgvector cosine) and lexical (PostgreSQL
full-text `ts_rank`), fused by Reciprocal Rank Fusion.

Those three numbers are not interchangeable:

- **Cosine** is a similarity in roughly `[0, 1]`, comparable across queries.
- **`ts_rank`** is a lexical weighting whose magnitude depends on term
  frequency and document length. It is not a similarity and shares no scale
  with cosine.
- **The fused RRF score** is a sum of `1/(k + rank)` terms with `k = 60`. For
  a result list of five it lives in roughly `[0.016, 0.033]` regardless of how
  relevant anything is. It encodes *agreement between rankers*, not
  relevance.

So there is exactly one correct place to gate on similarity: the per-method
score, before fusion collapses it. Thresholding the RRF score would be a
category error — a floor of `0.25` would empty every result set, including
perfect matches, because no RRF score ever reaches `0.25`. A test pins this
(`test_dense_floor_does_not_use_the_fused_rrf_score`).

## The bypass this closed

`MIN_RELEVANCE_SCORE` floors `dense_score`. A lexical-only match — one the
embedding missed but full-text search found — has no `dense_score` at all.

Before `MIN_LEXICAL_RELEVANCE_SCORE` existed, such a match was admitted
unconditionally. The consequence:

> An operator sets `MIN_RELEVANCE_SCORE=0.9`, the strictest plausible cosine
> floor. A user asks "what is the refund policy for concert tickets?" — an
> off-corpus question. Dense retrieval correctly rejects everything. Lexical
> retrieval matches the single token *policy* against the credential-rotation
> policy, `ts_rank` 0.03. That chunk enters the approved context and reaches
> the prompt. The configured floor did nothing.

The fix is not to floor `ts_rank` against a cosine threshold — that would be
the same category error. It is to give `ts_rank` its own floor on its own
scale.

`tests/evaluation/test_rag_lexical_floor.py` pins both halves: that the
bypass exists when only the dense floor is set, and that it closes when both
are.

## Why there is no shipped default

A correct threshold is a joint property of the embedding provider and the
corpus. It is not a constant anyone can ship:

- **Provider.** The deterministic word-hash provider used in CI and the
  production OpenAI `text-embedding-3-small` produce cosine distributions
  with entirely different shapes. A threshold measured on one is meaningless
  on the other.
- **Corpus.** A tenant with 10 documents on one topic and a tenant with
  10,000 across forty topics have different off-corpus similarity ceilings.

Shipping a plausible-looking non-zero default would convert "no gate" into
"a gate calibrated for someone else's data", which is worse: it looks like a
safeguard while rejecting real questions or admitting fake ones, and nobody
re-measures a value that came with the product.

For the record, the deterministic provider **does** separate on the
evaluation corpus in `tests/evaluation/`:

```
off-corpus max cosine : 0.222222   ("What is the airspeed velocity of an unladen swallow?")
on-corpus  min cosine : 0.306186   ("how do I escalate a severity one incident?")
gap                   : 0.083964
midpoint              : 0.264204
```

That is a real measurement on a five-chunk corpus, and it is *still* not a
defensible default — it is evidence that the mechanism works, not that
`0.264` is right for production.

## Measuring your thresholds

```bash
DATABASE_URL=postgresql://... \
EMBEDDING_PROVIDER=openai \
python scripts/measure_relevance_floor.py \
    --tenant-id acme \
    --on-corpus-file on.txt \
    --off-corpus-file off.txt
```

`on.txt` holds questions the corpus **should** answer; `off.txt` holds
questions it **should not**, one per line.

Make `off.txt` realistic. Nonsense queries ("zzzz qqqq xyzzy") are trivially
rejected and prove nothing. The queries that matter are plausible near-misses:
a policy the company does not have, a system it does not run, a benefit it
does not offer. Those are what a real user actually asks.

The script prints every query's top dense and lexical score, then the
separation and a recommended midpoint for each floor.

### When it reports OVERLAP

Exit code `1` means the distributions overlap: the highest-scoring off-corpus
query outranks the lowest-scoring on-corpus one. No single threshold rejects
the first without also rejecting the second.

This is a finding, not a script failure. Options, in preference order:

1. **Leave the floors disabled** and rely on generation-side refusal. The
   grounding instruction already tells the model to refuse when the context
   does not cover the question, and `UnifiedIntelligenceService` returns
   `answer: null, context_used: false` when retrieval is empty.
2. **Improve the corpus.** Overlap often means a genuine gap — the off-corpus
   query is one users ask and the corpus should cover.
3. **Change embedding provider.** A stronger model separates better.

Do not split the difference and set a threshold anyway. A floor placed inside
an overlap silently rejects real questions, and the symptom — "Ask Arc says
it doesn't know" — looks identical to a corpus gap, so it will be debugged in
the wrong place for a long time.

## What the floors do not do

- They do not affect tenant isolation. The tenant boundary comes from the
  trusted `TenantContext`; every match is re-validated against it and a
  foreign match raises rather than being filtered. A test pins this
  (`test_cross_tenant_match_still_fails_closed`).
- They do not affect version supersession. `_dedup_by_lineage` runs before
  the floor.
- They do not change `ApprovedContextItem.relevance_score`, which remains the
  RRF score.
- They do not make the model refuse. They control what reaches the prompt.
  Refusal is the generation layer's job.
