"""The CI image contract, enforced rather than documented.

    BUILD ONCE -> IMMUTABLE ARTIFACT -> CONSUME MANY -> TEST

The permanent invariant: **a consumer job must never build an ARC image.**

A comment cannot hold that line. The pressure to break it is specific and
predictable — a job fails because an image is missing, and the one-line fix
is to add a build step "just for this job". That is how four shards end up
testing four artifacts that merely agree, which is what PR #338's review
caught. These tests fail the build instead.

Structural defences, in order of strength:

1. ``docker-compose.ci.yml`` strips the build context with
   ``build: !reset null`` and sets ``pull_policy: never``. A consumer
   cannot build because there is nothing to build from, and cannot pull
   because it is forbidden to. Nothing in the YAML can override that.
2. Consumer jobs declare no build action, only the shared acquire action.
3. These tests assert both, so reintroducing a build is a red build.

Deliberately parses the YAML rather than trusting the workflow to be
well-behaved: the question is what CI *would* do, not what it is meant to.
"""

import os
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
CI_WORKFLOW = WORKFLOW_DIR / "ci.yml"
CI_COMPOSE = REPO_ROOT / "docker-compose.ci.yml"
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
ACQUIRE_ACTION = REPO_ROOT / ".github" / "actions" / "acquire-arc-image" / "action.yml"
SCAN_ACTION = REPO_ROOT / ".github" / "actions" / "scan-arc-image" / "action.yml"

# These tests analyse repository configuration, not application behaviour, so
# they need the checkout rather than the application image. The test image
# deliberately ships only src/, tests/ and scripts/ — .github/ is not in it,
# and putting it there would couple the image to CI config and force a
# rebuild on every workflow edit.
#
# So: skip when the files are not reachable (inside the container), and run
# for real in the `lint` job, which has the checkout. A silent skip would be
# a way for the invariant to stop being enforced without anyone noticing, so
# the job that is supposed to run them sets ARC_REQUIRE_CI_ARCHITECTURE_TESTS
# and the skip becomes a hard failure instead.
_WORKFLOW_AVAILABLE = CI_WORKFLOW.is_file() and ACQUIRE_ACTION.is_file()

if not _WORKFLOW_AVAILABLE and os.getenv("ARC_REQUIRE_CI_ARCHITECTURE_TESTS"):
    raise RuntimeError(
        "ARC_REQUIRE_CI_ARCHITECTURE_TESTS is set but the workflow files are "
        f"not readable from {REPO_ROOT}. The CI contract would go unchecked. "
        "Run these from a repository checkout, not from inside the test image."
    )

pytestmark = pytest.mark.skipif(
    not _WORKFLOW_AVAILABLE,
    reason=(
        "CI configuration is not present (running inside the test image, which "
        "ships no .github/). Enforced in the lint job, which has the checkout."
    ),
)

# Jobs that consume an ARC image. Adding a consumer means adding it here;
# that is the intended friction.
TEST_IMAGE_CONSUMERS = {"test", "production-config", "schema-bootstrap"}
PRODUCTION_IMAGE_CONSUMERS = {"e2e"}
CONSUMERS = TEST_IMAGE_CONSUMERS | PRODUCTION_IMAGE_CONSUMERS

BUILD_JOBS = {"build-test-image", "build-production-image"}

# Patterns that mean "this step builds an image".
#
# Anchored with word boundaries on purpose. A bare "docker build" substring
# also matches "docker buildx imagetools", which copies a manifest between
# registry tags and builds nothing — the release-promotion path. A detector
# that cries wolf gets loosened, and a loosened detector stops catching the
# thing it exists for.
BUILD_COMMAND_PATTERNS = (
    r"docker\s+build\s",
    r"docker\s+buildx\s+build\b",
    r"docker\s+compose\s+build\b",
    r"compose\s+up\b[^\n]*--build\b",
    r"\bup\s+-d\b[^\n]*--build\b",
)


def _looks_like_a_build(run: str) -> bool:
    return any(re.search(pattern, run) for pattern in BUILD_COMMAND_PATTERNS)


def _load(path: Path):
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def ci():
    return _load(CI_WORKFLOW)


@pytest.fixture(scope="module")
def jobs(ci):
    return ci["jobs"]


# Module-scoped: the repository-wide invariants and the container-scan
# ordering tests both walk every workflow, and they must walk the same set.
@pytest.fixture(scope="module")
def workflows():
    found = {}
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        found[path.name] = _load(path)
    assert found, "no workflows found; these tests would pass vacuously"
    return found


def _steps(job):
    return job.get("steps", []) or []


def _uses(step):
    return str(step.get("uses", "") or "")


def _run(step):
    return str(step.get("run", "") or "")


def _build_steps(job):
    """Steps that build an image, by action or by shell command."""
    found = []
    for step in _steps(job):
        if "build-push-action" in _uses(step):
            found.append(step.get("name", "<unnamed>"))
            continue
        if _looks_like_a_build(_run(step)):
            found.append(step.get("name", "<unnamed>"))
    return found


class TestConsumersNeverBuild:
    """The invariant itself."""

    @pytest.mark.parametrize("job_name", sorted(CONSUMERS))
    def test_consumer_declares_no_build_step(self, jobs, job_name):
        builds = _build_steps(jobs[job_name])
        assert builds == [], (
            f"consumer job {job_name!r} declares build step(s) {builds}. "
            "Consumer jobs must never build an ARC image — they consume the "
            "artifact a dedicated build job produced. See "
            "docs/ci/IMAGE_LIFECYCLE.md."
        )

    @pytest.mark.parametrize("job_name", sorted(CONSUMERS))
    def test_consumer_acquires_through_the_shared_action(self, jobs, job_name):
        """One sanctioned entry point, so the identity check cannot be skipped."""
        uses = [_uses(s) for s in _steps(jobs[job_name])]
        acquires = [u for u in uses if "acquire-arc-image" in u]
        assert len(acquires) == 1, (
            f"{job_name!r} must acquire its image through "
            f"./.github/actions/acquire-arc-image exactly once, found {acquires}"
        )

    @pytest.mark.parametrize("job_name", sorted(CONSUMERS))
    def test_consumer_depends_on_a_build_job(self, jobs, job_name):
        needs = jobs[job_name].get("needs")
        needs = [needs] if isinstance(needs, str) else list(needs or [])
        assert set(needs) & BUILD_JOBS, (
            f"{job_name!r} consumes an ARC image but does not depend on a "
            f"build job (needs={needs}); it would race the artifact it tests"
        )

    def test_every_compose_invocation_in_ci_uses_the_override(self, ci):
        """The override is what removes the build context. Skipping it re-arms the gun."""
        offenders = []
        for job_name, job in ci["jobs"].items():
            for step in _steps(job):
                run = _run(step)
                if "docker compose" not in run:
                    continue
                if "docker-compose.ci.yml" not in run:
                    offenders.append((job_name, step.get("name", "<unnamed>")))
        assert offenders == [], (
            "these CI steps run docker compose without docker-compose.ci.yml, "
            f"so the build context is still present: {offenders}"
        )


class TestBuildJobsBuildExactlyOnce:
    """Build once — per mode, not per step count."""

    @pytest.mark.parametrize("job_name", sorted(BUILD_JOBS))
    def test_build_steps_are_mutually_exclusive_by_mode(self, jobs, job_name):
        """Two build steps exist (registry and artifact); only one can run.

        Counting raw steps would read as "builds twice". What matters is how
        many can execute in a single run: each is gated on the acquisition
        mode, and the modes are exclusive, so exactly one does.
        """
        build_steps = [s for s in _steps(jobs[job_name]) if "build-push-action" in _uses(s)]
        assert len(build_steps) == 2, (
            f"{job_name!r} should declare exactly two build steps "
            f"(registry push + artifact export), found {len(build_steps)}"
        )
        conditions = [str(s.get("if", "")) for s in build_steps]
        assert all("steps.mode.outputs.mode" in c for c in conditions), (
            f"{job_name!r} build steps must each be gated on the acquisition "
            f"mode so only one can run; conditions were {conditions}"
        )
        registry = [c for c in conditions if "'registry'" in c]
        artifact = [c for c in conditions if "'artifact'" in c]
        assert len(registry) == 1 and len(artifact) == 1, (
            f"{job_name!r} must have exactly one registry-mode and one "
            f"artifact-mode build step; got {conditions}"
        )

    @pytest.mark.parametrize("job_name", sorted(BUILD_JOBS))
    def test_build_job_publishes_an_identity(self, jobs, job_name):
        outputs = jobs[job_name].get("outputs", {})
        for required in ("mode", "digest", "image", "image-id", "tarball-sha256"):
            assert required in outputs, (
                f"{job_name!r} must output {required!r} so consumers can verify "
                f"what they received; outputs were {sorted(outputs)}"
            )

    def test_exactly_one_build_job_per_target(self, jobs):
        targets = {}
        for name, job in jobs.items():
            for step in _steps(job):
                if "build-push-action" not in _uses(step):
                    continue
                target = (step.get("with") or {}).get("target")
                targets.setdefault(target, set()).add(name)
        assert targets.get("test") == {"build-test-image"}, targets
        assert targets.get("production") == {"build-production-image"}, targets


class TestComposeCannotBuild:
    """Missing image must fail closed, never fall back to a build."""

    def test_ci_override_removes_the_build_context(self):
        raw = CI_COMPOSE.read_text()
        for service in ("arc", "arc-test"):
            assert re.search(rf"^  {service}:", raw, re.M), f"{service} missing"
        # `!reset` is a compose tag PyYAML will not parse, so assert on text —
        # but only on real mapping lines. Counting bare substrings would also
        # match the prose above, which is how a test starts passing because
        # someone wrote the right words in a comment.
        resets = re.findall(r"^    build: !reset null$", raw, re.M)
        assert len(resets) == 2, (
            "both arc and arc-test must reset their build section; without it "
            f"compose can still build when an image is missing (found {len(resets)})"
        )
        nevers = re.findall(r"^    pull_policy: never$", raw, re.M)
        assert len(nevers) == 2, (
            "both services must set pull_policy: never so the image can only "
            f"be the one the job acquired and verified (found {len(nevers)})"
        )

    def test_unpinned_service_resolves_to_an_unusable_reference(self):
        """An unset variable must not become a blank or a real tag."""
        raw = CI_COMPOSE.read_text()
        assert "arc-image-not-pinned-for-this-job" in raw
        assert "arc-test-image-not-pinned-for-this-job" in raw

    def test_local_development_keeps_its_build_targets(self):
        """The override must not leak into ordinary local use."""
        base = _load(BASE_COMPOSE)
        for service, target in (("arc", "production"), ("arc-test", "test")):
            build = base["services"][service].get("build")
            assert build and build.get("target") == target, (
                f"local docker compose must still build {service} ({target}); "
                "developers rely on it and the CI override is opt-in"
            )


class TestForkPathSecurity:
    """Fork PRs run untrusted code: no secrets, no package writes."""

    def test_fork_path_does_not_use_pull_request_target(self, ci):
        triggers = ci.get(True, ci.get("on"))
        assert "pull_request_target" not in triggers, (
            "pull_request_target runs with repository write scope; combining "
            "it with a checkout of fork code is the standard way to leak "
            "credentials to untrusted code"
        )

    def test_fork_build_does_not_push_or_write_cache(self, jobs):
        """A fork must not publish into ARC's namespace or poison the cache."""
        for job_name in BUILD_JOBS:
            steps = [s for s in _steps(jobs[job_name]) if "build-push-action" in _uses(s)]
            artifact_steps = [s for s in steps if "'artifact'" in str(s.get("if", ""))]
            assert artifact_steps, f"{job_name} has no artifact-mode build"
            for step in artifact_steps:
                with_ = step.get("with") or {}
                assert not with_.get("push"), (
                    f"{job_name} artifact-mode build must not push: a fork has "
                    "no write access and must never gain any"
                )
                assert "cache-to" not in with_, (
                    f"{job_name} artifact-mode build must not write the shared "
                    "layer cache; untrusted code could poison what "
                    "same-repository builds read"
                )

    def test_registry_login_is_gated_on_registry_mode(self, jobs):
        for job_name in sorted(CONSUMERS | BUILD_JOBS):
            for step in _steps(jobs[job_name]):
                if "login-action" not in _uses(step):
                    continue
                condition = str(step.get("if", ""))
                assert "registry" in condition, (
                    f"{job_name!r} attempts a registry login without gating on "
                    f"registry mode (if: {condition!r})"
                )

    def test_consumers_request_no_write_permissions(self, jobs):
        for job_name in sorted(CONSUMERS):
            perms = jobs[job_name].get("permissions", {})
            assert perms.get("packages") in (None, "read"), (
                f"consumer {job_name!r} requests packages={perms.get('packages')!r}; "
                "consumers only ever read"
            )
            assert perms.get("contents") in (None, "read"), job_name


class TestArtifactIdentityIsVerified:
    """Both acquisition modes must prove what they received."""

    @pytest.fixture(scope="class")
    def action(self):
        return _load(ACQUIRE_ACTION)

    def test_action_never_builds(self, action):
        for step in action["runs"]["steps"]:
            assert not _looks_like_a_build(_run(step)), (
                f"the acquire action must never build: {step.get('name')}"
            )
            assert "build-push-action" not in _uses(step)

    def test_registry_mode_verifies_the_digest(self, action):
        body = "\n".join(_run(s) for s in action["runs"]["steps"])
        assert "expected-digest" in ACQUIRE_ACTION.read_text()
        assert "RepoDigests" in body, "registry mode must compare repo digests"

    def test_artifact_mode_verifies_checksum_and_image_id(self, action):
        names = [s.get("name", "") for s in action["runs"]["steps"]]
        assert any("checksum" in n.lower() for n in names), (
            "artifact mode must verify the tarball checksum before loading"
        )
        assert any("loaded image identity" in n.lower() for n in names), (
            "artifact mode must verify the loaded image id after loading"
        )
        body = "\n".join(_run(s) for s in action["runs"]["steps"])
        assert "sha256sum" in body
        assert "{{.Id}}" in body

    def test_checksum_is_verified_before_load(self, action):
        """Order matters: never admit unverified bytes into the daemon."""
        names = [s.get("name", "").lower() for s in action["runs"]["steps"]]
        checksum_at = next(i for i, n in enumerate(names) if "checksum" in n)
        load_at = next(i for i, n in enumerate(names) if n == "load the image")
        assert checksum_at < load_at, (
            "the tarball checksum must be verified before docker load, not after"
        )

    def test_unknown_mode_is_rejected(self, action):
        body = "\n".join(_run(s) for s in action["runs"]["steps"])
        assert "unknown acquisition mode" in body, (
            "an unrecognised mode must fail closed rather than silently "
            "acquiring nothing and letting compose decide what to run"
        )


class TestInvariantHoldsAcrossEveryWorkflow:
    """The invariant is repository-wide, not a property of ci.yml.

    The earlier tests in this module all read ci.yml. That was the gap: a
    build added to security.yml, promote.yml, or any workflow added later
    would satisfy every assertion above while breaking the guarantee. The
    scan below is deliberately unbounded — it walks whatever is in
    .github/workflows, so a new file is covered the moment it lands rather
    than when someone remembers to add it here.
    """

    def test_only_the_sanctioned_jobs_build_arc_images(self, workflows):
        """Exactly two jobs in the whole repository may build an ARC image."""
        builders = {}
        for filename, workflow in workflows.items():
            for job_name, job in (workflow.get("jobs") or {}).items():
                steps = job.get("steps", []) or []
                if any(
                    "build-push-action" in _uses(s) or _looks_like_a_build(_run(s)) for s in steps
                ):
                    builders[f"{filename}:{job_name}"] = job_name

        unexpected = {k: v for k, v in builders.items() if v not in BUILD_JOBS}
        assert unexpected == {}, (
            f"these jobs build an ARC image but are not the dedicated build "
            f"jobs: {sorted(unexpected)}. Building outside build-test-image / "
            "build-production-image produces a second artifact from the same "
            "source, which is what the build-once invariant exists to prevent. "
            "See docs/ci/IMAGE_LIFECYCLE.md."
        )
        assert set(builders.values()) == BUILD_JOBS, (
            f"expected exactly {sorted(BUILD_JOBS)} to build, found "
            f"{sorted(set(builders.values()))}"
        )

    def test_nothing_rebuilds_after_the_tested_artifact_exists(self, workflows):
        """Post-merge and release work must consume, never re-produce.

        A workflow that runs after CI — scanning, promoting, releasing —
        rebuilding from the same commit would produce a different image from
        the one that passed the tests. Rebuilding is not reproducing.
        """
        post_ci = {
            name: wf for name, wf in workflows.items() if name in {"promote.yml", "security.yml"}
        }
        assert post_ci, "expected the promote and security workflows to exist"
        for filename, workflow in post_ci.items():
            for job_name, job in (workflow.get("jobs") or {}).items():
                for step in job.get("steps", []) or []:
                    assert not _looks_like_a_build(_run(step)), (
                        f"{filename}:{job_name} step {step.get('name')!r} builds "
                        "an image after CI already produced and tested one"
                    )
                    assert "build-push-action" not in _uses(step), (
                        f"{filename}:{job_name} step {step.get('name')!r} uses a "
                        "build action; it should consume the published artifact"
                    )

    def test_promotion_moves_a_digest_rather_than_rebuilding(self, workflows):
        """Release promotion must be a retag of an already-tested manifest."""
        promote = workflows.get("promote.yml")
        assert promote, "promote.yml is missing"
        body = "\n".join(_run(s) for j in promote["jobs"].values() for s in (j.get("steps") or []))
        assert "imagetools create" in body, (
            "promotion must copy an existing manifest, not produce a new image"
        )
        assert "@${{ steps.source.outputs.digest }}" in body, (
            "promotion must reference the source image by DIGEST; a mutable tag "
            "could move between verification and copy"
        )

    def test_registry_builds_attach_provenance_and_sbom(self, workflows):
        """Published images must be traceable to their commit and run."""
        ci = workflows["ci.yml"]
        for job_name in BUILD_JOBS:
            pushes = [
                s
                for s in ci["jobs"][job_name]["steps"]
                if "build-push-action" in _uses(s) and (s.get("with") or {}).get("push")
            ]
            assert len(pushes) == 1, f"{job_name} should have one pushing build step"
            with_ = pushes[0]["with"]
            assert with_.get("provenance"), (
                f"{job_name} must attach provenance so a published image traces "
                "back to its commit and workflow run"
            )
            assert with_.get("sbom"), f"{job_name} must attach an SBOM"

    def test_security_scanning_reuses_the_published_image(self, workflows):
        """Scanning must not be an excuse to build a second artifact.

        The scanner now lives in a shared composite action, so this walks
        every workflow AND that action rather than assuming a Trivy step
        sits inline in security.yml.
        """
        scan_steps = [
            s
            for wf in list(workflows.values()) + [_load(SCAN_ACTION)]
            for j in (wf.get("jobs") or {"_": wf.get("runs", {})}).values()
            for s in (j.get("steps") or [])
            if "trivy" in _uses(s).lower()
        ]
        assert scan_steps, "expected a container scanning step"
        for step in scan_steps:
            ref = str((step.get("with") or {}).get("image-ref", ""))
            assert ref.startswith("ghcr.io/") or ref.startswith("${{ inputs."), (
                "the scanner must point at the image CI published, not a "
                f"locally built one (image-ref={ref!r})"
            )


class TestContainerScanConsumesTheBuiltArtifact:
    """The scan must run after — and against — the artifact CI published.

    This job used to sit in security.yml with no `needs:` at all. Push to
    main starts CI and Security as two independent workflow runs and nothing
    orders them, so the scan raced the build and lost: on 0452924 it failed
    at 13:15:52 looking for an image whose build started at 13:19:23.

    GitHub has no cross-workflow job dependency, so the per-commit scan has
    to live in the workflow that builds the image. These tests hold it there
    and hold it to a digest.
    """

    SCAN_JOB = "container-image-scan"
    SCAN_USES = "./.github/actions/scan-arc-image"

    @pytest.fixture(scope="class")
    def scan_action(self):
        return _load(SCAN_ACTION)

    @pytest.fixture(scope="class")
    def scan_job(self, jobs):
        assert self.SCAN_JOB in jobs, (
            f"{self.SCAN_JOB} must live in ci.yml: a `needs:` edge on the "
            "build job is the only ordering GitHub Actions provides, and it "
            "does not cross workflow boundaries"
        )
        return jobs[self.SCAN_JOB]

    def test_the_scan_waits_for_the_build_that_publishes_the_image(self, scan_job):
        needs = scan_job.get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        assert "build-production-image" in needs, (
            f"{self.SCAN_JOB} must declare needs: build-production-image. "
            "Without that edge it races the build and scans an image that "
            "does not exist yet."
        )

    def test_the_scan_uses_the_digest_the_build_job_published(self, jobs, scan_job):
        """Transitive: the ref must trace back to a digest, not a tag."""
        steps = [s for s in _steps(scan_job) if _uses(s) == self.SCAN_USES]
        assert len(steps) == 1, f"{self.SCAN_JOB} should scan exactly once"
        ref = str((steps[0].get("with") or {}).get("image-ref", ""))
        match = re.fullmatch(r"\$\{\{\s*needs\.([\w-]+)\.outputs\.([\w-]+)\s*\}\}", ref.strip())
        assert match, (
            f"{self.SCAN_JOB} must consume the producing job's output, not "
            f"re-derive a reference (image-ref={ref!r})"
        )
        producer, output = match.group(1), match.group(2)
        # Pinned to the production image specifically. `build-test-image`
        # also publishes a digest, so a generic "some producer" check would
        # accept a scan of the test image — which ships pytest and a
        # different dependency tree and is never deployed.
        assert producer == "build-production-image", (
            f"{self.SCAN_JOB} must scan the PRODUCTION image, not {producer!r}'s output"
        )
        needs = scan_job.get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        assert producer in needs, (
            f"{self.SCAN_JOB} references needs.{producer} without declaring "
            "it; the expression would resolve to an empty string"
        )
        published = str((jobs[producer].get("outputs") or {}).get(output, ""))
        assert "@" in published, (
            f"{producer}.outputs.{output} resolves to {published!r}, which is "
            "a mutable TAG. A tag can be repointed between publish and scan; "
            "every other image consumer in this repo takes a digest."
        )

    def test_the_scan_never_runs_on_a_pull_request(self, scan_job):
        condition = str(scan_job.get("if", ""))
        assert "pull_request" in condition, (
            f"{self.SCAN_JOB} must stay off pull_request: a fork build "
            "publishes nothing, so there would be no digest to scan"
        )
        assert "registry" in condition, (
            f"{self.SCAN_JOB} must be gated on registry mode as well, so the "
            "fork (artifact) path can never reach it"
        )

    def test_the_scan_requests_no_write_permissions(self, scan_job):
        for scope, level in (scan_job.get("permissions") or {}).items():
            assert level == "read", f"{self.SCAN_JOB} requests {scope}: {level}; scanning reads"

    def test_the_scheduled_rescan_is_not_triggered_by_push(self, workflows):
        """The racing path must not be able to come back.

        security.yml keeps the weekly rescan of the SHIPPED image — the only
        check that finds a CVE disclosed after a merge. It must not also run
        on push, which is where the race lived.
        """
        security = workflows["security.yml"]
        scanners = [
            (name, job)
            for name, job in security["jobs"].items()
            for s in (job.get("steps") or [])
            if _uses(s) == self.SCAN_USES
        ]
        assert scanners, "security.yml must keep the scheduled rescan"
        for name, job in scanners:
            condition = str(job.get("if", ""))
            assert "push" in condition and "pull_request" in condition, (
                f"security.yml:{name} must exclude push and pull_request "
                "(if: ...). On push it cannot order itself against the build "
                f"job in ci.yml and will race it. Got if={condition!r}"
            )

    def test_the_shared_action_refuses_a_tag(self, scan_action):
        body = "\n".join(_run(s) for s in scan_action["runs"]["steps"])
        assert "@sha256:" in body, (
            "scan-arc-image must reject a non-digest image-ref; that guard is "
            "what stops either caller reintroducing a mutable tag"
        )
        assert "exit 1" in body, "the digest guard must fail the job, not warn"

    def test_the_shared_action_stays_advisory(self, scan_action):
        trivy = [s for s in scan_action["runs"]["steps"] if "trivy" in _uses(s).lower()]
        assert len(trivy) == 1, "expected exactly one Trivy step"
        with_ = trivy[0]["with"]
        assert str(with_.get("exit-code")) == "0", (
            "the scan reports, it does not gate: an unfixable base-image CVE "
            "is not something a merge can resolve"
        )
        assert with_.get("severity") == "HIGH,CRITICAL"

    def test_no_workflow_pins_trivy_outside_the_shared_action(self, workflows):
        """One scanner definition, so the weekly path cannot drift."""
        for filename, workflow in workflows.items():
            for job_name, job in (workflow.get("jobs") or {}).items():
                for step in job.get("steps", []) or []:
                    assert "trivy" not in _uses(step).lower(), (
                        f"{filename}:{job_name} pins Trivy directly; use "
                        f"{self.SCAN_USES} so both callers stay in step"
                    )


class TestDependabotCoversEveryActionPin:
    """Every file that pins a third-party action must be watched.

    This exists because of a specific miss. Dependabot's github-actions
    ecosystem with ``directory: /`` searches .github/workflows and the ROOT
    action.yml — it does not descend into .github/actions. So
    ``actions/download-artifact`` sat pinned at v4 inside the acquire
    composite action, four majors behind upstream, while the workflows were
    being offered v7. Dependabot never proposed it once.

    That is not ordinary staleness: the download side is half of the
    fork-safe artifact handoff, and the half that verifies what arrived. An
    unwatched pin there is a security-relevant gap.

    The check is structural rather than a list of known files: it walks
    .github, finds everything that pins a third-party action, and asserts
    each one's directory is covered by a Dependabot entry. A new composite
    action is therefore covered the moment it lands, or the build fails.
    """

    DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

    @pytest.fixture(scope="class")
    def config(self):
        assert self.DEPENDABOT.is_file(), "dependabot.yml is missing"
        return _load(self.DEPENDABOT)

    @pytest.fixture(scope="class")
    def actions_dirs(self):
        """Directories holding a manifest that pins a third-party action.

        Local references (``./.github/actions/...``) are excluded: they are
        paths within this repository, not versioned dependencies.
        """
        found = set()
        for path in (REPO_ROOT / ".github").rglob("*.y*ml"):
            text = path.read_text()
            pins = [
                line for line in text.splitlines() if re.search(r"^\s*-?\s*uses:\s*[^./\s]", line)
            ]
            if pins:
                rel = path.parent.relative_to(REPO_ROOT)
                found.add("/" + str(rel))
        assert found, "no action pins found; this test would pass vacuously"
        return found

    def test_github_actions_ecosystem_uses_directories(self, config):
        entries = [u for u in config["updates"] if u["package-ecosystem"] == "github-actions"]
        assert entries, "no github-actions ecosystem entry"
        for entry in entries:
            assert "directories" in entry, (
                "the github-actions entry must use `directories` (plural). With a "
                "single `directory: /` Dependabot scans .github/workflows and the "
                "root action.yml only, and composite actions go unwatched."
            )

    def test_every_directory_with_action_pins_is_watched(self, config, actions_dirs):
        watched = set()
        for entry in config["updates"]:
            if entry["package-ecosystem"] != "github-actions":
                continue
            for directory in entry.get("directories", []) or [entry.get("directory")]:
                if directory:
                    watched.add(directory.rstrip("/") or "/")

        # `/` implicitly covers .github/workflows and the root manifest.
        implicitly_covered = {"/.github/workflows", "/"}

        unwatched = {
            d for d in actions_dirs if d.rstrip("/") not in watched and d not in implicitly_covered
        }
        assert unwatched == set(), (
            f"these directories pin third-party actions but no Dependabot entry "
            f"watches them: {sorted(unwatched)}. Add each to the `directories` "
            "list of the github-actions ecosystem in .github/dependabot.yml, or "
            "their pins will silently go stale."
        )

    def test_the_composite_action_is_explicitly_listed(self, config):
        """Regression guard for the exact gap that motivated this."""
        watched = {
            d
            for entry in config["updates"]
            if entry["package-ecosystem"] == "github-actions"
            for d in (entry.get("directories") or [])
        }
        assert "/.github/actions/acquire-arc-image" in watched, (
            "the acquire-arc-image composite action pins "
            "actions/download-artifact; it must be watched explicitly"
        )
