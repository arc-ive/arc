# The spaCy model behind PII detection

## Decision

**ARC ships `en_core_web_lg` and keeps it.** `PII_SPACY_MODEL` makes the
choice configurable, but the default does not change.

This was investigated as an image-size optimisation — `en_core_web_lg` is the
single largest thing in the container — and rejected on measured evidence.

## Why the small model looked safe

Of the eight categories in `DEFAULT_ENABLED_CATEGORIES`, only **PERSON**
consults the spaCy model:

| Category | Recogniser | Needs the model? |
|---|---|---|
| `PERSON` | spaCy NER | **yes** |
| `EMAIL_ADDRESS` | pattern | no |
| `PHONE_NUMBER` | pattern | no |
| `CREDIT_CARD` | pattern + Luhn checksum | no |
| `IBAN_CODE` | pattern + checksum | no |
| `IP_ADDRESS` | pattern | no |
| `US_SSN` | pattern + context (ARC's own recogniser) | no |
| `CREDENTIAL` | ARC regex patterns | no |

Nothing in `pii.py` reads word vectors or `.similarity()`, and word vectors
are the main capability `lg` adds over `sm`. On that reasoning the small model
should have been a free 430 MB.

And the whole PII suite — 94 tests — passes on both models.

## Why it was rejected anyway

The suite passing proves less than it appears: only 8 of those 94 tests
mention PERSON at all, and they use simple Anglo names. Measuring PERSON
recall directly over a matrix of 10 names × 8 sentence contexts (80 cases):

| Model | PERSON recall | Disk |
|---|---|---|
| `en_core_web_lg` | **79/80 — 98.8%** | 445.1 MB |
| `en_core_web_sm` | 77/80 — 96.2% | 15.2 MB |

The three regressions are the same name — *Priya Raghunathan* — in three
different contexts, each one caught by `lg`:

```
Escalate to Priya Raghunathan on the SRE rota.
cc Priya Raghunathan on the incident channel
Owner: Priya Raghunathan
```

Two things make this disqualifying rather than marginal:

1. **A PERSON miss is not a cosmetic degradation.** PII Guard runs at the
   ingestion boundary. A name it fails to detect is written into
   `knowledge_chunks`, embedded into a vector, and later assembled into an LLM
   prompt — in plaintext. That is the precise outcome this service exists to
   prevent, and the failure is silent.

2. **The degradation is not uniformly distributed.** The losses cluster on a
   non-Anglo name, in short and label-style contexts. A smaller model does not
   get uniformly worse; it gets worse first on the inputs that were already
   hardest, which here means non-Western names. Shipping that as an image-size
   optimisation would mean a PII guard that protects some employees measurably
   less well than others.

430 MB does not buy either of those.

`lg` is not perfect — it missed one case (`Escalate to Aisha Abdullah on the
SRE rota.`), which is worth knowing. But it is strictly better on this matrix,
and the question here is relative, not absolute.

## What did change

`AnalyzerEngine` was previously constructed with no explicit `nlp_engine`, so
Presidio fell back to its own default provider, which hardcodes
`en_core_web_lg`. The model was effectively unconfigurable and undocumented.

It is now built through an explicit `NlpEngineProvider` reading
`PII_SPACY_MODEL`. Passing the engine explicitly is what makes the variable
take effect — without it the env var would be read and silently ignored, which
is worse than offering no knob at all.

## Reproducing the measurement

```bash
# both models must be installed
uv pip install --python .venv-demo/bin/python \
  "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"

ARC_COMPARE_SPACY_MODELS=1 \
DATABASE_URL=postgresql://postgres@localhost:5432/arc_test \
.venv-demo/bin/pytest -q tests/test_pii_spacy_model.py
```

`tests/test_pii_spacy_model.py` pins three things:

- the default is `en_core_web_lg` (changing it is a security decision);
- PERSON recall on the default clears a 97.5% floor;
- `en_core_web_sm` is still measurably worse (opt-in, needs both models).

The third test fails if a future spaCy release closes the gap — at which point
the 430 MB is worth revisiting, with fresh numbers rather than this document's.

## If you want the small model anyway

A deployment whose corpus genuinely does not contain personal names, or which
has measured recall on its own data and accepted the trade-off, can set:

```
PII_SPACY_MODEL=en_core_web_sm
```

Measure first, on your own corpus, using the matrix in
`tests/test_pii_spacy_model.py` as the shape. Do not adopt this document's
numbers as a substitute for that — they are from a synthetic 80-case matrix,
not from your data.
