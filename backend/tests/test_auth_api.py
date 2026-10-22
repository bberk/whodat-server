"""End-to-end auth route tests with FastAPI's TestClient and temporary SQLite databases.

Covers the public contract (201 signup, 200 login/me/logout, 401 unauthenticated, 409 duplicate
email, 400 invalid invite, 429 rate limit), cookie attributes, and the absence of secret material
in responses and logs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api import deps
from app.api.main import create_app
from app.api.rate_limit import RateLimiter
from app.api.schemas_auth import LoginRequest, SignupRequest
from app.api.session import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, set_session
from app.db.auth_repositories import InviteRepository
from app.db.base import Base
from app.db.models import AppUser, League, UserLeague
from app.db.session import get_session as db_get_session
from app.security.invite_codes import hash_invite_code
from app.security.passwords import verify_password
from app.services.sync_service import PROVIDER_CONFIG_REF

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "another-strong-password"


class FakeClock:
    """A deterministic clock for the injected rate limiter."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Api:
    """A test application plus the database and limiter it uses."""

    client: TestClient
    factory: sessionmaker[Session]
    engine: Engine
    clock: FakeClock
    limiter: RateLimiter


@pytest.fixture
def api_factory(tmp_path: Path) -> Iterator[Callable[..., Api]]:
    """Build isolated applications that share nothing but their route definitions."""
    engines: list[Engine] = []

    def build(*, rate_limit: int = 10) -> Api:
        engine = create_engine(f"sqlite:///{tmp_path / f'auth-{len(engines)}.db'}")
        Base.metadata.create_all(engine)
        engines.append(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        clock = FakeClock()
        limiter = RateLimiter(limit=rate_limit, clock=clock)
        app = create_app()

        def override_session() -> Iterator[Session]:
            with factory() as session:
                yield session

        app.dependency_overrides[db_get_session] = override_session
        app.dependency_overrides[deps.get_rate_limiter] = lambda: limiter
        return Api(
            client=TestClient(app),
            factory=factory,
            engine=engine,
            clock=clock,
            limiter=limiter,
        )

    try:
        yield build
    finally:
        for engine in engines:
            Base.metadata.drop_all(engine)
            engine.dispose()


def _seed_invite(
    factory: sessionmaker[Session],
    *,
    code: str = "valid-invite-code",
    role: str = "member",
    expires_at: datetime | None = None,
) -> str:
    """Create a role-appropriate invite, returning the raw code.

    Member invites are bound to a league; admin invites are league-less (AC-AU-17).
    """
    with factory() as session:
        league_id = None
        if role == "member":
            league = League(
                provider="fake",
                external_id=f"league-{hash_invite_code(code)[:16]}",
                name="League",
                league_metadata={},
                provider_config_ref="ref",
            )
            session.add(league)
            session.flush()
            league_id = league.id
        InviteRepository(session).create(
            league_id,
            hash_invite_code(code),
            expires_at or (datetime.now(UTC) + timedelta(days=7)),
            role=role,
        )
        session.commit()
    return code


def _count(factory: sessionmaker[Session], model: type[Base]) -> int:
    with factory() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _signup(client: TestClient, code: str, email: str = "fan@example.com") -> object:
    return client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "invite_code": code},
    )


def test_AC_AU_01_signup_returns_201_public_user_and_session_cookie(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    code = _seed_invite(api.factory, role="admin")

    response = api.client.post(
        "/api/v1/auth/signup",
        json={"email": "  Fan@Example.COM ", "password": PASSWORD, "invite_code": code},
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email", "role", "league"}
    assert body["email"] == "fan@example.com"
    assert body["role"] == "admin"
    assert body["league"] is None

    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE_NAME}=v1.")
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Path=/" in header
    assert f"Max-Age={SESSION_MAX_AGE_SECONDS}" in header

    with api.factory() as session:
        user = session.scalar(select(AppUser))
        assert user is not None
        assert user.email == "fan@example.com"
        assert verify_password(PASSWORD, user.password_hash) is True
    assert _count(api.factory, UserLeague) == 0


def test_AC_AU_01_member_signup_returns_the_league_and_creates_the_membership(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    code = _seed_invite(api.factory, code="member-code")
    with api.factory() as session:
        league = session.scalar(select(League))
        assert league is not None
        league_id = league.id

    response = _signup(api.client, code)

    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "member"
    assert body["league"] == {
        "league_id": league_id,
        "provider": "fake",
        "external_id": f"league-{hash_invite_code(code)[:16]}",
        "name": "League",
    }
    assert code not in response.text
    with api.factory() as session:
        membership = session.scalar(select(UserLeague))
        assert membership is not None
        assert membership.league_id == league_id
        assert membership.espn_s2_encrypted is None
        assert membership.espn_swid_encrypted is None


def test_AC_AU_02_duplicate_email_returns_409_case_insensitively(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    code = _seed_invite(api.factory)

    assert _signup(api.client, code, "Fan@Example.com").status_code == 201
    response = _signup(api.client, code, "FAN@EXAMPLE.COM")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "email_taken"
    assert _count(api.factory, AppUser) == 1


def test_AC_AU_01_unknown_invite_returns_400(api_factory: Callable[..., Api]) -> None:
    api = api_factory()

    response = _signup(api.client, "unknown-code")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_invite"
    assert _count(api.factory, AppUser) == 0


def test_AC_AU_01_expired_invite_returns_400(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    code = _seed_invite(
        api.factory,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    response = _signup(api.client, code)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_invite"
    assert _count(api.factory, AppUser) == 0


def test_signup_validation_errors_are_structured_4xx(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    client = api.client

    missing = client.post("/api/v1/auth/signup", json={})
    bad_email = client.post(
        "/api/v1/auth/signup",
        json={"email": "not-an-email", "password": PASSWORD, "invite_code": "code"},
    )
    empty_local = client.post(
        "/api/v1/auth/signup",
        json={"email": "@example.com", "password": PASSWORD, "invite_code": "code"},
    )
    short_password = client.post(
        "/api/v1/auth/signup",
        json={"email": "fan@example.com", "password": "short", "invite_code": "code"},
    )

    for response in (missing, bad_email, empty_local, short_password):
        assert 400 <= response.status_code < 500
        assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize(
    "email",
    [
        "fan\x00@example.com",
        "fan\x01@example.com",
        "fan\n@example.com",
        "fan\t@example.com",
        "fan\x7f@example.com",
        "fan\u200b@example.com",
    ],
)
def test_auth_schemas_reject_control_characters_in_email(email: str) -> None:
    """Validation rejects NUL and other controls before any database lookup (both engines)."""
    with pytest.raises(ValidationError):
        SignupRequest(email=email, password=PASSWORD, invite_code="valid-invite-code")
    with pytest.raises(ValidationError):
        LoginRequest(email=email, password=PASSWORD)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password", "valid-password\x00suffix"),
        ("invite_code", "valid-code\x00suffix"),
    ],
)
def test_signup_schema_rejects_control_characters_in_other_text(
    field: str,
    value: str,
) -> None:
    payload = {"email": "fan@example.com", "password": PASSWORD, "invite_code": "valid-code"}
    payload[field] = value

    with pytest.raises(ValidationError):
        SignupRequest(**payload)


def test_nul_in_email_returns_structured_422_not_500(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()

    response = api.client.post(
        "/api/v1/auth/signup",
        json={
            "email": "fan\x00@example.com",
            "password": PASSWORD,
            "invite_code": "valid-invite-code",
        },
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert "Traceback" not in response.text
    assert _count(api.factory, AppUser) == 0

    login = api.client.post(
        "/api/v1/auth/login",
        json={"email": "fan\x00@example.com", "password": PASSWORD},
    )
    assert login.status_code == 422
    assert "Traceback" not in login.text


def test_validation_errors_do_not_echo_password_or_invite_code(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    secret_password = "Sup3rSecretPassword"
    secret_code = "SuperSecretInviteCode"

    bad_email = api.client.post(
        "/api/v1/auth/signup",
        json={"email": "not-an-email", "password": secret_password, "invite_code": secret_code},
    )
    short_password = api.client.post(
        "/api/v1/auth/signup",
        json={
            "email": "fan@example.com",
            "password": "zqxjk",
            "invite_code": secret_code,
        },
    )

    for response in (bad_email, short_password):
        assert response.status_code == 422
        assert secret_password not in response.text
        assert secret_code not in response.text
        assert "zqxjk" not in response.text
        assert all("input" not in error for error in response.json()["detail"])
        assert all("ctx" not in error for error in response.json()["detail"])


def test_AC_AU_04_login_sets_a_session_cookie(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    code = _seed_invite(api.factory)
    assert _signup(api.client, code).status_code == 201
    api.client.cookies.clear()

    response = api.client.post(
        "/api/v1/auth/login",
        json={"email": "FAN@example.com", "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "fan@example.com"
    assert response.headers["set-cookie"].startswith(f"{SESSION_COOKIE_NAME}=")


def test_AC_AU_04_unknown_email_and_wrong_password_return_the_same_401(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    code = _seed_invite(api.factory)
    assert _signup(api.client, code).status_code == 201
    api.client.cookies.clear()

    wrong_password = api.client.post(
        "/api/v1/auth/login",
        json={"email": "fan@example.com", "password": "wrong-password"},
    )
    unknown_email = api.client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": PASSWORD},
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["detail"]["code"] == "invalid_credentials"


def test_me_returns_the_current_user_and_401_without_a_session(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    code = _seed_invite(api.factory)
    created = _signup(api.client, code).json()

    authenticated = api.client.get("/api/v1/me")
    api.client.cookies.clear()
    unauthenticated = api.client.get("/api/v1/me")

    assert authenticated.status_code == 200
    body = authenticated.json()
    assert body == {
        "id": created["id"],
        "email": created["email"],
        "role": created["role"],
        "has_league": True,
    }
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"]["code"] == "not_authenticated"


def test_AC_AU_14_me_has_league_is_false_only_until_a_league_is_held(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    admin_code = _seed_invite(api.factory, code="admin-code", role="admin")
    member_code = _seed_invite(api.factory, code="member-code")

    assert _signup(api.client, admin_code, "admin@example.com").status_code == 201
    onboarding = api.client.get("/api/v1/me").json()

    assert onboarding["role"] == "admin"
    assert onboarding["has_league"] is False

    assert _signup(api.client, member_code, "member@example.com").status_code == 201
    onboarded = api.client.get("/api/v1/me").json()

    assert onboarded["role"] == "member"
    assert onboarded["has_league"] is True


def test_AC_AU_14_me_with_two_memberships_uses_one_existence_check(
    api_factory: Callable[..., Api],
) -> None:
    """A second membership must not turn has_league into a per-league query."""
    api = api_factory()
    member_code = _seed_invite(api.factory, code="member-code")
    assert _signup(api.client, member_code, "member@example.com").status_code == 201

    with api.factory() as session:
        user = session.scalar(select(AppUser).where(AppUser.email == "member@example.com"))
        assert user is not None
        second_league = League(
            provider="fake",
            external_id="second-league",
            name="Second League",
            league_metadata={},
            provider_config_ref=PROVIDER_CONFIG_REF,
        )
        session.add(second_league)
        session.flush()
        session.add(UserLeague(user_id=user.id, league_id=second_league.id))
        session.commit()

    statements: list[str] = []

    def capture(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(api.engine, "before_cursor_execute", capture)
    try:
        response = api.client.get("/api/v1/me")
    finally:
        event.remove(api.engine, "before_cursor_execute", capture)

    assert response.status_code == 200
    assert response.json()["has_league"] is True
    existence_checks = [sql for sql in statements if "FROM user_league" in sql]
    assert len(existence_checks) == 1
    assert "LIMIT" in existence_checks[0]


def test_me_rejects_a_tampered_cookie(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    code = _seed_invite(api.factory)
    assert _signup(api.client, code).status_code == 201
    api.client.cookies.set(SESSION_COOKIE_NAME, "v1.1.1.not-a-real-signature")

    response = api.client.get("/api/v1/me")

    assert response.status_code == 401


def test_logout_clears_the_cookie_and_is_idempotent(api_factory: Callable[..., Api]) -> None:
    api = api_factory()
    code = _seed_invite(api.factory)
    assert _signup(api.client, code).status_code == 201

    response = api.client.post("/api/v1/auth/logout")
    without_session = api.client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert without_session.status_code == 200
    assert api.client.get("/api/v1/me").status_code == 401


def test_AC_AU_11_signup_is_throttled_with_retry_after(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory(rate_limit=2)
    code = _seed_invite(api.factory)

    first = _signup(api.client, code, "first@example.com")
    second = _signup(api.client, code, "second@example.com")
    throttled = _signup(api.client, code, "third@example.com")

    assert first.status_code == 201
    assert second.status_code == 201
    assert throttled.status_code == 429
    assert throttled.headers["Retry-After"] == "60"
    assert throttled.json()["detail"]["code"] == "rate_limited"

    api.clock.advance(60)
    after_reset = _signup(api.client, code, "fourth@example.com")
    assert after_reset.status_code == 201


def test_AC_AU_11_rate_limit_is_per_route(api_factory: Callable[..., Api]) -> None:
    api = api_factory(rate_limit=1)

    assert _signup(api.client, "bad-code").status_code == 400
    assert _signup(api.client, "bad-code").status_code == 429
    login = api.client.post(
        "/api/v1/auth/login",
        json={"email": "fan@example.com", "password": PASSWORD},
    )

    assert login.status_code == 401
    assert login.json()["detail"]["code"] == "invalid_credentials"


def test_responses_and_logs_never_contain_secret_material(
    api_factory: Callable[..., Api],
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = api_factory()
    raw_code = _seed_invite(api.factory, code="super-secret-invite-code")
    caplog.set_level(logging.DEBUG)

    signup = _signup(api.client, raw_code)
    api.client.cookies.clear()
    failed_login = api.client.post(
        "/api/v1/auth/login",
        json={"email": "fan@example.com", "password": "wrong-secret-password"},
    )

    exposed = f"{signup.text}\n{failed_login.text}\n{caplog.text}"
    for secret in (
        PASSWORD,
        "wrong-secret-password",
        raw_code,
        "$argon2",
        "password_hash",
        "code_hash",
    ):
        assert secret not in exposed


def test_login_does_not_create_or_log_an_account_for_unknown_email(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()

    response = api.client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": NEW_PASSWORD},
    )

    assert response.status_code == 401
    assert _count(api.factory, AppUser) == 0


def test_me_rejects_a_valid_cookie_for_a_missing_account(
    api_factory: Callable[..., Api],
) -> None:
    api = api_factory()
    response = Response()
    set_session(response, 999_999)
    cookie = response.headers["set-cookie"].split(";", maxsplit=1)[0].split("=", maxsplit=1)[1]
    api.client.cookies.set(SESSION_COOKIE_NAME, cookie)

    me = api.client.get("/api/v1/me")

    assert me.status_code == 401
    assert me.json()["detail"]["code"] == "not_authenticated"


def test_default_rate_limiter_is_a_process_singleton() -> None:
    assert deps.get_rate_limiter() is deps.get_rate_limiter()


# ---------------------------------------------------------------------------
# Input hardening: invite-code alphabet and hostile text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "invite_code",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "' OR 1=1 --",
        '"; DROP TABLE app_user; --',
        "with space",
        "with/slash",
        "with\x00nul",
        "with\u202ertl",
        "with\u200bzero-width",
        "x" * 10_000,
    ],
)
def test_signup_rejects_invite_codes_outside_the_generated_alphabet(
    api_factory: Callable[..., Api], invite_code: str
) -> None:
    """A malformed invite code is a structured 422 and never reaches the invite lookup."""
    api = api_factory()

    response = _signup(api.client, invite_code)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert invite_code not in response.text
    assert all("input" not in error for error in response.json()["detail"])
    assert _count(api.factory, AppUser) == 0


@pytest.mark.parametrize(
    "email",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "' OR 1=1 --",
        '"; DROP TABLE app_user; --',
        "x" * 10_000,
    ],
)
def test_signup_and_login_reject_hostile_email_payloads_without_query_errors(
    api_factory: Callable[..., Api], email: str
) -> None:
    """Email shape checks reject markup, SQL metacharacters, and oversized values before lookup."""
    api = api_factory()
    payload = {"email": email, "password": PASSWORD, "invite_code": "valid-invite-code"}

    signup = api.client.post("/api/v1/auth/signup", json=payload)
    login = api.client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})

    for response in (signup, login):
        assert response.status_code == 422
        assert email not in response.text
        lowered = response.text.lower()
        for marker in ("operationalerror", "syntax error", "traceback", "sqlalchemy"):
            assert marker not in lowered
    assert _count(api.factory, AppUser) == 0

    # The table is still present and queryable after every hostile request.
    with api.factory() as session:
        assert session.scalar(select(func.count()).select_from(AppUser)) == 0
