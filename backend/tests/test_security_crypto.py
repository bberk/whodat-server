"""Tests for AES-256-GCM league-credential encryption (AC-AU-02)."""

from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings
from app.security import crypto
from app.security.crypto import (
    CredentialDecryptionError,
    CredentialKeyInvalidError,
    CredentialKeyMissingError,
    CredentialTokenError,
    decrypt,
    encrypt,
)

_KEY_A = bytes(range(32))
_KEY_B = bytes(range(32, 64))


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    """Clear the cached settings before and after each test so key changes are isolated."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configure_key(monkeypatch: pytest.MonkeyPatch, key: bytes | str | None) -> None:
    if key is None:
        monkeypatch.delenv("LEAGUE_CREDENTIALS_KEY", raising=False)
    elif isinstance(key, str):
        monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", key)
    else:
        monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", base64.b64encode(key).decode("ascii"))
    get_settings.cache_clear()


def _raw_token(token: str) -> bytes:
    return base64.urlsafe_b64decode(token.encode("ascii"))


def _encode_token(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def test_round_trip_returns_the_original_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_key(monkeypatch, _KEY_A)
    plaintext = "espn_s2=cookie-value; SWID={owner-id}; naïve-ünïcode"
    assert decrypt(encrypt(plaintext)) == plaintext


def test_each_call_uses_a_fresh_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_key(monkeypatch, _KEY_A)
    first, second = encrypt("same plaintext"), encrypt("same plaintext")

    assert first != second
    first_nonce = _raw_token(first)[1 : 1 + crypto._NONCE_BYTES]
    second_nonce = _raw_token(second)[1 : 1 + crypto._NONCE_BYTES]
    assert first_nonce != second_nonce
    assert decrypt(first) == decrypt(second) == "same plaintext"


def test_token_layout_is_version_nonce_ciphertext(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_key(monkeypatch, _KEY_A)
    plaintext = "abc"
    raw = _raw_token(encrypt(plaintext))

    assert raw[0] == crypto._VERSION
    assert len(raw[1 : 1 + crypto._NONCE_BYTES]) == 12
    assert len(raw[1 + crypto._NONCE_BYTES : -crypto._TAG_BYTES]) == len(plaintext.encode())
    assert len(raw[-crypto._TAG_BYTES :]) == 16
    assert len(raw) == 1 + crypto._NONCE_BYTES + len(plaintext) + crypto._TAG_BYTES


@pytest.mark.parametrize("offset", [-1, 13])
def test_flipping_a_token_byte_is_detected(monkeypatch: pytest.MonkeyPatch, offset: int) -> None:
    _configure_key(monkeypatch, _KEY_A)
    raw = bytearray(_raw_token(encrypt("tamper-me")))
    raw[offset] ^= 0x01

    with pytest.raises(CredentialDecryptionError) as excinfo:
        decrypt(_encode_token(bytes(raw)))
    assert "tamper-me" not in str(excinfo.value)


def test_decrypting_with_a_different_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_key(monkeypatch, _KEY_A)
    token = encrypt("only-key-a-can-read")

    _configure_key(monkeypatch, _KEY_B)
    with pytest.raises(CredentialDecryptionError):
        decrypt(token)


def test_unknown_version_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_key(monkeypatch, _KEY_A)
    raw = bytearray(_raw_token(encrypt("versioned")))
    raw[0] = crypto._VERSION + 1

    with pytest.raises(CredentialTokenError):
        decrypt(_encode_token(bytes(raw)))


@pytest.mark.parametrize(
    "token",
    [
        "",
        "!!!!",
        "é",
        _encode_token(b"\x01" + b"short"),
        _encode_token(bytes([1]) + b"\x00" * 12 + b"\x00" * 15),
    ],
)
def test_malformed_tokens_are_rejected(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    _configure_key(monkeypatch, _KEY_A)
    with pytest.raises(CredentialTokenError):
        decrypt(token)


def test_non_utf8_plaintext_is_rejected_with_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token that authenticates but is not UTF-8 text fails with a typed error."""
    _configure_key(monkeypatch, _KEY_A)
    nonce = b"\x00" * crypto._NONCE_BYTES
    ciphertext = AESGCM(_KEY_A).encrypt(nonce, b"\xff\xfe", crypto._AAD)
    token = _encode_token(bytes([crypto._VERSION]) + nonce + ciphertext)

    with pytest.raises(CredentialDecryptionError):
        decrypt(token)


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_key_raises_a_typed_error(
    monkeypatch: pytest.MonkeyPatch, missing: str | None
) -> None:
    _configure_key(monkeypatch, missing)
    with pytest.raises(CredentialKeyMissingError):
        encrypt("anything")


@pytest.mark.parametrize(
    "configured",
    [
        "not-base64!!!",
        base64.b64encode(b"x" * 31).decode("ascii"),
        base64.b64encode(b"x" * 33).decode("ascii"),
    ],
)
def test_malformed_key_raises_a_typed_error(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    _configure_key(monkeypatch, configured)
    with pytest.raises(CredentialKeyInvalidError) as excinfo:
        encrypt("anything")
    assert configured not in str(excinfo.value)


def test_decrypt_reports_missing_key_before_parsing_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_key(monkeypatch, None)
    with pytest.raises(CredentialKeyMissingError):
        decrypt("not-even-a-token")
