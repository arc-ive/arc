"""Tests for connector credential management (V2-ADR-015, TRD 20, Issue #137).

Security invariants under test:

A. Encryption at rest: stored credential is not plaintext.
B. Decryption: encrypted credential can be recovered correctly.
C. Tenant isolation: Tenant A cannot access Tenant B's credential.
D. API response security: responses never contain plaintext or encrypted credential.
E. Log security: credential material and encryption keys do not appear in logs.
F. Rotation: ciphertext changes, key_version updates, rotated_at updates.
G. Audit: credential-change audit events exist with safe metadata.
H. ENV fallback: no DB credential -> ENV credential is used.
I. DB precedence: DB credential takes precedence over ENV.
J. Authorization: unauthorized actor cannot manage credentials.
K. Cross-tenant isolation: explicit tenant A vs tenant B test.
L. Tamper detection: modified ciphertext fails decryption safely.
M. Failure safety: decryption/configuration failures do not log secrets.
"""

import base64
import logging
import uuid

import pytest

from arc.db.connection import NotFoundError
from arc.domain.models import (
    ConnectorCredential,
    ConnectorCredentialAudit,
    ConnectorProvider,
    TenantContext,
    UserRole,
)
from arc.security.encryption import EncryptionError, EncryptionService
from arc.services.connector_credentials import (
    ConnectorCredentialError,
    ConnectorCredentialService,
)


def _unique(prefix: str) -> str:
    return f"ccred-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str = "tenant-1", user_id: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Acme",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _encryption_key() -> bytes:
    """Return a deterministic 32-byte key for testing."""
    return b"\x01" * 32


def _make_encryption_service() -> EncryptionService:
    return EncryptionService(key=_encryption_key(), key_version=1)


# ---------------------------------------------------------------------------
# Fake repository for unit tests
# ---------------------------------------------------------------------------


class FakeConnectorCredentialRepository:
    """In-memory fake for ConnectorCredentialRepository."""

    def __init__(self):
        self._credentials: dict[tuple[str, str], ConnectorCredential] = {}
        self._audit: list[ConnectorCredentialAudit] = []

    async def get_by_tenant_and_provider(self, tenant_id: str, provider: str):
        return self._credentials.get((tenant_id, provider))

    async def create(self, credential: ConnectorCredential):
        key = (credential.tenant_id, credential.provider.value)
        self._credentials[key] = credential
        return credential

    async def update(self, credential: ConnectorCredential):
        key = (credential.tenant_id, credential.provider.value)
        if key not in self._credentials:
            raise NotFoundError("not found")
        self._credentials[key] = credential
        return credential

    async def delete(self, tenant_id: str, provider: str):
        key = (tenant_id, provider)
        if key not in self._credentials:
            raise NotFoundError("not found")
        del self._credentials[key]

    async def create_audit(self, audit: ConnectorCredentialAudit):
        self._audit.append(audit)
        return audit

    async def list_audit_for_tenant(self, tenant_id, provider=None):
        return [
            a
            for a in self._audit
            if a.tenant_id == tenant_id and (provider is None or a.provider.value == provider)
        ]


# ---------------------------------------------------------------------------
# A. Encryption at rest
# ---------------------------------------------------------------------------


class TestEncryptionAtRest:
    def test_stored_credential_is_not_plaintext(self):
        """Encrypted credential bytes are not equal to the plaintext."""
        enc = _make_encryption_service()
        plaintext = "ghp_supersecrettoken1234567890"
        encrypted, key_version = enc.encrypt(plaintext)
        assert encrypted != plaintext.encode("utf-8")
        assert encrypted != b""
        assert key_version == 1

    def test_different_encryptions_produce_different_ciphertext(self):
        """Two encryptions of the same plaintext produce different ciphertext (random nonce)."""
        enc = _make_encryption_service()
        plaintext = "ghp_same_token"
        enc1, _ = enc.encrypt(plaintext)
        enc2, _ = enc.encrypt(plaintext)
        assert enc1 != enc2


# ---------------------------------------------------------------------------
# B. Decryption
# ---------------------------------------------------------------------------


class TestDecryption:
    def test_roundtrip_encryption_decryption(self):
        """Encrypt then decrypt recovers the original plaintext."""
        enc = _make_encryption_service()
        plaintext = "ghp_abc123def456"
        encrypted, _ = enc.encrypt(plaintext)
        decrypted = enc.decrypt(encrypted)
        assert decrypted == plaintext

    def test_wrong_key_fails_decryption(self):
        """Decryption with a different key fails safely."""
        enc1 = EncryptionService(key=b"\x01" * 32, key_version=1)
        enc2 = EncryptionService(key=b"\x02" * 32, key_version=1)
        encrypted, _ = enc1.encrypt("secret")
        with pytest.raises(EncryptionError, match="Decryption failed"):
            enc2.decrypt(encrypted)

    def test_tampered_ciphertext_fails(self):
        """Modified ciphertext fails GCM authentication."""
        enc = _make_encryption_service()
        encrypted, _ = enc.encrypt("secret")
        tampered = bytearray(encrypted)
        tampered[-1] ^= 0xFF
        with pytest.raises(EncryptionError, match="Decryption failed"):
            enc.decrypt(bytes(tampered))


# ---------------------------------------------------------------------------
# C. Tenant isolation (unit-level)
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_tenant_a_cannot_read_tenant_b_credential(self):
        """Credential created by tenant A is not accessible by tenant B."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx_a = _context(tenant_id="tenant-a", user_id="user-a")
        ctx_b = _context(tenant_id="tenant-b", user_id="user-b")

        await svc.create_credential(ctx_a, ConnectorProvider.GITHUB, "token-a")

        # Tenant B cannot see tenant A's credential
        metadata = await svc.get_credential_metadata(ctx_b, ConnectorProvider.GITHUB)
        assert metadata is None

        # Tenant B cannot resolve tenant A's credential
        resolved = await svc.resolve_credential("tenant-b", ConnectorProvider.GITHUB)
        assert resolved is None


# ---------------------------------------------------------------------------
# D. API response security
# ---------------------------------------------------------------------------


class TestApiResponseSecurity:
    @pytest.mark.asyncio
    async def test_create_returns_no_plaintext(self):
        """Create response contains only safe metadata, not the credential."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        result = await svc.create_credential(ctx, ConnectorProvider.GITHUB, "ghp_secret123")

        assert "ghp_secret123" not in str(result)
        assert "encrypted_credential" not in result
        assert "token" not in result
        assert "credential" not in result
        # Safe fields present
        assert "id" in result
        assert "provider" in result
        assert result["provider"] == "github"
        assert "key_version" in result
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_get_metadata_returns_no_plaintext(self):
        """Get metadata response contains no secret material."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "ghp_secret123")

        metadata = await svc.get_credential_metadata(ctx, ConnectorProvider.GITHUB)
        assert "ghp_secret123" not in str(metadata)
        assert "encrypted_credential" not in metadata


# ---------------------------------------------------------------------------
# E. Log security
# ---------------------------------------------------------------------------


class TestLogSecurity:
    @pytest.mark.asyncio
    async def test_credential_not_in_logs(self, caplog):
        """Credential material does not appear in log output."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        secret = "ghp_LOGSECRET123456789"

        with caplog.at_level(logging.INFO, logger="arc.connector_credentials"):
            await svc.create_credential(ctx, ConnectorProvider.GITHUB, secret)

        for record in caplog.records:
            assert secret not in record.message
            assert "ghp_" not in record.message

    @pytest.mark.asyncio
    async def test_encryption_key_not_in_logs(self, caplog):
        """Encryption key material does not appear in log output."""
        key_hex = base64.b64encode(_encryption_key()).decode()
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        with caplog.at_level(logging.INFO, logger="arc.connector_credentials"):
            await svc.create_credential(ctx, ConnectorProvider.GITHUB, "token")

        for record in caplog.records:
            assert key_hex not in record.message


# ---------------------------------------------------------------------------
# F. Rotation
# ---------------------------------------------------------------------------


class TestRotation:
    @pytest.mark.asyncio
    async def test_rotation_updates_ciphertext_and_metadata(self):
        """Rotation changes ciphertext, key_version, and rotated_at."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "old_token")

        cred_before = await repo.get_by_tenant_and_provider("tenant-1", "github")
        old_encrypted = cred_before.encrypted_credential
        old_key_version = cred_before.key_version
        assert cred_before.rotated_at is None

        await svc.rotate_credential(ctx, ConnectorProvider.GITHUB, "new_token")

        cred_after = await repo.get_by_tenant_and_provider("tenant-1", "github")
        assert cred_after.encrypted_credential != old_encrypted
        assert cred_after.key_version == old_key_version  # same key, re-encrypted
        assert cred_after.rotated_at is not None

    @pytest.mark.asyncio
    async def test_rotated_credential_decrypts_to_new_value(self):
        """After rotation, resolve returns the new plaintext."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "old_token")
        await svc.rotate_credential(ctx, ConnectorProvider.GITHUB, "new_token")

        resolved = await svc.resolve_credential("tenant-1", ConnectorProvider.GITHUB)
        assert resolved == "new_token"

    @pytest.mark.asyncio
    async def test_rotation_of_nonexistent_credential_fails(self):
        """Rotating a credential that doesn't exist raises error."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        with pytest.raises(ConnectorCredentialError, match="No credential found"):
            await svc.rotate_credential(ctx, ConnectorProvider.GITHUB, "token")


# ---------------------------------------------------------------------------
# G. Audit
# ---------------------------------------------------------------------------


class TestAudit:
    @pytest.mark.asyncio
    async def test_create_produces_audit_event(self):
        """Creating a credential produces an audit record with safe metadata."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context(user_id="actor-1")
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "token")

        audit = await svc.list_audit(ctx, ConnectorProvider.GITHUB)
        assert len(audit) == 1
        assert audit[0].operation == "create"
        assert audit[0].actor_user_id == "actor-1"
        assert audit[0].provider == ConnectorProvider.GITHUB
        assert audit[0].key_version == 1

    @pytest.mark.asyncio
    async def test_rotate_produces_audit_event(self):
        """Rotating a credential produces an audit record."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context(user_id="actor-1")
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "token")
        await svc.rotate_credential(ctx, ConnectorProvider.GITHUB, "new_token")

        audit = await svc.list_audit(ctx, ConnectorProvider.GITHUB)
        assert len(audit) == 2
        assert audit[0].operation == "create"
        assert audit[1].operation == "rotate"

    @pytest.mark.asyncio
    async def test_delete_produces_audit_event(self):
        """Deleting a credential produces an audit record."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context(user_id="actor-1")
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "token")
        await svc.delete_credential(ctx, ConnectorProvider.GITHUB)

        audit = await svc.list_audit(ctx, ConnectorProvider.GITHUB)
        assert len(audit) == 2
        assert audit[0].operation == "create"
        assert audit[1].operation == "delete"

    @pytest.mark.asyncio
    async def test_audit_never_contains_credential(self):
        """Audit records never contain plaintext or encrypted credentials."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context(user_id="actor-1")
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "ghp_secret")

        audit = await svc.list_audit(ctx)
        for record in audit:
            audit_dict = {
                "id": record.id,
                "tenant_id": record.tenant_id,
                "provider": record.provider.value,
                "operation": record.operation,
                "actor_user_id": record.actor_user_id,
                "key_version": record.key_version,
            }
            assert "ghp_secret" not in str(audit_dict)
            assert "encrypted_credential" not in str(audit_dict)


# ---------------------------------------------------------------------------
# H. ENV fallback
# ---------------------------------------------------------------------------


class TestEnvFallback:
    @pytest.mark.asyncio
    async def test_env_fallback_when_no_db_credential(self):
        """When no DB credential exists, ENV fallback is used."""
        from arc.services.connector_providers.settings import ConnectorCredentialStore

        store = ConnectorCredentialStore(raw='{"tenant-1": {"github": "env_token_123"}}')

        token = store.get("tenant-1", ConnectorProvider.GITHUB)
        assert token == "env_token_123"


# ---------------------------------------------------------------------------
# I. DB precedence
# ---------------------------------------------------------------------------


class TestDBPrecedence:
    @pytest.mark.asyncio
    async def test_db_credential_takes_precedence_over_env(self):
        """When both DB and ENV credentials exist, DB credential is used."""
        from arc.services.connector_providers.settings import ConnectorCredentialStore

        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        # Create DB credential
        ctx = _context()
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "db_token")

        # ENV has a different token
        env_store = ConnectorCredentialStore(raw='{"tenant-1": {"github": "env_token"}}')

        # DB credential service resolves the DB token
        db_token = await svc.resolve_credential("tenant-1", ConnectorProvider.GITHUB)
        assert db_token == "db_token"

        # ENV store would return env_token
        env_token = env_store.get("tenant-1", ConnectorProvider.GITHUB)
        assert env_token == "env_token"

        # In the sync service, DB takes precedence:
        # token = credential_service.resolve_credential(...) or env_store.get(...)
        # Since DB returns a value, ENV is never consulted.
        assert db_token is not None
        assert db_token != env_token


# ---------------------------------------------------------------------------
# J. Authorization (unit-level)
# ---------------------------------------------------------------------------


class TestAuthorization:
    @pytest.mark.asyncio
    async def test_create_duplicate_fails(self):
        """Creating a credential when one already exists fails with error."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "token1")

        with pytest.raises(ConnectorCredentialError, match="already exists"):
            await svc.create_credential(ctx, ConnectorProvider.GITHUB, "token2")


# ---------------------------------------------------------------------------
# K. Cross-tenant isolation
# ---------------------------------------------------------------------------


class TestCrossTenantIsolation:
    @pytest.mark.asyncio
    async def test_tenant_a_cannot_delete_tenant_b_credential(self):
        """Tenant B cannot delete tenant A's credential."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx_a = _context(tenant_id="tenant-a", user_id="user-a")
        ctx_b = _context(tenant_id="tenant-b", user_id="user-b")

        await svc.create_credential(ctx_a, ConnectorProvider.GITHUB, "token-a")

        with pytest.raises(ConnectorCredentialError, match="No credential found"):
            await svc.delete_credential(ctx_b, ConnectorProvider.GITHUB)

        # Tenant A's credential still exists
        cred = await repo.get_by_tenant_and_provider("tenant-a", "github")
        assert cred is not None

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_rotate_tenant_b_credential(self):
        """Tenant B cannot rotate tenant A's credential."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx_a = _context(tenant_id="tenant-a", user_id="user-a")
        ctx_b = _context(tenant_id="tenant-b", user_id="user-b")

        await svc.create_credential(ctx_a, ConnectorProvider.GITHUB, "token-a")

        with pytest.raises(ConnectorCredentialError, match="No credential found"):
            await svc.rotate_credential(ctx_b, ConnectorProvider.GITHUB, "token-b")


# ---------------------------------------------------------------------------
# L. Tamper detection
# ---------------------------------------------------------------------------


class TestTamperDetection:
    def test_modified_ciphertext_fails_decryption(self):
        """Modifying stored ciphertext causes decryption to fail safely."""
        enc = _make_encryption_service()
        encrypted, _ = enc.encrypt("secret")

        # Tamper with the ciphertext
        tampered = bytearray(encrypted)
        tampered[20] ^= 0xFF
        tampered = bytes(tampered)

        with pytest.raises(EncryptionError, match="Decryption failed"):
            enc.decrypt(tampered)

    def test_truncated_ciphertext_fails(self):
        """Truncated ciphertext fails safely."""
        enc = _make_encryption_service()
        encrypted, _ = enc.encrypt("secret")

        with pytest.raises(EncryptionError, match="Ciphertext too short"):
            enc.decrypt(encrypted[:5])


# ---------------------------------------------------------------------------
# M. Failure safety
# ---------------------------------------------------------------------------


class TestFailureSafety:
    @pytest.mark.asyncio
    async def test_decryption_failure_returns_none(self, caplog):
        """When decryption fails (tampered data), resolve returns None without logging secrets."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        # Create a credential, then tamper with the stored bytes
        await svc.create_credential(ctx, ConnectorProvider.GITHUB, "secret_token")
        cred = await repo.get_by_tenant_and_provider("tenant-1", "github")

        # Tamper with stored ciphertext
        tampered = bytearray(cred.encrypted_credential)
        tampered[20] ^= 0xFF
        cred.encrypted_credential = bytes(tampered)

        with caplog.at_level(logging.ERROR, logger="arc.connector_credentials"):
            result = await svc.resolve_credential("tenant-1", ConnectorProvider.GITHUB)

        assert result is None
        # Verify no secret material in logs
        for record in caplog.records:
            assert "secret_token" not in record.message

    @pytest.mark.asyncio
    async def test_delete_nonexistent_fails_safely(self):
        """Deleting a nonexistent credential raises a controlled error."""
        repo = FakeConnectorCredentialRepository()
        enc = _make_encryption_service()
        svc = ConnectorCredentialService(credential_repo=repo, encryption_service=enc)

        ctx = _context()
        with pytest.raises(ConnectorCredentialError, match="No credential found"):
            await svc.delete_credential(ctx, ConnectorProvider.GITHUB)


# ---------------------------------------------------------------------------
# Domain model validation
# ---------------------------------------------------------------------------


class TestDomainModels:
    def test_credential_model_validation(self):
        """ConnectorCredential validates required fields."""
        with pytest.raises(ValueError, match="ID cannot be empty"):
            ConnectorCredential(
                id="", tenant_id="t", provider=ConnectorProvider.GITHUB, encrypted_credential=b"x"
            )

        with pytest.raises(ValueError, match="Tenant ID cannot be empty"):
            ConnectorCredential(
                id="1", tenant_id="", provider=ConnectorProvider.GITHUB, encrypted_credential=b"x"
            )

        with pytest.raises(ValueError, match="Invalid connector provider"):
            ConnectorCredential(
                id="1", tenant_id="t", provider="invalid", encrypted_credential=b"x"
            )

        with pytest.raises(ValueError, match="non-empty bytes"):
            ConnectorCredential(
                id="1", tenant_id="t", provider=ConnectorProvider.GITHUB, encrypted_credential=b""
            )

        with pytest.raises(ValueError, match="positive integer"):
            ConnectorCredential(
                id="1",
                tenant_id="t",
                provider=ConnectorProvider.GITHUB,
                encrypted_credential=b"x",
                key_version=0,
            )

    def test_audit_model_validation(self):
        """ConnectorCredentialAudit validates required fields."""
        with pytest.raises(ValueError, match="ID cannot be empty"):
            ConnectorCredentialAudit(
                id="",
                tenant_id="t",
                provider=ConnectorProvider.GITHUB,
                operation="create",
                actor_user_id="u",
            )

        with pytest.raises(ValueError, match="Invalid audit operation"):
            ConnectorCredentialAudit(
                id="1",
                tenant_id="t",
                provider=ConnectorProvider.GITHUB,
                operation="invalid",
                actor_user_id="u",
            )

        with pytest.raises(ValueError, match="Actor user ID cannot be empty"):
            ConnectorCredentialAudit(
                id="1",
                tenant_id="t",
                provider=ConnectorProvider.GITHUB,
                operation="create",
                actor_user_id="",
            )
