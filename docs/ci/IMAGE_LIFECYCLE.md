# CI image lifecycle: build once, test many

## The invariant

> **A consumer job must never build an ARC image.**
> Consumers receive only immutable artifacts produced by a dedicated build
> job, and prove what they received before using it.

```
BUILD ONCE  ->  IMMUTABLE ARTIFACT  ->  CONSUME MANY  ->  TEST
```

This is not a style preference. Before it, four test shards each ran their
own Docker build. A shared layer cache made those builds cheap, but cheap is
not the same as identical: four builds are four artifacts that happen to
agree, not one artifact under test. If a shard ever diverged — a cache miss
resolving a floating dependency differently, a partial cache, a registry
hiccup — the suite would report green on an image nobody shipped.

## Who builds, who consumes

| Job | Role | Builds |
|---|---|---|
| `build-test-image` | producer | **1** |
| `build-production-image` | producer | **1** |
| `test` (×4 shards) | consumer | 0 |
| `production-config` | consumer | 0 |
| `schema-bootstrap` | consumer | 0 |
| `e2e` | consumer | 0 |

`lint` and `frontend` touch no ARC image and are not consumers.

## Same-repository PRs and pushes

```
build-test-image                    build-production-image
   | build once                        | build once
   | push to GHCR                      | push to GHCR
   v                                   v
ghcr.io/arc-ive/arc-test@sha256:…   ghcr.io/arc-ive/arc@sha256:…
   |                                   |
   +-- test shard 1                    +-- Playwright E2E
   +-- test shard 2
   +-- test shard 3
   +-- test shard 4
   +-- production-config
   +-- schema-bootstrap
```

Consumers receive a **digest**, never a tag. A tag can be repointed between
jobs; a digest names exactly one manifest and cannot be. Immutability is
intrinsic here rather than asserted — though each consumer asserts it
anyway, so the logs show which artifact was tested.

## Fork PRs

A fork PR runs untrusted code with a read-only token and no secrets. It
cannot publish to ARC's package namespace, and must not be given the chance.

The answer is **not** to let fork jobs build their own images — that would
break the invariant in exactly the place it matters least to break it and
most to notice. Instead the same single build happens, and the artifact
travels by a different road:

```
build-test-image                    build-production-image
   | build once (no push)              | build once (no push)
   | docker save                       | docker save
   | upload-artifact                   | upload-artifact
   v                                   v
arc-test-image (ephemeral)          arc-production-image (ephemeral)
   |                                   |
   +-- test shard 1                    +-- Playwright E2E
   +-- test shard 2                        (download, verify, load)
   +-- test shard 3
   +-- test shard 4
   +-- production-config
   +-- schema-bootstrap
```

Still one build per target. Still every consumer testing that one artifact.

Mode is decided once, in the build job, by comparing the PR's head
repository against this repository, and published as a job output. Consumers
key off that output rather than re-deriving the condition, so the two cannot
drift apart.

## Artifact identity

A tag is mutable, so the fork path cannot rely on naming alone. Identity is
established twice, and the order matters:

1. **Tarball SHA-256, checked before `docker load`.** Proves the bytes that
   arrived are the bytes that were exported. Verified first so unverified
   content never enters the daemon at all.
2. **Image ID after load.** `docker save`/`docker load` preserves the image
   ID, because the ID is the SHA-256 of the image config blob. This proves
   the loaded image is the one that was built — not merely a well-formed
   image wearing the same tag.

Both were verified empirically before adoption, not assumed:

```
before save: sha256:2bc57a80af72afa20bea298456e5ea90ac444a074f9d3399cd6b8e207051c7e9
after  load: sha256:2bc57a80af72afa20bea298456e5ea90ac444a074f9d3399cd6b8e207051c7e9
```

Flipping one byte at offset 1000000 changes the checksum, so the gate rejects
a tampered or truncated artifact before load.

For the registry path the mechanism is the digest itself, compared against
the producing job's output.

## How consumers are *structurally* prevented from building

Documentation and review do not hold an invariant under deadline pressure.
Three layers do:

**1. No build context.** `docker-compose.ci.yml` is applied as an override
on every CI compose invocation:

```yaml
services:
  arc:
    build: !reset null
    image: ${ARC_IMAGE:-arc-image-not-pinned-for-this-job}
    pull_policy: never
```

`build: !reset null` *removes* the build section inherited from
`docker-compose.yml`. A consumer cannot fall back to building because there
is nothing left to build from. `pull_policy: never` stops it reaching a
registry. So the only image it can run is the one the job acquired and
verified. Missing image, missing variable, wrong digest — all fail closed:

```
Error response from daemon: No such image: arc-image-not-pinned-for-this-job:latest
```

The placeholder defaults are load-bearing. Compose interpolates the whole
file regardless of which service a command selects, so a strict `:?` guard
broke every test shard (they legitimately pin only `ARC_TEST_IMAGE`). The
defaults resolve to references that cannot exist in any registry, which
keeps the failure mode while letting interpolation succeed.

**2. One sanctioned acquisition path.** `.github/actions/acquire-arc-image`
is the only way a consumer obtains an image. It handles both modes and
performs the identity check, so a new consumer gets the guarantee by using
it — and a reviewer can see at a glance whether a job did.

**3. Tests that fail the build.** `tests/test_ci_architecture.py` parses the
workflow and the compose override and asserts the invariant: consumers
declare no build step, every compose call uses the override, both
`!reset`/`pull_policy` lines are present, build steps are mutually exclusive
by mode, the fork path never pushes or writes cache, consumers request no
write permissions, and the checksum is verified before load.

Reintroducing a build in a consumer job turns CI red with a message pointing
here.

## Security model for fork PRs

Fork PR code is untrusted. It receives:

- **No repository secrets.** GitHub does not pass secrets to workflows
  triggered by `pull_request` from a fork. Nothing in this workflow depends
  on one outside the registry path.
- **No package-write credentials.** The workflow token is read-only for
  forks. The push step is additionally gated on registry mode, so a push is
  never even attempted with fork code in the tree.
- **No cache-write access.** The fork build passes `cache-from` but not
  `cache-to`, so untrusted code cannot poison the layer cache that
  same-repository builds read from.
- **No ability to publish into ARC's namespace.** By both of the above.

`packages: write` remains declared on the build jobs for the
same-repository push. For a fork PR GitHub issues a read-only token
regardless of what the workflow requests, so this cannot grant untrusted
code write access.

**`pull_request_target` is not used, deliberately.** It runs with the base
repository's write-scoped token. Combining it with a checkout of fork code
is the standard way to hand repository credentials to an attacker, and using
it merely to obtain write permissions would trade the entire security model
for a registry push nobody needs. A test asserts it stays absent.

## Current policy

ARC does not currently depend on external fork contributors. The fork path
exists so that accepting them later is a configuration question rather than
a CI redesign — and so the build-once guarantee is not quietly weakened at
the moment someone needs fork CI working by the end of the day.

Because no fork PR exists against this repository, the fork path has been
validated statically and by local simulation, not by a live fork run. See
the PR discussion for exactly what was and was not executed.

## Local development is unaffected

Plain `docker compose` keeps both build targets and its local tags:

```bash
docker compose up -d                                   # builds arc (production)
docker compose --profile test build arc-test           # builds arc-test
```

The CI override applies only when passed explicitly with `-f`. A test
asserts the base compose file still carries both build targets, so a future
tightening of CI cannot quietly break local workflow.

## Adding a new consumer job

1. `needs:` the relevant build job.
2. Acquire via `./.github/actions/acquire-arc-image`, passing the build
   job's outputs.
3. Run compose with `-f docker-compose.yml -f docker-compose.ci.yml`.
4. Add the job to `CONSUMERS` in `tests/test_ci_architecture.py`.

Step 4 is deliberate friction: it is the moment someone states that a new
job consumes an ARC image, and from then on the tests hold it to the
invariant.
