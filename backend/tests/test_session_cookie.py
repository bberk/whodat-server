"""Tests for the signed, stateless session cookie.

The cookie carries a user id and issued-at timestamp signed with ``SECRET_KEY``. Invalid input is
always treated as unauthenticated; these tests exercise round-trip, tampering, expiry, malformed
values, and the documented cookie attributes.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import Request, Response

from app.api import session as session_module
from app.api.session import (
    SESSION_CLOCK_SKEW_SECONDS,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    clear_session,
    read_session_user_id,
    set_session,
)
from app.config import get_settings

ISSUED_AT = 1_700_000_000


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _request(cookie: str | None) -> Request:
    headers = [] if cookie is None else [(b"cookie", f"{SESSION_COOKIE_NAME}={cookie}".encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/me",
            "query_string": b"",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


def _set_cookie(user_id: int = 42, *, now: int = ISSUED_AT) -> str:
    response = Response()
    set_session(response, user_id, now=now)
    return response.headers["set-cookie"]


def _cookie_value(user_id: int = 42, *, now: int = ISSUED_AT) -> str:
    return _set_cookie(user_id, now=now).split(";", maxsplit=1)[0].split("=", maxsplit=1)[1]


def test_cookie_name_is_a_single_configurable_constant() -> None:
    assert SESSION_COOKIE_NAME == "whodat_session"


def test_set_and_read_round_trip() -> None:
    cookie = _cookie_value()

    assert read_session_user_id(_request(cookie), now=ISSUED_AT) == 42
    assert read_session_user_id(_request(cookie), now=ISSUED_AT + 10) == 42


def test_cookie_is_valid_just_before_the_seven_day_boundary() -> None:
    cookie = _cookie_value()

    assert read_session_user_id(_request(cookie), now=ISSUED_AT + SESSION_MAX_AGE_SECONDS - 1) == 42
    assert read_session_user_id(_request(cookie), now=ISSUED_AT + SESSION_MAX_AGE_SECONDS) is None


def test_expired_cookie_is_unauthenticated() -> None:
    cookie = _cookie_value()

    assert (
        read_session_user_id(_request(cookie), now=ISSUED_AT + SESSION_MAX_AGE_SECONDS + 1) is None
    )


def test_future_dated_cookie_beyond_skew_is_unauthenticated() -> None:
    cookie = _cookie_value(now=ISSUED_AT)

    too_far_ahead = ISSUED_AT - SESSION_CLOCK_SKEW_SECONDS - 1
    assert read_session_user_id(_request(cookie), now=too_far_ahead) is None
    at_skew = ISSUED_AT - SESSION_CLOCK_SKEW_SECONDS
    assert read_session_user_id(_request(cookie), now=at_skew) == 42


def test_absent_cookie_is_unauthenticated() -> None:
    assert read_session_user_id(_request(None), now=ISSUED_AT) is None
    assert read_session_user_id(_request(""), now=ISSUED_AT) is None


def test_tampered_signature_is_unauthenticated() -> None:
    cookie = _cookie_value()
    tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")

    assert read_session_user_id(_request(tampered), now=ISSUED_AT) is None


def test_tampered_payload_is_unauthenticated() -> None:
    cookie = _cookie_value(user_id=42)
    version, _user_id, issued_at, signature = cookie.split(".")
    forged = f"{version}.43.{issued_at}.{signature}"

    assert read_session_user_id(_request(forged), now=ISSUED_AT) is None


@pytest.mark.parametrize(
    "cookie",
    [
        "not-a-token",
        "v1.42",
        "v1.42.1700000000",
        "v2.42.1700000000.signature",
        "v1.42.1700000000.signature.extra",
    ],
)
def test_malformed_cookie_is_unauthenticated(cookie: str) -> None:
    assert read_session_user_id(_request(cookie), now=ISSUED_AT) is None


def test_signed_but_non_numeric_user_id_is_unauthenticated() -> None:
    payload = f"v1.not-a-number.{ISSUED_AT}"
    cookie = f"{payload}.{session_module._sign(payload)}"

    assert read_session_user_id(_request(cookie), now=ISSUED_AT) is None


def test_signed_but_non_positive_user_id_is_unauthenticated() -> None:
    payload = f"v1.0.{ISSUED_AT}"
    cookie = f"{payload}.{session_module._sign(payload)}"

    assert read_session_user_id(_request(cookie), now=ISSUED_AT) is None


def test_non_ascii_signature_is_unauthenticated_without_raising() -> None:
    assert read_session_user_id(_request("v1.42.1700000000.\xe9"), now=ISSUED_AT) is None


def test_a_different_secret_invalidates_the_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "first-secret")
    get_settings.cache_clear()
    cookie = _cookie_value()

    monkeypatch.setenv("SECRET_KEY", "second-secret")
    get_settings.cache_clear()

    assert read_session_user_id(_request(cookie), now=ISSUED_AT) is None


def test_cookie_attributes_in_local_environment() -> None:
    header = _set_cookie()

    assert header.startswith(f"{SESSION_COOKIE_NAME}=v1.42.{ISSUED_AT}.")
    assert "Path=/" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert f"Max-Age={SESSION_MAX_AGE_SECONDS}" in header
    assert "Secure" not in header


def test_cookie_is_secure_outside_local_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    get_settings.cache_clear()

    header = _set_cookie()

    assert "Secure" in header
    assert "HttpOnly" in header


def test_clear_session_expires_the_cookie() -> None:
    response = Response()
    clear_session(response)
    header = response.headers["set-cookie"]

    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "Max-Age=0" in header
    assert "Path=/" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header


def test_clear_session_marks_the_cookie_secure_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENV", "staging")
    get_settings.cache_clear()

    response = Response()
    clear_session(response)

    assert "Secure" in response.headers["set-cookie"]
