"""Tests for Argon2id password hashing (AC-AU-02)."""

from __future__ import annotations

import pytest

from app.security.passwords import hash_password, verify_password


def test_hashes_are_argon2id_with_the_documented_parameters() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$v=19$m=65536,t=3,p=4$")


def test_correct_password_verifies() -> None:
    encoded = hash_password("s3cret-password")
    assert verify_password("s3cret-password", encoded) is True


def test_wrong_password_does_not_verify() -> None:
    encoded = hash_password("s3cret-password")
    assert verify_password("s3cret-passw0rd", encoded) is False
    assert verify_password("", encoded) is False


def test_hashes_are_salted_so_the_same_password_hashes_differently() -> None:
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first != second
    assert verify_password("same-password", first) is True
    assert verify_password("same-password", second) is True
    assert first.split("$")[4] != second.split("$")[4]


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "not-a-hash",
        "$argon2id$",
        "$argon2id$v=19$m=65536,t=3,p=4$truncated",
        "argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA",
    ],
)
def test_malformed_hashes_return_false(encoded: str) -> None:
    assert verify_password("anything", encoded) is False


def test_unicode_and_long_passwords_round_trip() -> None:
    raw = "pässwörd-🔐-" + "a" * 200
    encoded = hash_password(raw)

    assert verify_password(raw, encoded) is True
    assert verify_password(raw + "x", encoded) is False


def test_hash_does_not_contain_the_raw_password() -> None:
    raw = "do-not-leak-this-password"
    assert raw not in hash_password(raw)
