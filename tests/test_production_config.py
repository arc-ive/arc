"""The production configuration boundary, exercised against the real app.

Two things change when ``APP_ENV`` is not ``development``:

1. ``src/arc/main.py`` stops mounting ``dev_router`` and ``dev_auth_router``.
   Those routes sign a caller in as any seeded user with no credentials, so
   their absence in production is a security boundary, not a convenience.
2. Session, CSRF and OIDC cookies are marked ``Secure`` so browsers only send
   them over HTTPS.

The mounting decision in ``main.py`` is a module-level ``if`` evaluated once at
import time, which is why it cannot be re-checked by patching the environment
inside an already-imported test process.  The existing tests in
``test_dev_auth.py`` worked around this by building a throwaway ``FastAPI()``
and re-implementing the guard expression in the test body — which passes
whether or not ``main.py`` is correct, because it never imports ``main.py``.

These tests import the real module in a subprocess with the environment set,
so what is asserted is the behaviour of the shipped gate.  CI additionally
runs this file with a production-like ``APP_ENV`` (see the
``production-config`` job), because the rest of the suite runs with
``APP_ENV=development`` and would otherwise never evaluate it.
"""

import json
import os
import subprocess
import sys

import pytest

DEV_ROUTE_PREFIX = "/internal/dev"

# Emitted by the probe below; kept as a module constant so a failure message
# can show what the shipped application actually exposed.
_PROBE = (
    "import json, arc.main; "
    "print('<<<' + json.dumps(sorted(arc.main.app.openapi()['paths'])) + '>>>')"
)


def _paths_for(app_env):
    """Import the real ``arc.main`` with ``APP_ENV`` set and return its paths.

    ``app_env`` of ``None`` means the variable is removed entirely, which is
    the fail-closed case an unconfigured deployment hits.
    """
    env = {k: v for k, v in os.environ.items() if k != "APP_ENV"}
    if app_env is not None:
        env["APP_ENV"] = app_env

    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"importing arc.main with APP_ENV={app_env!r} failed:\n{result.stderr[-2000:]}"
        )
    start = result.stdout.index("<<<") + 3
    end = result.stdout.index(">>>")
    return json.loads(result.stdout[start:end])


def _dev_routes(paths):
    return [p for p in paths if p.startswith(DEV_ROUTE_PREFIX)]


class TestDevRoutesAreDevelopmentOnly:
    """The real ``main.py`` gate, not a re-implementation of it."""

    def test_development_mounts_dev_routes(self):
        """Baseline: the routes exist at all, so their absence below is meaningful.

        Without this, every assertion in this class would also pass if the
        dev routers had been deleted outright.
        """
        dev = _dev_routes(_paths_for("development"))
        assert dev, "expected dev routes to be mounted when APP_ENV=development"
        assert f"{DEV_ROUTE_PREFIX}/auth/login" in dev

    @pytest.mark.parametrize("app_env", ["production", "staging", "prod", "test", ""])
    def test_non_development_mounts_no_dev_routes(self, app_env):
        """Only the exact string 'development' may expose them."""
        dev = _dev_routes(_paths_for(app_env))
        assert dev == [], f"APP_ENV={app_env!r} exposed development routes: {dev}"

    def test_unset_app_env_mounts_no_dev_routes(self):
        """Fail closed: an unconfigured deployment must not expose them."""
        dev = _dev_routes(_paths_for(None))
        assert dev == [], f"unset APP_ENV exposed development routes: {dev}"

    def test_application_routes_are_otherwise_unchanged(self):
        """The gate removes only the development routes, nothing else."""
        development = set(_paths_for("development"))
        production = set(_paths_for("production"))

        assert production < development, "production should expose a strict subset"
        assert development - production == set(_dev_routes(sorted(development)))
        assert not _dev_routes(sorted(production))


class TestCookieSecureBoundary:
    """Cookies are Secure everywhere except an explicit development run.

    ``test_cookie_secure.py`` already covers the helper and each call site in
    depth.  This asserts the same boundary through the imported module so the
    production-config CI job fails if either half of the boundary regresses.
    """

    @pytest.mark.parametrize(
        "app_env,expected",
        [("development", False), ("production", True), ("staging", True), ("", True)],
    )
    def test_cookie_secure_follows_app_env(self, app_env, expected):
        os.environ["APP_ENV"] = app_env
        try:
            from arc.api.auth_routes import _cookie_secure

            assert _cookie_secure() is expected
        finally:
            os.environ.pop("APP_ENV", None)

    def test_cookie_secure_when_app_env_unset(self):
        saved = os.environ.pop("APP_ENV", None)
        try:
            from arc.api.auth_routes import _cookie_secure

            assert _cookie_secure() is True
        finally:
            if saved is not None:
                os.environ["APP_ENV"] = saved
