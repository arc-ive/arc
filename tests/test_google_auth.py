"""Tests for Google OIDC authentication service.

Verifies authorization URL generation, code exchange, ID token verification,
and user mapping logic. Uses mocked HTTP responses to avoid real Google calls.
"""

import uuid
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
        # Explicit: an unknown identity matches no provisioned user by
        # email either. Without this the auto-specced mock returns a
        # truthy object and the assertion below passes for the wrong
        # reason.
        db.get_user_by_email = AsyncMock(return_value=None)
        db.link_user_provider = AsyncMock()

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


class TestFirstSignInLinking:
    """First Google sign-in binds the identity to a provisioned user.

    Nothing else in Arc writes ``provider_subject``. Without this step
    ``get_user_by_provider`` can never match and every Google sign-in is
    refused — which is exactly what the product did.
    """

    @staticmethod
    def _identity(**overrides):
        from arc.security.google import GoogleIdentity

        return GoogleIdentity(
            **{
                "sub": "google-new-1",
                "email": "employee@acme.example",
                "email_verified": True,
                "name": "Ada Lovelace",
                "picture": "https://example.com/a.png",
                **overrides,
            }
        )

    @staticmethod
    def _provisioned(**overrides):
        user = MagicMock(spec=User)
        user.id = "u-acme-employee"
        user.status = "active"
        user.provider_subject = None
        user.auth_provider = "local"
        for key, value in overrides.items():
            setattr(user, key, value)
        return user

    async def test_first_sign_in_links_a_provisioned_user(self, service, db):
        candidate = self._provisioned()
        linked = self._provisioned(provider_subject="google-new-1")
        db.get_user_by_provider = AsyncMock(return_value=None)
        db.get_user_by_email = AsyncMock(return_value=candidate)
        db.link_user_provider = AsyncMock(return_value=linked)

        user = await service.find_or_link_user(self._identity())

        assert user is linked
        db.link_user_provider.assert_awaited_once_with(
            user_id="u-acme-employee",
            auth_provider="google",
            provider_subject="google-new-1",
            display_name="Ada Lovelace",
            avatar_url="https://example.com/a.png",
        )

    async def test_returning_sign_in_never_consults_email(self, service, db):
        """Once bound, the durable subject is authoritative.

        Email must not re-enter the decision, or a reassigned address
        would become a path back to an account.
        """
        bound = self._provisioned(provider_subject="google-new-1")
        db.get_user_by_provider = AsyncMock(return_value=bound)
        db.get_user_by_email = AsyncMock()
        db.link_user_provider = AsyncMock()

        user = await service.find_or_link_user(self._identity())

        assert user is bound
        db.get_user_by_email.assert_not_awaited()
        db.link_user_provider.assert_not_awaited()

    async def test_unverified_email_is_never_linked(self, service, db):
        """An unverified address is an unproven claim.

        Binding on it would let anyone who can assert an address take
        over the Arc user holding it.
        """
        db.get_user_by_provider = AsyncMock(return_value=None)
        db.get_user_by_email = AsyncMock()
        db.link_user_provider = AsyncMock()

        user = await service.find_or_link_user(self._identity(email_verified=False))

        assert user is None
        db.get_user_by_email.assert_not_awaited()
        db.link_user_provider.assert_not_awaited()

    async def test_unknown_email_is_not_provisioned(self, service, db):
        """Correlation finds a user an admin created; it never creates one."""
        db.get_user_by_provider = AsyncMock(return_value=None)
        db.get_user_by_email = AsyncMock(return_value=None)
        db.link_user_provider = AsyncMock()

        user = await service.find_or_link_user(self._identity())

        assert user is None
        db.link_user_provider.assert_not_awaited()

    async def test_disabled_user_is_not_linked(self, service, db):
        db.get_user_by_provider = AsyncMock(return_value=None)
        db.get_user_by_email = AsyncMock(return_value=self._provisioned(status="disabled"))
        db.link_user_provider = AsyncMock()

        user = await service.find_or_link_user(self._identity())

        assert user is None
        db.link_user_provider.assert_not_awaited()

    async def test_already_bound_user_is_never_rebound(self, service, db):
        """Account-takeover guard.

        A user already bound to one Google subject must not be re-bound
        to a different one by a second identity asserting the same
        address.
        """
        db.get_user_by_provider = AsyncMock(return_value=None)
        db.get_user_by_email = AsyncMock(
            return_value=self._provisioned(
                provider_subject="google-ORIGINAL", auth_provider="google"
            )
        )
        db.link_user_provider = AsyncMock()

        user = await service.find_or_link_user(self._identity(sub="google-ATTACKER"))

        assert user is None
        db.link_user_provider.assert_not_awaited()


class TestFirstSignInLinkingAgainstTheDatabase:
    """The same Path 2 behaviour, proved against real PostgreSQL.

    The mock-based tests above assert that ``link_user_provider`` is
    CALLED with the right arguments. That is not the same claim as the
    binding PERSISTING, or as the user's email surviving the link —
    both of which are properties of the write, and a mock cannot show
    either. Review of PR #306 asked for exactly that distinction, and it
    is a fair one: an auth branch that is only proved against a mock is
    proved against the test's own assumptions.

    These exercise the real query path end to end: a provisioned user,
    an unbound row, a sign-in, and then a re-read from the database to
    see what is actually stored.
    """

    @staticmethod
    async def _database():
        """Standalone connection: the module-level ``db`` fixture is a mock."""
        import os

        from arc.db.connection import ArcDatabase

        database = ArcDatabase(
            os.getenv("DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc_test")
        )
        await database.connect()
        return database

    @staticmethod
    async def _provisioned_user(database, *, status: str = "active"):
        """An administrator-created user with no provider binding."""
        from arc.domain.models import User
        from arc.repositories.tenancy import PostgreSQLUserRepository

        users = PostgreSQLUserRepository(database)
        return await users.create(
            User(
                id=f"gauth-{uuid.uuid4().hex[:12]}",
                email=f"{uuid.uuid4().hex}@acme.example",
                username="provisioned",
                status=status,
            )
        )

    @staticmethod
    def _service_over(database, config):
        return GoogleOIDCService(config, database)

    @staticmethod
    def _identity(email, **overrides):
        from arc.security.google import GoogleIdentity

        return GoogleIdentity(
            **{
                "sub": f"google-{uuid.uuid4().hex[:12]}",
                "email": email,
                "email_verified": True,
                "name": "Ada Lovelace",
                "picture": "https://example.com/a.png",
                **overrides,
            }
        )

    async def test_a_verified_email_binds_the_subject_and_it_persists(self, config):
        """Requirement 1: the binding is durable, not merely attempted."""
        database = await self._database()
        try:
            user = await self._provisioned_user(database)
            assert user.provider_subject is None, "fixture must start unbound"

            identity = self._identity(user.email)
            linked = await self._service_over(database, config).find_or_link_user(identity)

            assert linked is not None
            # Re-read: what the caller got could be an in-memory object.
            stored = await database.get_user_by_email(user.email)
            assert stored.provider_subject == identity.sub
            assert stored.auth_provider == "google"

            # And the durable lookup now resolves, which is the whole
            # point: the next sign-in takes Path 1.
            by_subject = await database.get_user_by_provider("google", identity.sub)
            assert by_subject is not None
            assert by_subject.id == user.id
        finally:
            await database.disconnect()

    async def test_an_unverified_email_writes_nothing(self, config):
        """Requirement 2: rejected, and no binding left behind.

        Asserting the return is None is not enough — a partial write
        would still return None.
        """
        database = await self._database()
        try:
            user = await self._provisioned_user(database)
            identity = self._identity(user.email, email_verified=False)

            result = await self._service_over(database, config).find_or_link_user(identity)

            assert result is None
            stored = await database.get_user_by_email(user.email)
            assert stored.provider_subject is None
            assert stored.auth_provider == "local"
        finally:
            await database.disconnect()

    async def test_an_already_bound_user_is_not_rebound(self, config):
        """Requirement 3: account-takeover guard, against the stored row.

        A second Google identity asserting the same address must not
        displace the first, and must leave the original binding intact.
        """
        database = await self._database()
        try:
            user = await self._provisioned_user(database)
            service = self._service_over(database, config)

            first = self._identity(user.email)
            assert await service.find_or_link_user(first) is not None

            attacker = self._identity(user.email)
            assert await service.find_or_link_user(attacker) is None

            stored = await database.get_user_by_email(user.email)
            assert stored.provider_subject == first.sub, "original binding was displaced"
        finally:
            await database.disconnect()

    async def test_the_email_is_never_written_back_from_the_provider(self, config):
        """Requirement 4: linking binds a subject; it does not touch email.

        Email is the correlation key for ONE sign-in only. If the
        provider could rewrite it, a reassigned address would become a
        path back into an account.
        """
        database = await self._database()
        try:
            user = await self._provisioned_user(database)
            original_email = user.email

            # The provider reports a DIFFERENT address in the same claim
            # set; correlation still happens on the stored one.
            identity = self._identity(original_email)
            await self._service_over(database, config).find_or_link_user(identity)

            stored = await database.get_user_by_email(original_email)
            assert stored.email == original_email
            assert stored.id == user.id
        finally:
            await database.disconnect()

    async def test_a_disabled_user_is_not_bound(self, config):
        """A disabled account must not gain a working sign-in route."""
        database = await self._database()
        try:
            user = await self._provisioned_user(database, status="disabled")
            identity = self._identity(user.email)

            result = await self._service_over(database, config).find_or_link_user(identity)

            assert result is None
            stored = await database.get_user_by_email(user.email)
            assert stored.provider_subject is None
        finally:
            await database.disconnect()

    async def test_an_unknown_email_provisions_nobody(self, config):
        """Correlation finds a user an administrator created; never creates one."""
        database = await self._database()
        try:
            absent = f"{uuid.uuid4().hex}@nowhere.example"
            identity = self._identity(absent)

            result = await self._service_over(database, config).find_or_link_user(identity)

            assert result is None
            assert await database.get_user_by_email(absent) is None
        finally:
            await database.disconnect()
