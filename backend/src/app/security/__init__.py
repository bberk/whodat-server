"""Security primitives: league-credential encryption and password hashing.

Credential encryption uses AES-256-GCM with a versioned token format; passwords are stored as
salted Argon2id hashes (AC-AU-02). Nothing here logs plaintext, keys, or password material.
"""

from app.security.crypto import (
    CredentialCryptoError,
    CredentialDecryptionError,
    CredentialKeyInvalidError,
    CredentialKeyMissingError,
    CredentialTokenError,
    decrypt,
    encrypt,
)
from app.security.passwords import hash_password, verify_password

__all__ = [
    "CredentialCryptoError",
    "CredentialDecryptionError",
    "CredentialKeyInvalidError",
    "CredentialKeyMissingError",
    "CredentialTokenError",
    "decrypt",
    "encrypt",
    "hash_password",
    "verify_password",
]
