# Arc — Synthetic Demo Knowledge Pack

**Every document in this directory is synthetic. The company, people,
products, customers and figures are invented. Nothing here describes a
real organisation or a real person.**

## Purpose

These documents exist so Ask Arc can be demonstrated and, more
importantly, **verified**. Each one contains specific, checkable facts,
and `EXPECTED_ANSWERS.md` records the question, the answer, and the
document the answer must be cited from.

That makes retrieval objectively testable: an answer is correct only if
it states the known fact *and* cites the document that contains it.

## Format

Markdown and plain text only, deliberately.

Arc's ingestion path today accepts text (`POST
/tenants/{id}/knowledge`). PDF, DOCX and image/OCR ingestion is issue
 #299 and is **not implemented**, so shipping PDFs here would be demo
material that cannot actually be ingested. When #299 lands, the same
documents should be added in those formats and this note removed.

## Fictional company

**Acme Technologies** — a mid-sized IT services company. It is the
existing reference tenant (`ref-acme-technologies`), so these documents
load into the environment `scripts/dev_reset.py` already creates.

## Loading

```bash
python demo/load_knowledge.py --tenant ref-acme-technologies \
  --user ref-acme-technologies-company-admin
```

The loader goes through the real HTTP API with a real session, so it
exercises authentication, tenant context, authorization, chunking,
embedding and indexing exactly as a human would. It does not write to
the database directly.
