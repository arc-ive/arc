# ARC CI architecture

This describes what ARC's CI actually does and why each part exists. The
image lifecycle and the build-once invariant are in
[IMAGE_LIFECYCLE.md](IMAGE_LIFECYCLE.md); this is the wider picture.

## The pipeline

```
Developer
   |
   v
Pull Request
   |
   +-- lint ------------------- Ruff check + format, CI-contract tests   (~10s)
   +-- frontend --------------- oxlint, 426 vitest tests, vite build     (~45s)
   |
   +-- build-test-image ------- ONE build -> GHCR digest                 (~1m)
   |        |
   |        +-- test shard 1/4 ---+
   |        +-- test shard 2/4    |  ~3000 pytest tests, duration-split,
   |        +-- test shard 3/4    |  each shard its own PostgreSQL
   |        +-- test shard 4/4 ---+
   |        +-- production-config -- APP_ENV=production boundary         (~50s)
   |        +-- schema-bootstrap ---- fresh-DB provisioning              (~45s)
   |
   +-- build-production-image -- ONE build -> GHCR digest                (~20s)
            |
            +-- e2e ------------- Playwright against the shipped image   (~1m30s)
   |
   v
Required checks  (see "Repository settings" — NOT currently enforced)
   |
   v
main
   |
   +-- security workflow ------- dependency audit, image scan
   |
   v
Immutable production image at ghcr.io/arc-ive/arc@sha256:...
   (promotion is manual; ARC has no deployment target yet)
```

Separately: **Security** (dependency + image scanning, weekly and on main)
and **RAG eval (real embeddings)** (`workflow_dispatch` only, needs a paid
API key).

## Why this shape

**Build once, test many.** Four shards previously each ran their own Docker
build. A shared cache made that cheap, but four builds are four artifacts
that happen to agree, not one artifact under test. Now each image is built
exactly once and every consumer proves by digest that it received that
artifact. Measured effect: summed runner time fell from 2403s to 1710s
(−29%), wall clock rose 538s → 554s (+3%) because the build jobs are now on
the critical path. That trade is deliberate — see
[IMAGE_LIFECYCLE.md](IMAGE_LIFECYCLE.md).

**Consumers can't build.** Not by convention — `docker-compose.ci.yml`
strips the build context (`build: !reset null`) and forbids pulling
(`pull_policy: never`), and `tests/test_ci_architecture.py` fails the build
if a consumer job declares a build step or skips the override.

**Fast feedback first.** `lint` and `frontend` do not wait for an image, so
a formatting mistake fails in ~10s rather than after a 24-minute suite.

## Test layers

| Layer | Where | What it protects |
|---|---|---|
| Static | `lint` | formatting, lint, and the CI contract itself |
| Frontend unit | `frontend` | 426 vitest tests, build integrity |
| Backend suite | `test` ×4 | ~3000 tests against real PostgreSQL — RBAC, tenant isolation, PII, RAG, approvals, connectors, webhooks, agent/skill execution |
| Config boundary | `production-config` | that `APP_ENV=production` really removes dev auth routes and sets Secure cookies |
| Schema | `schema-bootstrap` | that `schema.sql` provisions a genuinely empty database and is idempotent |
| E2E | `e2e` | Playwright against the **production** image, real flows |
| Supply chain | `security` | dependency CVEs, container CVEs |

The backend suite is not split by "unit vs integration" because ARC's tests
are deliberately integration-first: they run against real PostgreSQL rather
than mocks, which is what makes tenant-isolation and RBAC assertions worth
anything. Splitting them by speed would mean mocking the boundary the tests
exist to verify.

**Sharding is duration-aware.** `.test_durations` ships in the test image
(it did not, before — pytest-split was silently falling back to count-based
splitting). Per-shard totals went from 202.8/140.9/89.6/205.2s to
190.4/141.1/153.4/153.7s: slowest shard 205.2s → 190.4s, spread 115.5s →
49.3s.

## What ARC deliberately does NOT have

Listed because their absence is a decision, not an oversight.

- **No migration-upgrade tests.** ARC has no migration tool. `schema.sql` is
  applied idempotently at startup (`CREATE TABLE IF NOT EXISTS`, `ALTER
  TABLE ... ADD COLUMN IF NOT EXISTS`). `schema-bootstrap` covers the
  fresh-database case, which is the case that exists. Inventing migration
  tests would mean inventing a migration framework first.
- **No API contract snapshot.** `tests/test_api_surface.py` already asserts
  the public route surface and the production OpenAPI document, including
  that dev-only endpoints stay absent. A schema snapshot would duplicate it
  with worse failure messages.
- **No deployment job.** ARC has no deployment target: no Kubernetes, no
  Terraform, no cloud manifests, no deployed environment. A deploy job would
  be speculative architecture. The production image is built, tested and
  published by digest, which is the part that can be done honestly today.
- **No `latest` tag.** Deployment identity is a digest. A mutable tag is not
  an identity.
- **No self-hosted runners, no second registry, no external CI service.**
  GitHub Actions + Buildx + GHCR covers every requirement here; nothing in
  ARC's current shape justifies the operational burden of more.
- **No secret-scanning workflow.** GitHub provides push protection natively.
  Reimplementing it in a workflow would be strictly worse — it would run
  after the secret is already in the history.

## Security model

**Same-repository PRs** run with the repository's token, publish to GHCR by
digest, and write the shared layer cache.

**Fork PRs** (not currently used; supported by design) run untrusted code
and receive no repository secrets, no package-write credentials, and no
cache-write access. Their image is handed off as an ephemeral Actions
artifact, verified by tarball SHA-256 and image ID. `pull_request_target` is
not used, and a test asserts it stays absent. Full detail in
[IMAGE_LIFECYCLE.md](IMAGE_LIFECYCLE.md).

**Supply chain.** Registry-mode builds attach SBOM and provenance
(`provenance: mode=max`, `sbom: true`), both buildx-native, so a published
image traces to its commit and workflow run from the registry alone.

**Dependency auditing** runs `pip-audit` against the resolved environment
(so transitive dependencies are covered) and `npm audit --audit-level=high`
on the frontend. The Python gate has an explicit exception list: anything
not on it fails the job. Current exceptions, both recorded with reasons in
`.github/workflows/security.yml`:

- `cryptography` 48.0.1 (3 advisories) — `presidio-anonymizer` pins
  `>=48.0.1,<49.0.0` and the fixes are 49.0.0/50.0.0. **This one matters**:
  cryptography sits in the connector-credential and approval-argument
  encryption path. Revisit the moment Presidio relaxes the pin.
- `pytest` 8.4.2 — dev-only, and verified absent from the production image.
  A direct payoff of the production/test image split: the vulnerable package
  is not in the runtime container at all.

**Container scanning** (Trivy) runs on main and weekly, never on PRs —
scanning requires an image, and building one in the security workflow would
be a second build of the same source. It scans the image CI already
published for that commit. It reports rather than gates, because an unfixed
base-image CVE is not something a merge can resolve and a gate nobody can
satisfy gets bypassed. Promote it to a gate once findings are triaged.

## Caching

| Cache | Scope | Notes |
|---|---|---|
| Docker layers | `type=gha`, scopes `arc-test` / `arc-prod` | The ~400 MB spaCy layer is keyed on `pyproject.toml`, so ordinary code changes restore it |
| pip | `setup-python` cache | lint and security jobs only |
| npm | `setup-node` cache, keyed on `frontend/package-lock.json` | frontend job |

Fork builds read the layer cache but never write it (`cache-from` without
`cache-to`), so untrusted code cannot poison what same-repository builds
consume.

**Cache is not identity.** A cache hit makes a build faster; it does not
make two builds the same artifact. The digest is the identity.

## Repository settings that CI cannot set itself

`main` has an active ruleset ("Protect main") enforcing deletion protection,
non-fast-forward protection, and 1 required approving review.

**It has no `required_status_checks` rule.** CI runs on every PR and blocks
nothing: a PR with one approval can merge with every check red. This is the
single highest-value change available and it needs repository admin:

```
Settings -> Rules -> Protect main -> add "Require status checks to pass"
```

Recommended required checks:

```
Lint & Format
Frontend (lint, test, build)
Test (shard 1/4)
Test (shard 2/4)
Test (shard 3/4)
Test (shard 4/4)
Production config boundary
Schema Bootstrap (fresh DB)
Playwright E2E (Phase 1-3)
```

Deliberately excluded from the required set: the Security workflow jobs.
They are path- and schedule-triggered, so requiring them would block every
PR that does not touch dependencies on a check that never runs.

Or via the API:

```bash
gh api -X PUT repos/arc-ive/arc/rulesets/<id> --input ruleset.json
```

**Merge queue**: not recommended yet. A merge queue earns its place when
concurrent merges collide often enough to cause broken-main incidents. ARC
merges a few PRs a day through a single review gate; a queue would add
latency and a second CI run per merge for a problem that is not yet
occurring. Revisit if main starts breaking from semantic conflicts between
independently-green PRs.

## Artifact lifecycle

```
commit SHA
   |
   v
build (once per target)
   |
   v
ghcr.io/arc-ive/arc-test:<sha>   ghcr.io/arc-ive/arc:<sha>
        + SBOM + provenance             + SBOM + provenance
   |                                |
   v                                v
digest-pinned consumers          e2e
   |                                |
   +--------------+-----------------+
                  |
                  v
        all checks green
                  |
                  v
   ghcr.io/arc-ive/arc@sha256:...  <- the artifact that passed
```

The image that passed validation is the image that would be promoted. There
is no rebuild between test and release, which is the point: rebuilding the
same source produces a different artifact, and the one you tested is not the
one you shipped.

Tag meanings:

| Tag form | Means |
|---|---|
| `ghcr.io/arc-ive/arc:<commit-sha>` | built from that commit; may or may not have passed |
| `ghcr.io/arc-ive/arc@sha256:<digest>` | one specific immutable artifact — the only form safe for deployment identity |
| `ghcr.io/arc-ive/arc-test:<commit-sha>` | test image, never deployed |

## Adding a check

Ask which layer it belongs to, and whether it must block a merge or is
better as a scheduled signal. A check that fails for reasons the author
cannot fix belongs on a schedule, not on the PR — a gate people learn to
ignore is worse than no gate.
