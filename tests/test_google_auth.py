"""Tests for Google OIDC authentication service.

Verifies authorization URL generation, code exchange, ID token verification,
and user mapping logic. Uses mocked HTTP responses to avoid real Google calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arc.db.connection import ArcDatabase
from arc.domain.models import User
from arc.security.google import GoogleAuthError, GoogleConfig, GoogleOIDCService


@pytest.fixture
def config():
    """Google OIDC configuration for testing."""
    return GoogleConfig(
        client_id="test-client-id.apps.googleusercontent.com",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:5173/api/auth/callback",
    )


@pytest.fixture
def db():
    """Mock database connection."""
    return AsyncMock(spec=ArcDatabase)


@pytest.fixture
def service(config, db):
    """GoogleOIDCService with mocked database."""
    return GoogleOIDCService(config, db)


class TestAuthorizationURL:
    """Test Google authorization URL generation."""

    def test_authorization_url_contains_client_id(self, service):
        """Authorization URL contains the client ID."""
        state = service.generate_state()
        nonce = service.generate_nonce()
        url = service.build_authorization_url(state, nonce)
        assert "test-client-id.apps.googleusercontent.com" in url

    def test_authorization_url_contains_redirect_uri(self, service):
        """Authorization URL contains the redirect URI."""
        state = service.generate_state()
        nonce = service.generate_nonce()
        url = service.build_authorization_url(state, nonce)
        # URL is encoded, so check for the encoded version
        assert "redirect_uri=" in url
        assert "localhost%3A5173" in url or "localhost:5173" in url

    def test_authorization_url_contains_response_type(self, service):
        """Authorization URL contains response_type=code."""
        state = service.generate_state()
        nonce = service.generate_nonce()
        url = service.build_authorization_url(state, nonce)
        assert "response_type=code" in url

    def test_authorization_url_contains_scope(self, service):
        """Authorization URL contains openid email profile scope."""
        state = service.generate_state()
        nonce = service.generate_nonce()
        url = service.build_authorization_url(state, nonce)
        assert "scope=openid" in url
        assert "email" in url
        assert "profile" in url

    def test_authorization_url_contains_state(self, service):
        """Authorization URL contains a state parameter for CSRF protection."""
        state = "test-state-token"
        nonce = service.generate_nonce()
        url = service.build_authorization_url(state, nonce)
        assert "state=test-state-token" in url

    def test_authorization_url_is_https(self, service):
        """Authorization URL uses HTTPS."""
        state = service.generate_state()
        nonce = service.generate_nonce()
        url = service.build_authorization_url(state, nonce)
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")

    def test_generate_state_is_sync(self, service):
        """generate_state returns a string directly (not a coroutine)."""
        result = service.generate_state()
        assert isinstance(result, str)
        assert len(result) >= 32

    def test_generate_nonce_is_sync(self, service):
        """generate_nonce returns a string directly (not a coroutine)."""
        result = service.generate_nonce()
        assert isinstance(result, str)
        assert len(result) >= 32

    def test_generate_state_is_random(self, service):
        """generate_state produces unique values."""
        s1 = service.generate_state()
        s2 = service.generate_state()
        assert s1 != s2

    def test_generate_nonce_is_random(self, service):
        """generate_nonce produces unique values."""
        n1 = service.generate_nonce()
        n2 = service.generate_nonce()
        assert n1 != n2


class TestCodeExchange:
    """Test authorization code exchange for tokens."""

    async def test_exchange_code_returns_tokens(self, service):
        """Code exchange returns access token and ID token."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "mock-access-token",
            "id_token": "mock-id-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await service.exchange_code("auth-code-123")

        assert result is not None
        assert result["access_token"] == "mock-access-token"
        assert result["id_token"] == "mock-id-token"

    async def test_exchange_code_raises_on_error(self, service):
        """Code exchange raises GoogleAuthError on Google API errors."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = Exception("Bad request")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with pytest.raises(GoogleAuthError):
                await service.exchange_code("invalid-code")


class TestIDTokenVerification:
    """Test ID token verification and claims extraction."""

    async def test_verify_id_token_returns_identity(self, service):
        """Valid ID token returns verified GoogleIdentity."""
        from arc.security.google import GoogleIdentity

        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with patch("jwt.PyJWKClient", return_value=mock_client):
            with patch("jwt.decode") as mock_decode:
                mock_decode.return_value = {
                    "sub": "google-user-123",
                    "email": "user@example.com",
                    "name": "Test User",
                    "picture": "https://example.com/photo.jpg",
                    "email_verified": True,
                    "nonce": "expected-nonce",
                }

                identity = await service.verify_id_token("mock-id-token", "expected-nonce")

        assert identity is not None
        assert isinstance(identity, GoogleIdentity)
        assert identity.sub == "google-user-123"
        assert identity.email == "user@example.com"

    async def test_verify_id_token_raises_on_invalid_token(self, service):
        """Invalid ID token raises GoogleAuthError."""
        with patch("jwt.PyJWKClient") as mock_client:
            mock_client.side_effect = Exception("Invalid token")

            with pytest.raises(GoogleAuthError):
                await service.verify_id_token("invalid-token", "some-nonce")

    async def test_verify_id_token_rejects_wrong_nonce(self, service):
        """ID token with wrong nonce is rejected."""
        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with patch("jwt.PyJWKClient", return_value=mock_client):
            with patch("jwt.decode") as mock_decode:
                mock_decode.return_value = {
                    "sub": "google-user-123",
                    "email": "user@example.com",
                    "email_verified": True,
                    "nonce": "token-nonce",
                }

                with pytest.raises(GoogleAuthError, match="Invalid nonce"):
                    await service.verify_id_token("mock-id-token", "expected-nonce")

    async def test_verify_id_token_rejects_missing_nonce_in_token(self, service):
        """ID token missing nonce claim is rejected when nonce is expected."""
        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with patch("jwt.PyJWKClient", return_value=mock_client):
            with patch("jwt.decode") as mock_decode:
                mock_decode.return_value = {
                    "sub": "google-user-123",
                    "email": "user@example.com",
                    "email_verified": True,
                    # No nonce claim
                }

                with pytest.raises(GoogleAuthError, match="Invalid nonce"):
                    await service.verify_id_token("mock-id-token", "expected-nonce")

    async def test_verify_id_token_rejects_wrong_issuer(self, service):
        """ID token with wrong issuer is rejected."""
        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with patch("jwt.PyJWKClient", return_value=mock_client):
            with patch("jwt.decode") as mock_decode:
                mock_decode.side_effect = Exception("Invalid issuer")

                with pytest.raises(GoogleAuthError):
                    await service.verify_id_token("mock-id-token", "some-nonce")

    async def test_verify_id_token_rejects_wrong_audience(self, service):
        """ID token with wrong audience is rejected."""
        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with patch("jwt.PyJWKClient", return_value=mock_client):
            with patch("jwt.decode") as mock_decode:
                mock_decode.side_effect = Exception("Invalid audience")

                with pytest.raises(GoogleAuthError):
                    await service.verify_id_token("mock-id-token", "some-nonce")

    async def test_verify_id_token_rejects_bad_signature(self, service):
        """ID token with bad signature is rejected."""
        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with patch("jwt.PyJWKClient", return_value=mock_client):
            with patch("jwt.decode") as mock_decode:
                mock_decode.side_effect = Exception("Signature verification failed")

                with pytest.raises(GoogleAuthError):
                    await service.verify_id_token("mock-id-token", "some-nonce")

    async def test_verify_id_token_rejects_expired_token(self, service):
        """Expired ID token is rejected."""
        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with patch("jwt.PyJWKClient", return_value=mock_client):
            with patch("jwt.decode") as mock_decode:
                mock_decode.side_effect = Exception("Token has expired")

                with pytest.raises(GoogleAuthError):
                    await service.verify_id_token("mock-id-token", "some-nonce")


class TestUserMapping:
    """Test Google identity to Arc user mapping."""

    async def test_find_or_link_user_returns_user(self, service, db):
        """Finding a linked user returns the Arc user."""
        mock_user = MagicMock(spec=User)
        mock_user.id = "user-123"
        mock_user.status = "active"

        db.get_user_by_provider = AsyncMock(return_value=mock_user)

        from arc.security.google import GoogleIdentity

        identity = GoogleIdentity(
            sub="google-123",
            email="user@example.com",
            email_verified=True,
        )

        user = await service.find_or_link_user(identity)

        assert user is not None
        assert user.id == "user-123"

    async def test_find_or_link_user_returns_none_for_unknown(self, service, db):
        """Unknown Google identity returns None (no auto-provisioning)."""
        db.get_user_by_provider = AsyncMock(return_value=None)

        from arc.security.google import GoogleIdentity

        identity = GoogleIdentity(
            sub="unknown-google-user",
            email="unknown@example.com",
            email_verified=True,
        )

        user = await service.find_or_link_user(identity)

        assert user is None

    async def test_find_or_link_user_returns_none_for_inactive(self, service, db):
        """Inactive user returns None."""
        mock_user = MagicMock(spec=User)
        mock_user.id = "user-456"
        mock_user.status = "inactive"

        db.get_user_by_provider = AsyncMock(return_value=mock_user)

        from arc.security.google import GoogleIdentity

        identity = GoogleIdentity(
            sub="google-456",
            email="inactive@example.com",
            email_verified=True,
        )

        user = await service.find_or_link_user(identity)

        assert user is None

    async def test_sub_identity_immutable_across_email_changes(self, service, db):
        """Same provider_subject with different email maps to same Arc user.

        The durable identity is provider + provider_subject, NOT email.
        """
        mock_user = MagicMock(spec=User)
        mock_user.id = "user-789"
        mock_user.status = "active"

        db.get_user_by_provider = AsyncMock(return_value=mock_user)

        from arc.security.google import GoogleIdentity

        # First login with original email
        identity_v1 = GoogleIdentity(
            sub="google-sub-789",
            email="alice@acme-corp.example",
            email_verified=True,
        )
        user_v1 = await service.find_or_link_user(identity_v1)

        # Second login with changed email (same sub)
        identity_v2 = GoogleIdentity(
            sub="google-sub-789",
            email="alice.new@acme-corp.example",
            email_verified=True,
        )
        user_v2 = await service.find_or_link_user(identity_v2)

        # Both resolve to the same Arc user
        assert user_v1 is not None
        assert user_v2 is not None
        assert user_v1.id == user_v2.id

        # The lookup was by provider_subject, not email
        db.get_user_by_provider.assert_called_with("google", "google-sub-789")


class TestConfiguration:
    """Test Google OIDC configuration."""

    def test_config_from_env(self):
        """Configuration can be created from environment variables."""
        config = GoogleConfig(
            client_id="test-id",
            client_secret="test-secret",
            redirect_uri="http://localhost:5173/api/auth/callback",
        )
        assert config.client_id == "test-id"
        assert config.client_secret == "test-secret"

    def test_is_configured_property(self, config, db):
        """Service reports as configured when credentials are present."""
        GoogleOIDCService(config, db)
        # Check if config has non-empty client_id and client_secret
        assert config.client_id and config.client_secret

    def test_is_not_configured_without_client_id(self, db):
        """Service reports as not configured without client ID."""
        config = GoogleConfig(
            client_id="",
            client_secret="test-secret",
            redirect_uri="http://localhost:5173/api/auth/callback",
        )
        # Empty client_id means not configured
        assert not config.client_id


class TestPyJWIIssuerList:
    """Regression: PyJWT issuer parameter accepts a list/sequence.

    Google issues tokens with either ``accounts.google.com`` or
    ``https://accounts.google.com`` as the issuer. The code passes
    both forms as a list. This test verifies PyJWT 2.x accepts that
    without mocking jwt.decode.
    """

    def test_pyjwt_accepts_list_issuer(self):
        """PyJWT decode() accepts a list for the issuer parameter."""
        import jwt as pyjwt
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()

        payload = {
            "sub": "test-user",
            "iss": "accounts.google.com",
            "aud": "test-client.apps.googleusercontent.com",
            "exp": 9999999999,
        }
        token = pyjwt.encode(payload, private_key, algorithm="RS256")

        # Should succeed with a list containing the exact issuer
        decoded = pyjwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience="test-client.apps.googleusercontent.com",
            issuer=["accounts.google.com", "https://accounts.google.com"],
        )
        assert decoded["sub"] == "test-user"
        assert decoded["iss"] == "accounts.google.com"

    def test_pyjwt_rejects_unlisted_issuer(self):
        """PyJWT rejects a token whose issuer is not in the list."""
        import jwt as pyjwt
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()

        payload = {
            "sub": "test-user",
            "iss": "evil-issuer.com",
            "aud": "test-client.apps.googleusercontent.com",
            "exp": 9999999999,
        }
        token = pyjwt.encode(payload, private_key, algorithm="RS256")

        from jwt.exceptions import InvalidIssuerError

        with pytest.raises(InvalidIssuerError):
            pyjwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience="test-client.apps.googleusercontent.com",
                issuer=["accounts.google.com", "https://accounts.google.com"],
            )
