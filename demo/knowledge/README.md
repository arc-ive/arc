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

## Formats

Markdown is the **source of truth**. The PDF and Word files are
generated from it by `demo/build_formats.py`, so the facts cannot drift:
change a figure in the Markdown, regenerate, and every format agrees and
`EXPECTED_ANSWERS.md` stays valid for all of them.

| File | Format | Exercises |
|---|---|---|
| `leave-policy.docx` | Word | Tables — entitlements live in them |
| `product-catalogue.docx` | Word | Pricing tables |
| `it-security-policy.pdf` | PDF | Multi-page prose with a text layer |
| `benefits.pdf` | PDF | Prose and figures |

Regenerate with:

```bash
python demo/build_formats.py
```

**Images are deliberately absent.** Arc refuses them, because OCR is not
configured and storing an image would create a document with nothing
readable in it. A fixture Arc cannot ingest would be demo material
pretending to be a capability.

## Fictional company

**Acme Technologies** — a mid-sized IT services company. It is the
existing reference tenant (`ref-acme-technologies`), so these documents
load into the environment `scripts/dev_reset.py` already creates.

## Loading

```bash
# The Markdown set, through the JSON create endpoint.
python demo/load_knowledge.py --tenant ref-acme-technologies \
  --user ref-acme-technologies-company-admin

# OR the PDF/Word set, through the upload endpoint, which exercises
# extraction.
python demo/load_knowledge.py --tenant ref-acme-technologies \
  --user ref-acme-technologies-company-admin --formats
```

**Load one set or the other, not both.** They carry the same facts, so
loading both puts every answer in the corpus twice and splits retrieval
between two copies of the same document — which makes ranking look worse
than it is for a reason that has nothing to do with Arc.

The loader goes through the real HTTP API with a real session, so it
exercises authentication, tenant context, authorization, chunking,
embedding and indexing exactly as a human would. It does not write to
the database directly.
