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
import re
import secrets

#: Number of random bytes behind a generated code (``secrets.token_urlsafe`` uses 32 bytes).
INVITE_CODE_BYTES = 32

#: Documented default invite lifetime (AC-AU-01).
DEFAULT_INVITE_LIFETIME_DAYS = 7

#: A decade is far beyond any real invite lifetime and keeps expiry arithmetic inside datetime's
#: range, so an absurd request becomes a validation error rather than a traceback.
MAX_INVITE_LIFETIME_DAYS = 3650

#: URL-safe base64 alphabet produced by :func:`secrets.token_urlsafe`, without padding.
INVITE_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]+")

#: Bounds applied to submitted codes. A generated 32-byte token is 43 characters, so the upper
#: bound leaves room for a longer token without accepting arbitrarily large request bodies.
INVITE_CODE_MIN_LENGTH = 1
INVITE_CODE_MAX_LENGTH = 128


def generate_invite_code() -> str:
    """Return a fresh URL-safe invite code backed by 32 bytes of cryptographic randomness."""
    return secrets.token_urlsafe(INVITE_CODE_BYTES)


def validate_invite_code_format(code: str) -> str:
    """Return ``code`` when it uses the generated URL-safe token alphabet, else raise.

    Only ``A-Z a-z 0-9 _ -`` is accepted, with a length of 1..128. That is the alphabet
    :func:`secrets.token_urlsafe` emits (base64 padding and ``+``/``/`` are never produced), so a
    legitimate generated code always passes while whitespace, quotes, angle brackets, slashes,
    SQL metacharacters, NUL/control characters, and non-ASCII text are rejected. The error message
    is fixed and never repeats the submitted value.
    """
    if (
        not isinstance(code, str)
        or not INVITE_CODE_MIN_LENGTH <= len(code) <= INVITE_CODE_MAX_LENGTH
        or INVITE_CODE_PATTERN.fullmatch(code) is None
    ):
        raise ValueError("invite code must be 1-128 URL-safe token characters")
    return code


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
