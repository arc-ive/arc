"""Authenticated encryption for connector credentials (V2-ADR-015, TRD 20).

Provides AES-256-GCM encryption for connector credential storage.
Each encryption operation uses a cryptographically random 12-byte nonce.
The key is loaded from the CONNECTOR_ENCRYPTION_KEY environment variable.

Security properties:
- Authenticated encryption detects tampering (GCM tag).
- Random nonce per encryption prevents reuse.
- Plaintext is never logged, serialized, or returned through APIs.
- Key material is never logged or exposed.
"""

import base64
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("arc.security.encryption")

_DEFAULT_KEY_VERSION = 1


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""


class EncryptionService:
    """AES-256-GCM authenticated encryption for credential storage.

    The key is loaded from CONNECTOR_ENCRYPTION_KEY (base64-encoded 32 bytes).
    The key_version is determined by the current configured key version.

    Args:
        key: Raw 32-byte AES-256 key. If None, loaded from environment.
        key_version: Current key version identifier.
    """

    def __init__(self, key: bytes | None = None, key_version: int = _DEFAULT_KEY_VERSION):
        if key is None:
            key = _load_key_from_env()
        if len(key) != 32:
            raise EncryptionError("Encryption key must be exactly 32 bytes (AES-256)")
        self._aesgcm = AESGCM(key)
        self._key_version = key_version

    @property
    def key_version(self) -> int:
        """Return the current key version."""
        return self._key_version

    def encrypt(self, plaintext: str) -> tuple[bytes, int]:
        """Encrypt plaintext and return (ciphertext, key_version).

        The ciphertext includes the GCM authentication tag. A fresh
        random nonce is generated for every encryption operation.

        Plaintext is never logged.
        """
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        # Prepend nonce to ciphertext: nonce (12) + ciphertext_with_tag
        return nonce + ciphertext, self._key_version

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt ciphertext and return the plaintext string.

        Raises EncryptionError on tampering or invalid ciphertext.
        Plaintext is never logged.
        """
        if len(ciphertext) < 13:
            raise EncryptionError("Ciphertext too short")
        nonce = ciphertext[:12]
        encrypted_data = ciphertext[12:]
        try:
            plaintext_bytes = self._aesgcm.decrypt(nonce, encrypted_data, None)
            return plaintext_bytes.decode("utf-8")
        except Exception as exc:
            raise EncryptionError("Decryption failed: invalid ciphertext or tampered data") from exc


def _load_key_from_env() -> bytes:
    """Load the AES-256 key from CONNECTOR_ENCRYPTION_KEY environment variable.

    The key must be base64-encoded and exactly 32 bytes when decoded.
    """
    raw = os.getenv("CONNECTOR_ENCRYPTION_KEY", "")
    if not raw:
        raise EncryptionError("CONNECTOR_ENCRYPTION_KEY environment variable is required")
    try:
        key = base64.b64decode(raw)
    except Exception as exc:
        raise EncryptionError("CONNECTOR_ENCRYPTION_KEY must be valid base64") from exc
    if len(key) != 32:
        raise EncryptionError(
            f"CONNECTOR_ENCRYPTION_KEY must decode to exactly 32 bytes, got {len(key)}"
        )
    return key
