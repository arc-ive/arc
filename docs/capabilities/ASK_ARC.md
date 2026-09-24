# Arc — Ask Arc

How a question becomes a grounded answer, what happens when it cannot,
and how to verify any of it.

Behaviour below was measured against a running instance. Where something
is environment-dependent, it says so rather than describing an intention
as a fact.

---

## 1. The flow

```
question
  |  session cookie + CSRF double-submit
authentication
  |  trusted tenant context (never from the request body)
authorization                       knowledge:read
  |
hybrid retrieval                    dense + lexical, fused by RRF
  |  tenant SQL filter, then a defensive re-check per match
ApprovedContext                     sanitized content + citation refs only
  |
LLM                                 no tenant ids, no vectors, no auth state
  |
answer + citations
  |
frontend                            citations resolved to document titles
```

The boundary that matters: the model receives **only** the
ApprovedContext. Not the tenant id, not the principal, not scores, not
vectors, not authorization state (V2-ADR-008).

## 2. Setup

```bash
# 1. Backend and frontend running (see PROJECT_CONTEXT.md).
# 2. Load knowledge - through the real API, not the database.
python demo/load_knowledge.py \
  --tenant ref-acme-technologies \
  --user ref-acme-technologies-company-admin
# 3. Ask, signed in as any member with knowledge:read.
```

### Configuration that changes behaviour

| Variable | Effect |
|---|---|
| `LLM_PROVIDER` | `deterministic` returns a fixed, machine-shaped string, not prose. Ask Arc only *looks* like a product with a real provider configured. |
| `EMBEDDING_PROVIDER` | `deterministic` produces non-semantic vectors: ranking is effectively lexical. |
| `MIN_RELEVANCE_SCORE` | Floor below which a dense match is dropped. Defaults to `0.0` - disabled - which is correct for the deterministic provider, where cosine values do not separate on- from off-corpus queries. **Set a measured value in production.** |
| `PROMPT_CONTEXT_MAX_CHARS` | Character budget for the context block. |

## 3. Defined behaviour

### A. The knowledge answers the question

Grounded answer with citations. Verified: asking *"How many days of
annual leave do I get?"* against the demo pack retrieves the Leave
Policy first and cites it.

### B. Company knowledge does not contain the answer

Two defences, at different layers.

**Retrieval layer** - when nothing passes the relevance floor,
`ApprovedContext` is empty, the service returns `answer: null,
context_used: false`, and the frontend says:

> Nothing in your Company Brain covers this yet.
> Arc answers only from your company's own knowledge. It will not fill
> the gap from somewhere else.

**Prompt layer** - hybrid retrieval always returns its top-k, so with
the floor disabled an off-corpus question arrives with a full block of
unrelated documents. The system instruction therefore names refusal as a
valid answer:

> If the approved context does not contain the answer, say so plainly
> and do not infer, estimate or invent a company fact. You may add
> general knowledge only when it is useful and only if you state clearly
> that it does not come from this company's records.

**This layer is only as good as the model.** With
`LLM_PROVIDER=deterministic` the instruction is unexercised - the
deterministic provider ignores it and emits its fixed string. The
instruction is asserted by tests; the *behaviour* requires a real model
and should be re-measured against the negative cases in
`demo/knowledge/EXPECTED_ANSWERS.md` when one is configured.

### C. The question is unrelated to the company

Same path as B. General knowledge is permitted but must be labelled as
not coming from the company's records, so a reader can always tell which
half of an answer is a company fact.

Measured before the instruction existed: *"What is the capital of
France"* returned `context_used: true` with four citations from Acme HR
documents. That is the failure this instruction exists to prevent.

### D. No documents exist yet

`ApprovedContext` is empty and case B's empty state renders. The Ask Arc
page also shows what Arc can currently search in a side rail, so an
empty corpus is visible before a question is asked rather than after.

### E. Retrieval is weak or ambiguous

Governed by `MIN_RELEVANCE_SCORE`. Below the floor, items are dropped
and the answer degrades to case B. Lexical-only matches are deliberately
**not** floored, because `ts_rank` is not comparable to cosine
similarity - so with a real embedding provider the floor governs the
dense arm, and lexical precision governs the other.

### F. Another tenant's information

Enforced in the backend, not the UI. The tenant comes from the trusted
context and never from the request; the SQL is tenant-scoped; every
returned match is re-validated against the trusted tenant and an
invariant violation fails closed.

Verified: an Acme administrator requesting Nova's knowledge receives
403, and an employee opening another tenant's workspace is told they are
not a member - the message deliberately does not distinguish "not a
member" from "does not exist".

### G. Citations

The API returns citation references of the form `<document-id>#<chunk>`.
The frontend resolves these to document titles, which is what a reader
sees ("IT service guide", "Employee handbook").

Consequence worth knowing: an API consumer that does **not** also fetch
the knowledge list sees opaque identifiers. Only the frontend currently
resolves them.

## 4. Permissions

| Capability | Permission |
|---|---|
| Ask a question | `knowledge:read` in that tenant |
| Add a document | `knowledge:create` |
| Edit a document | `knowledge:update` |

A platform administrator holds these globally but is not a member of any
customer tenant (V2-ADR-003) and receives 403 on tenant-scoped knowledge
routes. Platform administration does not read customer knowledge.

## 5. Testing it objectively

`demo/knowledge/EXPECTED_ANSWERS.md` is the verification set: 18
questions with known answers and the document each must be cited from,
4 negative cases that must not produce a confident company answer, and 1
cross-tenant case that must return nothing.

An answer is correct only if it states the fact **and** cites the right
document. Textually right with the wrong citation is a retrieval
failure.

Observed ranking with the deterministic embedding provider is recorded
in that file: the correct document ranked first for five of six
questions and third for the pricing question. That is a baseline proving
the pipeline works end to end - **not** a measurement of retrieval
quality with a real embedding model.

## 6. Known limitations

| Limitation | Nature |
|---|---|
| Deterministic provider returns a machine-shaped string, not prose | Configuration - needs a real `LLM_PROVIDER` |
| Ranking is effectively lexical | Configuration - needs a real `EMBEDDING_PROVIDER` |
| Refusal behaviour unexercised in dev | Follows from the above; the instruction is tested, the behaviour is not |
| Citations are opaque outside the frontend | Product gap |
| Text ingestion only | Issue #299 - PDF, DOCX and OCR not implemented |
