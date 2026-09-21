"""Connection pool sizing is configurable via the environment (Issue #187).

asyncpg defaults to a fixed 10/10 pool, which caps concurrency under load and
cannot be tuned without a code change. These tests pin the configuration
contract: the defaults, the environment overrides, and the failure modes for a
bound that cannot be honoured.

They assert on the values the manager will hand to asyncpg rather than opening
a pool, so they need no database.
"""

import pytest

from arc.db.connection import (
    DEFAULT_POOL_MAX,
    DEFAULT_POOL_MIN,
    ArcDatabase,
    DatabaseError,
)


class TestDefaults:
    def test_defaults_apply_when_unset(self, monkeypatch):
        monkeypatch.delenv("DB_POOL_MIN", raising=False)
        monkeypatch.delenv("DB_POOL_MAX", raising=False)
        db = ArcDatabase()
        assert (db.pool_min, db.pool_max) == (DEFAULT_POOL_MIN, DEFAULT_POOL_MAX)

    def test_default_max_exceeds_asyncpg_default(self):
        """The point of the change: a higher ceiling than asyncpg's fixed 10."""
        assert DEFAULT_POOL_MAX > 10
        assert DEFAULT_POOL_MIN >= 1

    def test_empty_value_falls_back_to_default(self, monkeypatch):
        """An unset variable in a .env file arrives as an empty string."""
        monkeypatch.setenv("DB_POOL_MIN", "")
        monkeypatch.setenv("DB_POOL_MAX", "")
        db = ArcDatabase()
        assert (db.pool_min, db.pool_max) == (DEFAULT_POOL_MIN, DEFAULT_POOL_MAX)


class TestEnvironmentOverrides:
    def test_environment_values_are_used(self, monkeypatch):
        monkeypatch.setenv("DB_POOL_MIN", "5")
        monkeypatch.setenv("DB_POOL_MAX", "50")
        db = ArcDatabase()
        assert (db.pool_min, db.pool_max) == (5, 50)

    def test_explicit_arguments_win_over_environment(self, monkeypatch):
        monkeypatch.setenv("DB_POOL_MIN", "5")
        monkeypatch.setenv("DB_POOL_MAX", "50")
        db = ArcDatabase(pool_min=1, pool_max=3)
        assert (db.pool_min, db.pool_max) == (1, 3)

    def test_equal_bounds_are_allowed(self, monkeypatch):
        monkeypatch.setenv("DB_POOL_MIN", "7")
        monkeypatch.setenv("DB_POOL_MAX", "7")
        assert ArcDatabase().pool_min == 7


class TestInvalidConfigurationIsRejected:
    """A bad bound is reported here, not as an opaque asyncpg error later."""

    @pytest.mark.parametrize("value", ["abc", "3.5", "ten"])
    def test_non_integer_is_rejected(self, monkeypatch, value):
        monkeypatch.setenv("DB_POOL_MAX", value)
        with pytest.raises(DatabaseError, match="DB_POOL_MAX"):
            ArcDatabase()

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_non_positive_is_rejected(self, monkeypatch, value):
        monkeypatch.setenv("DB_POOL_MIN", value)
        with pytest.raises(DatabaseError, match="DB_POOL_MIN"):
            ArcDatabase()

    def test_min_above_max_is_rejected(self, monkeypatch):
        monkeypatch.setenv("DB_POOL_MIN", "30")
        monkeypatch.setenv("DB_POOL_MAX", "10")
        with pytest.raises(DatabaseError, match="cannot exceed"):
            ArcDatabase()


class TestPoolIsCreatedWithTheConfiguredBounds:
    async def test_connect_passes_bounds_to_asyncpg(self, monkeypatch):
        """The configured values must actually reach create_pool."""
        captured = {}

        async def fake_create_pool(dsn, **kwargs):
            captured.update(dsn=dsn, **kwargs)
            return object()

        monkeypatch.setattr("arc.db.connection.asyncpg.create_pool", fake_create_pool)
        db = ArcDatabase("postgresql://example/db", pool_min=4, pool_max=9)
        await db.connect()

        assert captured["min_size"] == 4
        assert captured["max_size"] == 9
        assert captured["dsn"] == "postgresql://example/db"
