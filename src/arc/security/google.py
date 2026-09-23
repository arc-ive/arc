"""Google OIDC authentication service.

Handles the Google OAuth2/OIDC flow:
1. Build the Google authorization URL with state and nonce
2. Exchange authorization code for tokens
3. Verify the Google ID token
4. Map the Google identity to an Arc user

Security properties:
- State parameter prevents CSRF (stored in session cookie)
- Nonce prevents replay attacks on ID tokens
- Issuer validation ensures tokens come from Google
- Audience validation ensures tokens are for this application
- Signature verification uses Google's public keys
- Provider subject (Google's `sub`) is the durable identity binding
- Email changes do NOT update the Arc user email (prevents account takeover)
- Unknown Google identities are NOT auto-provisioned
"""

import logging
import secrets
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import httpx

from arc.db.connection import ArcDatabase
from arc.domain.models import User

logger = logging.getLogger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUER = "accounts.google.com"

# Google OIDC scopes
GOOGLE_SCOPES = ["openid", "email", "profile"]


@dataclass
class GoogleConfig:
    """Google OAuth2 configuration."""

    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass
class GoogleIdentity:
    """Verified Google identity from ID token."""

    sub: str  # Google's stable user ID (durable)
    email: str
    email_verified: bool
    name: Optional[str] = None
    picture: Optional[str] = None


class GoogleAuthError(Exception):
    """Raised when Google authentication fails."""


class GoogleOIDCService:
    """Handles Google OAuth2/OIDC authentication flow."""

    def __init__(self, config: GoogleConfig, db: ArcDatabase):
        self._config = config
        self._db = db
        self._jwks_cache: Optional[dict] = None
        self._jwks_cache_timestamp: float = 0

    def build_authorization_url(self, state: str, nonce: str) -> str:
        """Build the Google OAuth2 authorization URL.

        Args:
            state: CSRF prevention token (stored in cookie, validated on callback).
            nonce: Replay prevention token (included in ID token request).

        Returns:
            The full Google authorization URL to redirect the user to.
        """
        params = {
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "state": state,
            "nonce": nonce,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Exchange authorization code for tokens.

        Args:
            code: The authorization code from Google's callback.

        Returns:
            Token response containing id_token, access_token, etc.

        Raises:
            GoogleAuthError: If the code exchange fails.
        """
        data = {
            "code": code,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "redirect_uri": self._config.redirect_uri,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(GOOGLE_TOKEN_ENDPOINT, data=data)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error("Google token exchange failed: %s", e.response.status_code)
                raise GoogleAuthError("Token exchange failed") from e
            except Exception as e:
                logger.error("Google token exchange error: %s", e)
                raise GoogleAuthError("Token exchange unavailable") from e

    async def verify_id_token(self, id_token: str, nonce: str) -> GoogleIdentity:
        """Verify a Google ID token and extract the identity.

        Args:
            id_token: The raw ID token from Google.
            nonce: The expected nonce from the session (required).

        Returns:
            Verified Google identity.

        Raises:
            GoogleAuthError: If verification fails.
        """
        try:
            import jwt as pyjwt
            from jwt import PyJWKClient

            # Get Google's public keys
            jwks_client = PyJWKClient(GOOGLE_JWKS_URI)
            signing_key = jwks_client.get_signing_key_from_jwt(id_token)

            # Decode and verify
            payload = pyjwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._config.client_id,
                issuer=[GOOGLE_ISSUER, f"https://{GOOGLE_ISSUER}"],
                options={"require": ["sub", "email", "iss", "aud", "exp"]},
            )

            # Validate nonce (required — fail closed)
            if payload.get("nonce") != nonce:
                raise GoogleAuthError("Invalid nonce")

            return GoogleIdentity(
                sub=payload["sub"],
                email=payload["email"],
                email_verified=payload.get("email_verified", False),
                name=payload.get("name"),
                picture=payload.get("picture"),
            )

        except GoogleAuthError:
            raise
        except Exception as e:
            logger.error("Google ID token verification failed: %s", e)
            raise GoogleAuthError("Invalid ID token") from e

    async def find_or_link_user(self, identity: GoogleIdentity) -> Optional[User]:
        """Resolve a verified Google identity to an Arc user.

        Two paths, in order:

        1. **Returning sign-in.** The durable ``(google, sub)`` pair is
           already bound to a user — return it.
        2. **First sign-in.** No binding exists yet, so the identity is
           correlated to an already-provisioned Arc user by verified
           email and the binding is created. Subsequent sign-ins take
           path 1 and never consult email again.

        Step 2 is what makes Google sign-in possible at all: nothing
        else in Arc writes ``provider_subject``, so without it path 1 can
        never match and every Google sign-in is refused.

        Unknown identities are still NOT auto-provisioned. Correlation
        only ever finds a user an administrator already created; it never
        creates one.

        Four conditions guard the binding, and each fails closed:

        - Google must report the address verified. An unverified email is
          an unproven claim, and binding on it would let anyone who can
          assert an address take over the Arc user holding it.
        - The Arc user must exist. No user, no sign-in.
        - The Arc user must be active.
        - The Arc user must not already carry a provider binding. A user
          bound to one Google subject is never re-bound to a different
          one by this path, so a second identity claiming the same
          address cannot displace the first.

        Email is a safe correlation key here because ``users.email`` is
        UNIQUE, and it is used only to FIND the user — the durable
        subject is what gets stored, and the address is never written
        back from the provider (see ``link_user_provider``).

        Args:
            identity: The verified Google identity.

        Returns:
            The Arc user, or None when any condition above fails.
        """
        # Path 1 — already bound.
        user = await self._db.get_user_by_provider("google", identity.sub)

        if user is not None:
            if user.status != "active":
                logger.warning(
                    "Google identity %s maps to disabled user %s",
                    identity.sub,
                    user.id,
                )
                return None
            return user

        # Path 2 — first sign-in for a provisioned user.
        if not identity.email_verified:
            logger.warning(
                "Refusing to link unverified Google email: sub=%s",
                identity.sub,
            )
            return None

        candidate = await self._db.get_user_by_email(identity.email)

        if candidate is None:
            # Unknown identity. Explicit admin provisioning is required.
            logger.info(
                "Unknown Google identity: sub=%s email=%s",
                identity.sub,
                identity.email,
            )
            return None

        if candidate.status != "active":
            logger.warning(
                "Google identity %s maps to disabled user %s",
                identity.sub,
                candidate.id,
            )
            return None

        if candidate.provider_subject is not None:
            # Already bound to a different subject. Never re-bind.
            logger.warning(
                "Refusing to re-link user %s: already bound to provider %s",
                candidate.id,
                candidate.auth_provider,
            )
            return None

        linked = await self._db.link_user_provider(
            user_id=candidate.id,
            auth_provider="google",
            provider_subject=identity.sub,
            display_name=identity.name,
            avatar_url=identity.picture,
        )
        logger.info(
            "Linked Google identity to existing user: user=%s sub=%s",
            linked.id,
            identity.sub,
        )
        return linked

    def generate_state(self) -> str:
        """Generate a CSRF-prevention state token."""
        return secrets.token_urlsafe(32)

    def generate_nonce(self) -> str:
        """Generate a nonce for ID token replay prevention."""
        return secrets.token_urlsafe(32)
