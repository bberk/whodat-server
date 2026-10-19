"""Argon2id password hashing for user accounts (AC-AU-02).

Salt and parameters are encoded in each hash, so verification works across parameter changes.
The parameters are pinned explicitly rather than taken from library defaults so a dependency
upgrade cannot silently lower the work factor:

============  ==========================================================
``time_cost``  3 passes
``memory_cost`` 65,536 KiB (64 MiB)
``parallelism`` 4 lanes
``hash_len``   32 bytes
``salt_len``   16 bytes (fresh random salt per hash)
``type``       Argon2id
============  ==========================================================

These are above the OWASP minimum (19 MiB, two passes, one lane) and suit a server that hashes
only on signup and login. Raw passwords are never logged and never returned by these helpers.
"""

from __future__ import annotations

from argon2 import PasswordHasher, Type
from argon2.exceptions import Argon2Error

_TIME_COST = 3
_MEMORY_COST = 65_536
_PARALLELISM = 4
_HASH_LEN = 32
_SALT_LEN = 16

_hasher = PasswordHasher(
    time_cost=_TIME_COST,
    memory_cost=_MEMORY_COST,
    parallelism=_PARALLELISM,
    hash_len=_HASH_LEN,
    salt_len=_SALT_LEN,
    type=Type.ID,
)


def hash_password(raw: str) -> str:
    """Return a salted Argon2id hash (a PHC string) for ``raw``.

    Every call generates a fresh random salt, so hashing the same password twice returns
    different encoded hashes. Raises :class:`argon2.exceptions.HashingError` only when the
    library cannot allocate or hash; the raw password is not included in the error.
    """
    return _hasher.hash(raw)


def verify_password(raw: str, encoded: str) -> bool:
    """Return whether ``raw`` matches the Argon2id hash in ``encoded``.

    Verification is constant-time inside argon2-cffi. Non-string or empty inputs (including a
    malformed, truncated, or unparseable stored hash) return ``False`` rather than raising, so
    callers can treat a stored value as untrusted input.
    """
    if not isinstance(raw, str) or not isinstance(encoded, str) or not raw or not encoded:
        return False
    try:
        return _hasher.verify(encoded, raw)
    except Argon2Error, ValueError, TypeError:
        return False
