"""Unit tests for the shared text, identifier, and invite-code validators.

These tests exercise the exact shapes the API schemas and the sync service rely on: a narrow
identifier alphabet, the URL-safe invite-code alphabet, and provider display-text normalization.
No database or HTTP layer is involved here; the route and persistence behaviour is covered by the
API and sync-service suites.
"""

from __future__ import annotations

import asyncio
import unicodedata

import pytest
from pydantic import ValidationError

from app.api.body_limit import RequestBodyLimitMiddleware
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


def test_normalize_display_text_preserves_zwj_emoji_sequences() -> None:
    """ZWJ is meaningful in emoji sequences and must survive normalization unchanged."""
    family = "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466"
    pirate_flag = "\U0001f3f4\u200d\u2620\ufe0f"

    assert normalize_display_text(family) == family
    assert normalize_display_text(pirate_flag) == pirate_flag


def test_normalize_display_text_preserves_persian_zwnj() -> None:
    """ZWNJ is part of Persian orthography, so the name is stored exactly as provided."""
    name = "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"  # میخواهم

    assert normalize_display_text(name) == name


def test_normalize_display_text_preserves_indic_zwj_sequences() -> None:
    """Indic conjuncts can carry ZWJ; normalization must not split them apart."""
    name = "\u0915\u094d\u200d\u0937"  # Devanagari ksha with ZWJ

    assert normalize_display_text(name) == name


def test_normalize_display_text_removes_bidi_controls_and_marks() -> None:
    assert normalize_display_text("\u202eEvil\u202c") == "Evil"
    assert normalize_display_text("\u2066a\u2069") == "a"
    assert normalize_display_text("\u061c\u200e\u200f") == ""
    assert normalize_display_text("\ufeffLeague") == "League"


def test_normalize_display_text_preserves_arabic_number_signs() -> None:
    """Arabic number signs are format characters with meaning, not decoration to strip."""
    value = "\u0600\u0661\u0662"

    assert normalize_display_text(value) == value


def test_normalize_display_text_still_strips_nul_and_controls() -> None:
    assert normalize_display_text("a\x00b\x01c\x7fd\x80e") == "abcde"


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


# ---------------------------------------------------------------------------
# Request-body limit middleware internals
# ---------------------------------------------------------------------------


def _http_scope(*, headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, object]:
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": headers or [],
    }


def test_body_limit_passes_non_http_scopes_through() -> None:
    """Lifespan and websocket scopes are not request bodies and must not be buffered."""
    asyncio.run(_assert_non_http_scope())


async def _assert_non_http_scope() -> None:
    seen: list[str] = []

    async def app(scope: dict[str, object], receive: object, send: object) -> None:
        seen.append(str(scope["type"]))

    async def receive() -> dict[str, object]:
        return {"type": "lifespan.startup"}

    async def send(_message: dict[str, object]) -> None:
        return None

    await RequestBodyLimitMiddleware(app)({"type": "lifespan"}, receive, send)  # type: ignore[arg-type]
    assert seen == ["lifespan"]


def test_body_limit_returns_without_calling_the_app_on_disconnect() -> None:
    """A client that disconnects before sending a body is not passed to the application."""
    asyncio.run(_assert_disconnect())


async def _assert_disconnect() -> None:
    called = False

    async def app(scope: object, receive: object, send: object) -> None:
        nonlocal called
        called = True

    async def receive() -> dict[str, object]:
        return {"type": "http.disconnect"}

    async def send(_message: dict[str, object]) -> None:
        return None

    await RequestBodyLimitMiddleware(app)(_http_scope(), receive, send)  # type: ignore[arg-type]
    assert called is False


@pytest.mark.parametrize("declared", [b"not-a-number", b"-1"])
def test_body_limit_ignores_malformed_or_negative_content_length(declared: bytes) -> None:
    """Only a valid non-negative Content-Length can trigger the early declaration check."""
    asyncio.run(_assert_body_replayed([(b"content-length", declared)], [b"payload"]))


def test_body_limit_replays_chunked_messages_and_serves_a_second_receive() -> None:
    """Multiple more_body chunks are joined; a later receive reaches the original stream."""
    asyncio.run(_assert_chunked_replay())


async def _assert_body_replayed(headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> None:
    bodies: list[bytes] = []

    async def app(scope: object, receive: object, send: object) -> None:
        message = await receive()  # type: ignore[operator]
        bodies.append(message["body"])

    remaining = list(chunks)

    async def receive() -> dict[str, object]:
        chunk = remaining.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(remaining)}

    async def send(_message: dict[str, object]) -> None:
        return None

    await RequestBodyLimitMiddleware(app)(_http_scope(headers=headers), receive, send)  # type: ignore[arg-type]
    assert bodies == [b"".join(chunks)]


async def _assert_chunked_replay() -> None:
    messages: list[dict[str, object]] = [
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"cd", "more_body": False},
    ]
    received: list[dict[str, object]] = []

    async def app(scope: object, receive: object, send: object) -> None:
        received.append(await receive())  # type: ignore[operator]
        received.append(await receive())  # type: ignore[operator]

    async def receive() -> dict[str, object]:
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(_message: dict[str, object]) -> None:
        return None

    await RequestBodyLimitMiddleware(app)(_http_scope(), receive, send)  # type: ignore[arg-type]
    assert received[0] == {"type": "http.request", "body": b"abcd", "more_body": False}
    assert received[1] == {"type": "http.disconnect"}


def test_validators_reject_non_text_input_without_echoing_it() -> None:
    """Programmatic callers get the same fixed errors as HTTP callers."""
    with pytest.raises(ValueError):
        normalize_external_id(None)  # type: ignore[arg-type]
    assert normalize_display_text(None) == ""  # type: ignore[arg-type]
