"""Server-side session management for Google OIDC authentication.

Session IDs are opaque, cryptographically random tokens stored in an
HttpOnly cookie. The session record maps the session to a user and
enforces expiry. No signing secret is needed: the session ID is a
random token looked up directly in the database.

Security properties:
- Session IDs are 256-bit cryptographically random tokens
- Sessions are stored server-side in PostgreSQL
- Session IDs are never exposed to JavaScript (HttpOnly cookie)
- CSRF tokens are cryptographically random and stored server-side
- CSRF tokens are returned to the client in a non-HttpOnly cookie
- Expired sessions are rejected on every request
- Logout invalidates the session in the database
- Multiple concurrent sessions are allowed (multi-device)
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from arc.db.connection import ArcDatabase, DatabaseError, NotFoundError
from arc.domain.models import Session, User

SESSION_COOKIE_NAME = "arc_session"
CSRF_COOKIE_NAME = "arc_csrf_token"
SESSION_ID_LENGTH = 32  # 256 bits
CSRF_TOKEN_LENGTH = 32  # 256 bits
DEFAULT_SESSION_EXPIRY_HOURS = 24


class SessionService:
    """Manages server-side sessions for authenticated users."""

    def __init__(self, db: ArcDatabase, expiry_hours: int = DEFAULT_SESSION_EXPIRY_HOURS):
        self._db = db
        self._expiry_hours = expiry_hours

    def generate_session_id(self) -> str:
        """Generate a cryptographically random session ID."""
        return secrets.token_urlsafe(SESSION_ID_LENGTH)

    def generate_csrf_token(self) -> str:
        """Generate a cryptographically random CSRF token."""
        return secrets.token_urlsafe(CSRF_TOKEN_LENGTH)

    async def create_session(
        self,
        user: User,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Session:
        """Create a new session for an authenticated user.

        Args:
            user: The authenticated user (must be active).
            user_agent: Optional user agent string for audit.
            ip_address: Optional IP address for audit.

        Returns:
            The created session with the opaque session ID.

        Raises:
            ValueError: If the user is not active.
        """
        if user.status != "active":
            raise ValueError("Cannot create session for inactive user")

        session_id = self.generate_session_id()
        csrf_token = self.generate_csrf_token()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=self._expiry_hours)

        session = Session(
            id=session_id,
            user_id=user.id,
            csrf_token=csrf_token,
            created_at=now,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        return await self._db.create_session(session)

    async def validate_session(self, session_id: str) -> Optional[User]:
        """Validate a session ID and return the associated user.

        Returns None if the session is invalid, expired, or the user
        is not found or inactive. Never raises exceptions.
        """
        try:
            session = await self._db.get_session(session_id)
            if session is None:
                return None

            # Double-check expiry (defense in depth)
            if session.is_expired:
                return None

            user = await self._db.get_user(session.user_id)
            if user is None or user.status != "active":
                return None

            return user
        except (DatabaseError, NotFoundError):
            return None

    async def get_session_csrf_token(self, session_id: str) -> Optional[str]:
        """Get the CSRF token for a session.

        Returns None if the session is invalid or expired.
        """
        try:
            session = await self._db.get_session(session_id)
            if session is None:
                return None
            if session.is_expired:
                return None
            return session.csrf_token
        except (DatabaseError, NotFoundError):
            return None

    async def validate_csrf_token(self, session_id: str, csrf_token: str) -> bool:
        """Validate a CSRF token against the session.

        Returns True if the token is valid, False otherwise.
        """
        stored_token = await self.get_session_csrf_token(session_id)
        if stored_token is None:
            return False
        # Constant-time comparison to prevent timing attacks
        return secrets.compare_digest(stored_token, csrf_token)

    async def invalidate_session(self, session_id: str) -> bool:
        """Delete a specific session (logout)."""
        return await self._db.delete_session(session_id)

    async def invalidate_all_sessions(self, user_id: str) -> int:
        """Delete all sessions for a user (logout everywhere)."""
        return await self._db.delete_sessions_for_user(user_id)
