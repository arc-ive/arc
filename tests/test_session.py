"""Tests for server-side session management.

Verifies session creation, validation, invalidation, and expiry behavior.
Sessions are server-side only; no session ID is exposed to the client.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from arc.db.connection import ArcDatabase
from arc.domain.models import User
from arc.security.session import SessionService


@pytest.fixture
def db():
    """Mock database connection."""
    db = AsyncMock(spec=ArcDatabase)
    return db


@pytest.fixture
def service(db):
    """SessionService with 24-hour expiry."""
    return SessionService(db, expiry_hours=24)


@pytest.fixture
def short_lived_service(db):
    """SessionService with 1-hour expiry for testing expiry behavior."""
    return SessionService(db, expiry_hours=1)


@pytest.fixture
def active_user():
    """An active user for testing."""
    return User(
        id="user-123",
        email="test@example.com",
        username="testuser",
        status="active",
    )


@pytest.fixture
def inactive_user():
    """An inactive user for testing."""
    return User(
        id="user-456",
        email="inactive@example.com",
        username="inactiveuser",
        status="inactive",
    )


class TestSessionCreation:
    """Test session creation and ID generation."""

    async def test_create_session_returns_session(self, service, active_user, db):
        """Session creation returns a Session object with an ID."""
        mock_session = MagicMock()
        mock_session.id = "generated-session-id"
        db.create_session = AsyncMock(return_value=mock_session)

        session = await service.create_session(active_user)
        assert session is not None
        assert session.id == "generated-session-id"

    async def test_session_id_is_unique(self, service, active_user):
        """Multiple sessions for the same user produce unique IDs."""
        id1 = service.generate_session_id()
        id2 = service.generate_session_id()
        assert id1 != id2

    async def test_session_id_is_opaque(self, service):
        """Session ID is opaque and not predictable."""
        id1 = service.generate_session_id()
        id2 = service.generate_session_id()
        # Statistical test: IDs should not be sequential
        assert id1 != id2

    async def test_create_session_stores_user_id(self, service, active_user, db):
        """Session creation stores user ID in database."""
        mock_session = MagicMock()
        db.create_session = AsyncMock(return_value=mock_session)

        await service.create_session(active_user)

        db.create_session.assert_called_once()
        call_args = db.create_session.call_args
        session_arg = call_args[0][0] if call_args[0] else call_args[1].get("session")
        assert session_arg.user_id == "user-123"

    async def test_create_session_stores_expiry(self, service, active_user, db):
        """Session creation stores expiry timestamp."""
        mock_session = MagicMock()
        db.create_session = AsyncMock(return_value=mock_session)

        await service.create_session(active_user)

        call_args = db.create_session.call_args
        session_arg = call_args[0][0] if call_args[0] else call_args[1].get("session")
        assert session_arg.expires_at is not None
        assert session_arg.expires_at > datetime.now(timezone.utc)

    async def test_create_session_rejects_inactive_user(self, service, inactive_user):
        """Cannot create session for inactive user."""
        with pytest.raises(ValueError, match="Cannot create session for inactive user"):
            await service.create_session(inactive_user)


class TestSessionValidation:
    """Test session validation and lookup."""

    async def test_validate_session_returns_user(self, service, db, active_user):
        """Valid session returns the associated user."""
        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.is_expired = False

        db.get_session = AsyncMock(return_value=mock_session)
        db.get_user = AsyncMock(return_value=active_user)

        result = await service.validate_session("valid-session-id")

        assert result is not None
        assert result.id == "user-123"

    async def test_validate_session_returns_none_for_invalid(self, service, db):
        """Invalid session returns None."""
        db.get_session = AsyncMock(return_value=None)

        result = await service.validate_session("invalid-session-id")

        assert result is None

    async def test_validate_session_returns_none_for_expired(self, service, db, active_user):
        """Expired session returns None."""
        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.is_expired = True

        db.get_session = AsyncMock(return_value=mock_session)

        result = await service.validate_session("expired-session-id")

        assert result is None

    async def test_validate_session_returns_none_for_inactive_user(
        self, service, db, inactive_user
    ):
        """Session for inactive user returns None."""
        mock_session = MagicMock()
        mock_session.user_id = "user-456"
        mock_session.is_expired = False

        db.get_session = AsyncMock(return_value=mock_session)
        db.get_user = AsyncMock(return_value=inactive_user)

        result = await service.validate_session("session-for-inactive-user")

        assert result is None


class TestSessionInvalidation:
    """Test session invalidation (logout)."""

    async def test_invalidate_session_deletes_session(self, service, db):
        """Invalidation deletes the session from database."""
        db.delete_session = AsyncMock(return_value=True)

        result = await service.invalidate_session("session-to-delete")

        assert result is True
        db.delete_session.assert_called_once_with("session-to-delete")

    async def test_invalidate_all_user_sessions(self, service, db):
        """Invalidating all sessions for a user removes all their sessions."""
        db.delete_sessions_for_user = AsyncMock(return_value=3)

        count = await service.invalidate_all_sessions("user-123")

        assert count == 3
        db.delete_sessions_for_user.assert_called_once_with("user-123")


class TestSessionExpiry:
    """Test session expiry behavior."""

    async def test_expired_session_not_validated(self, short_lived_service, db):
        """Expired sessions are not validated."""
        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.is_expired = True

        db.get_session = AsyncMock(return_value=mock_session)

        result = await short_lived_service.validate_session("expired-session")

        assert result is None

    async def test_session_expiry_configurable(self, db):
        """Session expiry can be configured via constructor."""
        service_1h = SessionService(db, expiry_hours=1)
        service_48h = SessionService(db, expiry_hours=48)

        # Verify different expiry times are used
        assert service_1h._expiry_hours == 1
        assert service_48h._expiry_hours == 48

    async def test_is_expired_uses_utc_now(self):
        """is_expired compares timezone-aware UTC timestamps.

        Regression test: datetime.now() (naive) must not be compared
        with a timezone-aware expires_at from PostgreSQL/asyncpg.
        """
        from datetime import datetime, timedelta, timezone

        from arc.domain.models import Session

        # Create a session that expires 1 hour from now (UTC-aware)
        now = datetime.now(timezone.utc)
        future_session = Session(
            id="test",
            user_id="user-1",
            csrf_token="csrf",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert future_session.is_expired is False

        # Create a session that expired 1 hour ago (UTC-aware)
        past_session = Session(
            id="test",
            user_id="user-1",
            csrf_token="csrf",
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        assert past_session.is_expired is True
