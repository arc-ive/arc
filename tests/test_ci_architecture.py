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
