"""AES-256-GCM encryption for per-user league credentials.

A token is self-describing and versioned so the format can evolve without ambiguity::

    base64url(version byte || 12-byte nonce || AES-256-GCM ciphertext and tag)

The 256-bit key is read on every call from ``Settings.league_credentials_key`` via
``app.config.get_settings``. There is deliberately no default or derived fallback key: a missing
or malformed key raises instead of silently encrypting credentials with a guessable key. Because
``get_settings`` is process-cached, changing ``LEAGUE_CREDENTIALS_KEY`` takes effect only after
``get_settings.cache_clear()`` or a process restart; tokens encrypted with a replaced key are not
decryptable under the new key (there is no multi-key ring in this module).

The associated data is the fixed string ``whodat-server:league-credentials:v1``. It is static for
this token version; a future version must use a new AAD value together with a new version byte.

Error messages identify the failure but never include the key or the plaintext.
"""

from __future__ import annotations

import base64
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_VERSION = 1
_NONCE_BYTES = 12
_TAG_BYTES = 16
_KEY_BYTES = 32
_AAD = b"whodat-server:league-credentials:v1"


class CredentialCryptoError(Exception):
    """Base class for credential-encryption failures.

    Subclasses carry the specific failure (missing key, invalid key, malformed token, failed
    authentication). Messages never contain key or plaintext material.
    """


class CredentialKeyMissingError(CredentialCryptoError):
    """``LEAGUE_CREDENTIALS_KEY`` is not configured."""


class CredentialKeyInvalidError(CredentialCryptoError):
    """``LEAGUE_CREDENTIALS_KEY`` is not base64 for exactly 32 bytes."""


class CredentialTokenError(CredentialCryptoError):
    """The token is not well-formed base64url or uses an unsupported format version."""


class CredentialDecryptionError(CredentialCryptoError):
    """The token failed authentication: it was tampered with or encrypted with another key."""


def encrypt(plaintext: str) -> str:
    """Encrypt ``plaintext`` into a versioned, base64url-encoded token.

    A fresh 12-byte nonce is generated for every call, so encrypting the same plaintext twice
    yields different tokens. Raises :class:`CredentialKeyMissingError` or
    :class:`CredentialKeyInvalidError` when the configured key cannot be used.
    """
    key = _load_key()
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), _AAD)
    token = bytes([_VERSION]) + nonce + ciphertext
    return base64.urlsafe_b64encode(token).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`.

    Raises :class:`CredentialTokenError` for malformed or unsupported tokens,
    :class:`CredentialDecryptionError` when authentication fails (tampering or a different key),
    and the key errors described by :func:`encrypt`. The plaintext is not logged.
    """
    key = _load_key()
    raw = _decode_token(token)
    nonce = raw[1 : 1 + _NONCE_BYTES]
    ciphertext = raw[1 + _NONCE_BYTES :]
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _AAD)
    except InvalidTag, ValueError:
        raise CredentialDecryptionError("credential token could not be decrypted") from None
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError:
        raise CredentialDecryptionError("decrypted credential is not valid UTF-8") from None


def _load_key() -> bytes:
    """Return the configured 256-bit key, or raise a typed error without echoing the value."""
    configured = get_settings().league_credentials_key
    if configured is None or not configured.strip():
        raise CredentialKeyMissingError("league credential key is not configured")

    try:
        key = base64.b64decode(configured.strip(), altchars=b"-_", validate=True)
    except ValueError:
        raise CredentialKeyInvalidError("league credential key is not valid base64") from None
    if len(key) != _KEY_BYTES:
        raise CredentialKeyInvalidError("league credential key must decode to 32 bytes")
    return key


def _decode_token(token: str) -> bytes:
    """Decode and validate the framing of a token; return version, nonce, and ciphertext."""
    try:
        raw = base64.b64decode(token.encode("ascii"), altchars=b"-_", validate=True)
    except ValueError:
        raise CredentialTokenError("credential token is not valid base64url") from None
    if len(raw) < 1 + _NONCE_BYTES + _TAG_BYTES:
        raise CredentialTokenError("credential token is too short")
    if raw[0] != _VERSION:
        raise CredentialTokenError("unsupported credential token version")
    return raw
