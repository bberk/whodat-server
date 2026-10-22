"""Unit tests for the shared text, identifier, and invite-code validators.

These tests exercise the exact shapes the API schemas and the sync service rely on: a narrow
identifier alphabet, the URL-safe invite-code alphabet, and provider display-text normalization.
No database or HTTP layer is involved here; the route and persistence behaviour is covered by the
API and sync-service suites.
"""

from __future__ import annotations

import unicodedata

import pytest
from pydantic import ValidationError

from app.api.schemas_auth import SignupRequest
from app.api.schemas_leagues import AddLeagueRequest, RedeemInviteRequest
from app.security.invite_codes import (
    INVITE_CODE_MAX_LENGTH,
    generate_invite_code,
    validate_invite_code_format,
)
from app.validation import (
    MAX_DISPLAY_TEXT_LENGTH,
    MAX_EXTERNAL_ID_LENGTH,
    normalize_display_text,
    normalize_external_id,
)

PASSWORD = "correct-horse-battery"


# ---------------------------------------------------------------------------
# External provider ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12345", "12345"),
        (" 12345 ", "12345"),
        ("e2e-fixture-league", "e2e-fixture-league"),
        ("A.b_c-9", "A.b_c-9"),
        ("a" * MAX_EXTERNAL_ID_LENGTH, "a" * MAX_EXTERNAL_ID_LENGTH),
    ],
)
def test_normalize_external_id_accepts_provider_shaped_ids(value: str, expected: str) -> None:
    assert normalize_external_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "' OR 1=1 --",
        '"; DROP TABLE app_user; --',
        "a/b",
        "a\\b",
        "a b",
        "a\tb",
        "a\nb",
        "a\x00b",
        "a\x01b",
        "\u202eevil\u200b",
        "a" * (MAX_EXTERNAL_ID_LENGTH + 1),
    ],
)
def test_normalize_external_id_rejects_malformed_or_hostile_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_external_id(value)


def test_add_league_request_accepts_current_fixtures_and_rejects_hostile_ids() -> None:
    assert AddLeagueRequest(espn_league_id="12345").espn_league_id == "12345"
    assert (
        AddLeagueRequest(espn_league_id="e2e-fixture-league").espn_league_id == "e2e-fixture-league"
    )
    assert AddLeagueRequest(espn_league_id="  espn-league-1  ").espn_league_id == "espn-league-1"

    for value in (
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "' OR 1=1 --",
        '"; DROP TABLE app_user; --',
        "a/b",
        "a\x00b",
        "a" * (MAX_EXTERNAL_ID_LENGTH + 1),
    ):
        with pytest.raises(ValidationError):
            AddLeagueRequest(espn_league_id=value)


# ---------------------------------------------------------------------------
# Provider display text
# ---------------------------------------------------------------------------


def test_normalize_display_text_strips_controls_formats_and_collapses_whitespace() -> None:
    value = "\u202eE\u0301vil\x00<script>alert(1)</script>\n\t  League\u200b"

    normalized = normalize_display_text(value)

    assert normalized == "Évil<script>alert(1)</script> League"
    assert unicodedata.normalize("NFC", normalized) == normalized
    assert all(
        unicodedata.category(character) not in {"Cc", "Cf", "Zl", "Zp", "Cs"}
        for character in normalized
    )


def test_normalize_display_text_keeps_html_literal_rather_than_escaping_it() -> None:
    assert (
        normalize_display_text('<img src=x onerror="alert(1)">') == '<img src=x onerror="alert(1)">'
    )


def test_normalize_display_text_caps_pathological_length() -> None:
    normalized = normalize_display_text("x" * 10_000)

    assert len(normalized) == MAX_DISPLAY_TEXT_LENGTH
    assert normalized == "x" * MAX_DISPLAY_TEXT_LENGTH


def test_normalize_display_text_returns_empty_for_only_unsafe_characters() -> None:
    assert normalize_display_text("\x00\x01\u200b\u202e\u2028") == ""
    assert normalize_display_text("   ") == ""


# ---------------------------------------------------------------------------
# Invite codes
# ---------------------------------------------------------------------------


def test_generated_invite_codes_pass_the_http_validator() -> None:
    for _ in range(50):
        code = generate_invite_code()
        assert validate_invite_code_format(code) == code


@pytest.mark.parametrize(
    "code",
    [
        "valid-code",
        "e2e-admin-invite-code",
        "e2e-member-invite-code",
        "super-secret-invite-code",
        "a" * INVITE_CODE_MAX_LENGTH,
    ],
)
def test_invite_validator_accepts_existing_fixtures_and_boundary_length(code: str) -> None:
    assert validate_invite_code_format(code) == code


@pytest.mark.parametrize(
    "code",
    [
        "",
        "a" * (INVITE_CODE_MAX_LENGTH + 1),
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "' OR 1=1 --",
        '"; DROP TABLE app_user; --',
        "with space",
        "with/slash",
        "with+plus",
        "with=padding",
        "with\x00nul",
        "with\u202ertl",
        "with\u200bzero-width",
    ],
)
def test_invite_validator_rejects_non_token_values(code: str) -> None:
    with pytest.raises(ValueError):
        validate_invite_code_format(code)


def test_signup_and_redeem_schemas_apply_the_invite_charset() -> None:
    assert (
        SignupRequest(
            email="fan@example.com",
            password=PASSWORD,
            invite_code="e2e-member-invite-code",
        ).invite_code.get_secret_value()
        == "e2e-member-invite-code"
    )
    assert (
        RedeemInviteRequest(invite_code="valid-code").invite_code.get_secret_value() == "valid-code"
    )

    for value in ("<script>alert(1)</script>", "' OR 1=1 --", "with space", "with\x00nul"):
        with pytest.raises(ValidationError):
            SignupRequest(email="fan@example.com", password=PASSWORD, invite_code=value)
        with pytest.raises(ValidationError):
            RedeemInviteRequest(invite_code=value)
