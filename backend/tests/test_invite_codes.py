"""Tests for invite-code generation and one-way hashing (AC-AU-01)."""

from __future__ import annotations

import hmac
import re
from unittest.mock import patch

import pytest

from app.security import invite_codes
from app.security.invite_codes import (
    generate_invite_code,
    hash_invite_code,
    invite_code_matches,
)


def test_generated_codes_are_unique_url_safe_tokens() -> None:
    codes = {generate_invite_code() for _ in range(50)}

    assert len(codes) == 50
    for code in codes:
        assert re.fullmatch(r"[A-Za-z0-9_-]+", code)
        # token_urlsafe(32) produces 43 characters without padding.
        assert len(code) == 43


def test_raw_code_never_equals_its_hash() -> None:
    code = generate_invite_code()
    digest = hash_invite_code(code)

    assert digest != code
    assert code not in digest


def test_hashing_is_deterministic_and_lowercase_sha256_hex() -> None:
    code = "a-fixed-invite-code"

    first = hash_invite_code(code)
    second = hash_invite_code(code)

    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first)


def test_different_codes_hash_differently() -> None:
    assert hash_invite_code("code-one") != hash_invite_code("code-two")


def test_hasher_rejects_empty_and_non_string_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        hash_invite_code("")
    with pytest.raises(ValueError, match="must not be empty"):
        hash_invite_code(None)  # type: ignore[arg-type]


def test_constant_time_helper_accepts_the_matching_code() -> None:
    code = generate_invite_code()
    assert invite_code_matches(code, hash_invite_code(code)) is True


def test_constant_time_helper_rejects_wrong_empty_and_malformed_values() -> None:
    code = generate_invite_code()
    digest = hash_invite_code(code)

    assert invite_code_matches("wrong-code", digest) is False
    assert invite_code_matches("", digest) is False
    assert invite_code_matches(code, "") is False
    assert invite_code_matches(code, "not-a-digest") is False
    assert invite_code_matches(None, digest) is False  # type: ignore[arg-type]
    assert invite_code_matches(123, digest) is False  # type: ignore[arg-type]


def test_constant_time_helper_uses_compare_digest() -> None:
    code = generate_invite_code()
    digest = hash_invite_code(code)

    with patch.object(
        invite_codes.hmac, "compare_digest", wraps=hmac.compare_digest
    ) as compare_digest:
        assert invite_code_matches(code, digest) is True

    compare_digest.assert_called_once_with(digest, digest)
