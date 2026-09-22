"""Destructive-fixture safety guard for the test database (Issue #232).

The session fixture in ``tests/conftest.py`` drops the whole ``public``
schema, so collection itself refuses any ``DATABASE_URL`` that does not
name a disposable test database. These tests exercise the guard in
isolation and never connect anywhere, let alone drop anything.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import TEST_DATABASE_URL, UnsafeTestDatabaseError, require_test_database


def test_rejects_development_database():
    with pytest.raises(UnsafeTestDatabaseError, match="'arc'"):
        require_test_database("postgresql://arc:dev-secret@localhost:5432/arc")


def test_error_explains_how_to_run_and_leaks_no_password():
    with pytest.raises(UnsafeTestDatabaseError) as exc_info:
        require_test_database("postgresql://arc:super-secret-pw@localhost:5432/arc")
    message = str(exc_info.value)
    assert "arc_test" in message
    assert "DATABASE_URL" in message
    assert "super-secret-pw" not in message


def test_accepts_intended_test_database():
    assert require_test_database(TEST_DATABASE_URL) == "arc_test"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://arc:pw@localhost:5432/arc_test",
        "postgresql://arc:pw@127.0.0.1:5433/other_test",
        "postgresql://arc:pw@localhost:5432/arc_test?sslmode=require",
        # Percent-encoded credentials must not confuse name extraction.
        "postgresql://arc:p%40ss%2Fw@localhost:5432/arc_test",
    ],
)
def test_accepts_test_database_forms(url):
    assert require_test_database(url).endswith("_test")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://arc:pw@localhost:5432/production",
        "postgresql://arc:pw@localhost:5432/postgres",
        "postgresql://arc:pw@localhost:5432/arc_test_extra",
        "postgresql://arc:pw@localhost:5432/",
        "postgresql://arc:pw@localhost:5432",
        "mysql://arc:pw@localhost:5432/arc_test",
        "postgres://arc:pw@localhost:5432/arc_test",
        "not-a-url",
        "",
    ],
)
def test_rejects_unsafe_or_ambiguous_database(url):
    with pytest.raises(UnsafeTestDatabaseError):
        require_test_database(url)


def _run_collection(database_url: str) -> subprocess.CompletedProcess:
    """Collect one throwaway test file in a subprocess with the given URL.

    Collection imports ``tests/conftest.py``, so an unsafe URL must fail
    here — before any fixture (destructive or otherwise) can execute.
    """
    probe = Path("tests/test_tmp_guard_probe_232.py")
    probe.write_text("def test_probe():\n    pass\n")
    try:
        pythonpath = os.pathsep.join(part for part in (os.environ.get("PYTHONPATH"), "src") if part)
        env = {**os.environ, "DATABASE_URL": database_url, "PYTHONPATH": pythonpath}
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                str(probe),
            ],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
            env=env,
        )
    finally:
        probe.unlink(missing_ok=True)


def test_collection_refuses_unsafe_database_before_any_fixture():
    result = _run_collection("postgresql://arc:x@localhost:5432/arc")
    assert result.returncode != 0
    assert "arc_test" in result.stdout + result.stderr


def test_collection_accepts_intended_test_database():
    result = _run_collection(TEST_DATABASE_URL)
    assert result.returncode == 0
