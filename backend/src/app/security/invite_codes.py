"""Generate and verify one-way invite codes.

An invite code is a high-entropy URL-safe token. Only its SHA-256 hex digest is persisted (see
``invite.code_hash``); the raw code is returned to the admin once at creation and is never stored
or logged by this module.

Hashing is deliberately deterministic: signup receives the raw code, hashes it, and looks the
digest up. Because the digest compares fixed-length hexadecimal strings, the comparison helper can
use :func:`hmac.compare_digest` without leaking timing information about how much of a guessed
code matched.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

#: Number of random bytes behind a generated code (``secrets.token_urlsafe`` uses 32 bytes).
INVITE_CODE_BYTES = 32


def generate_invite_code() -> str:
    """Return a fresh URL-safe invite code backed by 32 bytes of cryptographic randomness."""
    return secrets.token_urlsafe(INVITE_CODE_BYTES)


def hash_invite_code(code: str) -> str:
    """Return the deterministic lowercase SHA-256 hex digest stored for ``code``.

    The digest is one-way, so a database leak does not reveal usable invite codes. Empty input is
    rejected rather than hashed into a predictable digest for the empty string.
    """
    if not isinstance(code, str) or not code:
        raise ValueError("invite code must not be empty")
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def invite_code_matches(code: str, expected_hash: str) -> bool:
    """Return whether ``code`` hashes to ``expected_hash``, comparing in constant time.

    Malformed or empty inputs return ``False`` instead of raising, so callers can treat a stored
    hash as untrusted data.
    """
    if not code or not expected_hash:
        return False
    try:
        candidate = hash_invite_code(code)
    except TypeError, ValueError:
        return False
    return hmac.compare_digest(candidate, expected_hash)
