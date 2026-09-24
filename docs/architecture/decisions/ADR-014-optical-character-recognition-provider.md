# ADR-014: Optical Character Recognition — A Local Engine, Off By Default

## Status

Accepted

## Date

2026-09-24

## Decision Owners

- Platform engineering

## Context

Issue #299 asked for multi-format ingestion: PDF, DOCX and OCR alongside
plain text. PDF, DOCX and text shipped. OCR did not, and the reason was
recorded in `pyproject.toml` at the time:

> Image OCR is deliberately NOT here. It needs either a Tesseract binary
> — which is not pip-installable as a working install across platforms —
> or a cloud provider, and choosing where tenant documents get sent for
> OCR is an infrastructure and data-residency decision rather than a
> dependency choice.

That is still the right diagnosis. The blocker was never a missing
library. It was one question:

**Where does a customer's document go to be read?**

A scanned document is often the most sensitive thing a customer uploads —
a signed contract, an invoice, a medical form, a photographed ID. Sending
it to a hosted OCR API means tenant content leaves the deployment. For
some customers that is disqualifying whatever the accuracy, and Arc has
no per-tenant processor configuration to make it a per-customer choice.

Meanwhile the refusal was costing something real. `document_extraction`
refused images with a message naming OCR, and refused scanned PDFs for
having no text layer. Both are honest, and both mean a customer's archive
of scans is invisible to Company Brain — which for many organisations is
where the institutional knowledge actually lives.

The original plan was to spike first: measure what share of real customer
documents are image-only before choosing. That measurement is worth
having, and this decision does not replace it. But the sequencing was
backwards: the spike's purpose was to justify taking on a residency risk,
and there is an option that takes on no residency risk at all.

## Decision

**OCR ships as a local engine, behind an optional dependency, off by
default.**

1. **The engine is local.** `TesseractOcrProvider` shells out to a
   Tesseract binary running inside the deployment. A scanned contract is
   read on the same machine that stored it. Enabling OCR therefore adds
   **no new destination for tenant content**, and is not also a residency
   decision — which is precisely the decision this ADR declines to make
   on a customer's behalf.
2. **It is off unless configured.** `OCR_PROVIDER` defaults to `none`. A
   deployment that does not opt in behaves exactly as it did before,
   refusal message and all. Nobody silently gains OCR on upgrade, and no
   existing refusal changes meaning.
3. **It is an optional dependency**, the `ocr` extra. `pytesseract` is a
   thin wrapper that shells out to a binary pip cannot install, so as a
   base dependency it would make a broken install look like a working
   one. A provider that is configured but cannot run raises at
   **startup**, not on a user's upload an hour later.
4. **`OcrProvider` is a protocol, not a library.** A hosted or regional
   engine can be added later as a deliberate, documented residency
   decision, without touching extraction. The protocol is the seam where
   that decision will be visible.
5. **The text layer always wins.** OCR is a fallback for documents with
   no text, never a second opinion on documents that have some.
   Re-reading a real text layer would replace exact characters with
   guessed ones.
6. **Scanned PDFs are read through their embedded images**, using the PDF
   reader Arc already depends on rather than adding a rasteriser. For a
   scan each page *is* one embedded image, which is the case this exists
   for. A vector-only PDF with no text layer has no image to read and is
   refused like any other unreadable file — stated, not hidden.
7. **Machine-read text says so.** `ExtractedDocument` carries `ocr_used`
   and the provider name, and the upload response reports both. OCR text
   and a document's own text layer retrieve and cite identically, so if
   the distinction does not travel with the result it is lost at the
   moment the document is stored.

Bounds, because recognition is CPU-bound and roughly linear in pages: at
most 20 images per document (`OCR_MAX_PAGES`), a per-image timeout
(`OCR_TIMEOUT_SECONDS`, default 30s), embedded images below 200px on
their short side skipped as decoration, and the whole extraction moved
off the event loop into a threadpool.

## Options Considered

### Option 1 — A hosted OCR API (AWS Textract, Google Document AI, Azure)

Description: send the image to a managed service and store what comes
back.

Advantages:

- The best accuracy available, by a wide margin, on exactly the inputs
  that are hardest: photographs, skewed scans, handwriting, tables.
- No binary to install, no per-host setup, scales without capacity work.
- Structure extraction (tables, key-value pairs) far beyond plain text.

Disadvantages:

- **Tenant documents leave the deployment.** This is the whole blocker.
  It is a compliance posture Arc would be choosing for every customer,
  and the most sensitive uploads are exactly the ones that need OCR.
- Residency becomes a per-tenant configuration problem Arc has no model
  for: no per-tenant processor settings, no per-tenant regional routing,
  no per-tenant data-processing agreements.
- A second place tenant content lives, with its own retention policy to
  read, audit and defend.
- Per-page cost on a path a user can trigger by uploading, with no
  spend control in Arc today.

### Option 2 — Local Tesseract (chosen)

Description: as recorded under Decision.

Advantages:

- **No residency decision.** Nothing crosses a boundary that did not
  already exist, so the option is available to every customer including
  the ones a hosted API disqualifies.
- No per-page cost and no new vendor relationship.
- Apache-2.0, invoked as a separate process — suitable for commercial
  multi-tenant use with no linking question.
- Off by default, so it changes nothing for a deployment that does not
  ask for it.

Disadvantages:

- **Worse accuracy**, and worst exactly where it matters most: a
  photographed invoice at an angle, a low-contrast fax, handwriting. The
  honest framing is worse text in exchange for no new place for tenant
  documents to be.
- Requires a system binary, so it cannot be a base dependency and
  operators have one more install step.
- CPU-bound and slow: seconds per page, which is why it is bounded and
  runs off the event loop.
- No structure extraction — plain text only, so a table becomes prose.

### Option 3 — Keep refusing, and run the spike first

Description: leave the honest refusal in place; measure what share of
real customer documents are image-only before choosing anything.

Advantages:

- Zero new code, zero new dependency, zero risk.
- The measurement is genuinely useful and would tell us whether accuracy
  is worth paying for.

Disadvantages:

- It gates a capability on a study whose purpose was to justify a
  residency risk that Option 2 does not take. The spike answers "is the
  cloud engine worth it", not "should OCR exist".
- The refusal keeps a real customer archive invisible in the meantime,
  and "we are measuring" is not an answer a customer can use.
- The measurement is better taken WITH a local engine deployed: real
  usage on real corpora is stronger evidence than a sample survey, and
  it tells us whether local accuracy is actually sufficient — which is
  the fact that decides Option 1 versus Option 2.

### Option 4 — A self-hosted modern OCR model (PaddleOCR, docTR, TrOCR)

Description: run a neural OCR model in-process or as a sidecar.

Advantages:

- Accuracy much closer to a hosted API while still local.
- No system binary; installable as Python wheels.

Disadvantages:

- Model weights are hundreds of megabytes to gigabytes, on top of the
  `en_core_web_lg` download Arc already carries. Image size and cold
  start both get materially worse.
- Practically wants a GPU for acceptable latency, which is an
  infrastructure requirement, not a dependency.
- Licences need checking per model and per weight set, and some research
  checkpoints are non-commercial — the kind of thing that is easy to miss
  and expensive to discover later.
- It is the right upgrade *later*, behind the same `OcrProvider`
  protocol, once there is evidence that local accuracy is the binding
  constraint.

## Rationale

The recorded blocker was residency, and Option 2 is the option that has
no residency consequence. That is the whole argument: a local engine can
be enabled by any customer, including the ones for whom Option 1 is not
discussable, so shipping it first maximises who can use OCR at all.

Accuracy is the price, and it is stated plainly rather than papered over.
A deployment that needs better accuracy and can accept a processor has a
clear upgrade path, and the `OcrProvider` protocol is where that decision
will be made explicitly rather than inherited from this one.

Option 3 — the original spike-first plan — was reconsidered rather than
ignored. Its logic was sound when the only alternatives took on residency
risk. It is weaker against an option that takes none, and the measurement
it proposed is better taken with a local engine actually deployed: real
usage tells us both how many image-only documents exist AND whether local
accuracy suffices, which is the pair of facts that decides whether to add
Option 1 or Option 4 later.

"Off by default" is what makes this reversible. If the local engine turns
out to be too inaccurate to be useful, nothing has to be undone: the
deployments that did not enable it never changed, and the ones that did
can turn it off in one environment variable.

## Consequences

### Positive

- A customer's archive of scanned documents can enter Company Brain, and
  for many organisations that is where the institutional knowledge is.
- No tenant document leaves the deployment for OCR, so the capability is
  available to every customer rather than the ones with a permissive
  posture.
- The refusal message stops being permanent while remaining accurate for
  deployments that do not opt in.
- `ocr_used` makes machine-read text distinguishable from a document's
  own text, which matters for anyone judging a citation.

### Negative

- Accuracy on hard inputs is materially worse than a hosted API's, and
  the worst cases are common real ones.
- Operators gain an install step (a binary plus language packs) and a new
  CPU cost on the upload path.
- Tables and layout are lost; OCR output is plain text.
- One more configuration surface, and one more way for a deployment to be
  half-configured — mitigated by failing at startup.

### Risks

- **OCR silently producing garbage that then gets indexed and cited.**
  Mitigated by the minimum-extracted-characters rule (a document that
  reads as nothing is refused, not stored), by skipping decoration-sized
  images, and by reporting `ocr_used` so a reader can weigh the text. Not
  fully mitigated: plausible-looking wrong text is the failure mode OCR
  has, and no amount of validation catches it.
- **A worker occupied by a long scan.** Mitigated by the image bound, the
  per-image timeout, and moving extraction off the event loop.
- **Someone enabling a hosted provider later without re-deciding
  residency**, since the protocol makes it easy. Mitigated by this ADR
  being the thing a new provider has to supersede, and by the protocol
  docstring saying so.
- **The byte-size trap.** The first implementation filtered embedded
  images by byte length; pypdf re-encodes when it hands an image over, so
  that measured the compressor, not the content — a clean scan of a
  sparse page can encode smaller than a busy logo. Filtering is by pixel
  dimensions instead.

## Security Considerations

- **No new trust boundary.** OCR runs in-process against bytes that were
  already accepted, under the same `knowledge:create` permission, the
  same trusted tenant context, the same upload size cap and the same PII
  sanitization. The upload endpoint gains no new authorization path.
- **No new destination for tenant content**, which is the point.
- **OCR output is untrusted text**, exactly like the text layer of an
  uploaded PDF, and goes through the identical ingestion path. It is
  never interpreted as instructions; it is document content.
- **Subprocess boundary.** `pytesseract` invokes the binary with the
  image on a temporary file and no shell interpolation of user data. The
  image is decoded by Pillow first, so malformed input fails as an
  unreadable image rather than reaching the engine.
- **Denial of service.** An image is a file and the existing 20MB cap
  applies before any recognition; the image count and per-image timeout
  bound the work after that.
- **Fail closed.** A configured provider that cannot run raises at
  startup. An unknown `OCR_PROVIDER` value raises rather than silently
  falling back to "no OCR", because falling back would hide an operator
  typo that leaves a promised capability missing.

## Operational Considerations

- Install: `pip install "arc[ocr]"` plus the binary
  (`apt-get install tesseract-ocr`, or `brew install tesseract`), then
  `OCR_PROVIDER=tesseract`. Language packs beyond English are separate
  OS packages named in `OCR_LANGUAGES`.
- Configuration: `OCR_PROVIDER` (default `none`), `OCR_LANGUAGES`
  (default `eng`), `OCR_MAX_PAGES` (default 20), `OCR_TIMEOUT_SECONDS`
  (default 30). Invalid numeric values log a warning and fall back rather
  than failing a deployment.
- No schema change, no migration, no new secret.
- Capacity: recognition is CPU-bound, so a deployment enabling OCR should
  expect upload latency in seconds per page and size workers accordingly.
  Extraction runs in a threadpool so it does not stall other requests.
- Monitoring: `ocr_enabled` at startup names the engine and bounds;
  `ocr_image_failed` and `ocr_image_limit_reached` cover the two
  degradations that lose content. Neither logs document content.

## Testing / Validation

- Every pre-OCR test still passes unchanged, which is the evidence that
  "off by default" really means unchanged: images are still refused with
  a message naming OCR, and scanned PDFs are still refused for having no
  text layer.
- The opt-in path is covered at the extraction layer and over HTTP
  through the running application, with a real PNG and a hand-built
  scanned PDF. The recogniser is the only stand-in; every decision Arc
  makes around it is real code.
- Specific invariants: an image becomes a retrievable document; a scanned
  PDF is read through its page image; a PDF that has a text layer is
  never re-read by OCR; the image count is bounded and a short scan is
  read in full; an image that reads as nothing is still refused; an
  engine failure never becomes a stored empty document; OCR relaxes
  neither the size limit nor authorization; the response distinguishes
  machine-read text from a text layer.
- Configuration: off unless set, every off-spelling honoured, an unknown
  provider refused, a configured-but-unavailable engine refused at build
  time, and invalid bounds falling back rather than crashing.
- The three OCR invariants were verified load-bearing by removing each
  and confirming the relevant tests fail. The text-layer-preference test
  initially did NOT fail, because its fixture had no embedded image to
  read instead; the fixture now carries both a text layer and a page
  image, and the test fails without the preference.

## Related Documents

- `docs/capabilities/ASK_ARC.md` — ingestion and retrieval behaviour
- ADR-003 — Company Brain document identity and re-ingestion
- ADR-013 — external actions (the other decision where a third party
  would have meant tenant content leaving the deployment)

## Related Work

- Linear:
- GitHub: #299

## Supersedes

## Superseded By
