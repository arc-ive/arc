"""JWT signing and validation for X-11 authentication.

This module is an INTERNAL authentication concern. Application code and
downstream services must consume ``AuthenticatedPrincipal`` instead of
touching token internals.

Security properties:
- HS256 only (algorithm allow-list)
- required and validated ``sub``, ``exp``, ``iss``, ``aud`` claims
- tokens never carry roles, permissions, or tenant context
- tokens are never logged
- failures raise ``AuthenticationError`` with generic semantics
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from jwt import InvalidTokenError

from arc.security.settings import SecuritySettings

ALLOWED_ALGORITHMS = ["HS256"]


class AuthenticationError(Exception):
    """Raised when credentials are missing, malformed, or invalid.

    The message must remain generic; it is never exposed to clients.
    """


class JwtService:
    """Mint and validate HS256 JWTs for the simulated development environment."""

    def __init__(self, settings: SecuritySettings):
        self._settings = settings

    def create_access_token(
        self,
        subject: str,
        *,
        expires_in_seconds: Optional[int] = None,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
    ) -> str:
        """Create a signed access token for a subject.

        The token carries ONLY identity claims (sub/iss/aud/exp/iat). Roles,
        permissions, and tenant context are never embedded in the token; the
        server remains authoritative for authorization.
        """
        if not subject:
            raise ValueError("JWT subject cannot be empty")

        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "sub": subject,
            "iss": issuer or self._settings.jwt_issuer,
            "aud": audience or self._settings.jwt_audience,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in_seconds or self._settings.jwt_expiry_seconds),
        }
        return jwt.encode(
            payload, self._settings.jwt_secret, algorithm=self._settings.jwt_algorithm
        )

    def decode_access_token(self, token: str) -> str:
        """Validate a token and return the authenticated subject (user ID).

        Every validation requirement is enforced:
        - signature verified with the configured secret
        - algorithm restricted to the HS256 allow-list
        - ``exp`` required and validated
        - ``iss`` and ``aud`` required and validated
        - ``sub`` required and non-empty

        Raises:
            AuthenticationError: for any invalid token (generic semantics).
        """
        try:
            claims = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=ALLOWED_ALGORITHMS,
                issuer=self._settings.jwt_issuer,
                audience=self._settings.jwt_audience,
                options={
                    "require": ["sub", "exp", "iss", "aud"],
                    "verify_signature": True,
                },
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("Invalid authentication credentials") from exc

        subject = claims.get("sub")
        if not subject:
            raise AuthenticationError("Invalid authentication credentials")
        return str(subject)
