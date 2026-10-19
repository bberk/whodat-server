"""Service-level tests for invite-gated signup and login (AC-AU-01..04, AC-AU-11)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.auth_repositories import InviteRepository, UserRepository
from app.db.base import Base
from app.db.models import AppUser, League, UserLeague
from app.security.invite_codes import hash_invite_code
from app.security.passwords import verify_password
from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    ExpiredInviteError,
    InactiveUserError,
    InvalidCredentialsError,
    InviteError,
    UserNotFoundError,
)

PASSWORD = "correct-horse-battery"


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    """Provide a file-backed SQLite database so uncommitted work is invisible to other sessions."""
    engine = create_engine(f"sqlite:///{tmp_path / 'auth-service.db'}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db_session:
            yield db_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_invite(
    session: Session,
    *,
    code: str = "valid-invite-code",
    role: str = "member",
    expires_at: datetime | None = None,
) -> str:
    """Store a league invite for ``code`` and return the raw code."""
    league = League(
        provider="fake",
        external_id=f"league-{code}",
        name="League",
        league_metadata={},
        provider_config_ref="ref",
    )
    session.add(league)
    session.flush()
    expiry = expires_at or (datetime.now(UTC) + timedelta(days=7))
    InviteRepository(session).create(
        league.id,
        hash_invite_code(code),
        expiry,
        role=role,
    )
    session.commit()
    return code


def _count(session: Session, model: type[Base]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_AC_AU_01_signup_creates_an_account_from_an_invite(session: Session) -> None:
    code = _seed_invite(session, role="admin")
    service = AuthService(session)

    user = service.signup("  Fan@Example.COM ", PASSWORD, code)

    assert user.id is not None
    assert user.email == "fan@example.com"
    assert user.role == "admin"
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, user.password_hash) is True
    # Membership and credential handling is intentionally outside this service.
    assert _count(session, UserLeague) == 0


def test_AC_AU_01_unknown_invite_is_rejected_without_storing_a_user(session: Session) -> None:
    _seed_invite(session)
    service = AuthService(session)

    with pytest.raises(InviteError, match="invalid") as error:
        service.signup("fan@example.com", PASSWORD, "not-the-code")

    assert "not-the-code" not in str(error.value)
    assert _count(session, AppUser) == 0


def test_AC_AU_01_empty_invite_code_is_rejected_without_storing_a_user(session: Session) -> None:
    with pytest.raises(InviteError, match="invalid"):
        AuthService(session).signup("fan@example.com", PASSWORD, "")
    assert _count(session, AppUser) == 0


def test_AC_AU_01_expired_invite_is_rejected(session: Session) -> None:
    expiry = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    code = _seed_invite(session, expires_at=expiry)
    service = AuthService(session, clock=lambda: expiry)

    with pytest.raises(ExpiredInviteError, match="expired"):
        service.signup("fan@example.com", PASSWORD, code)
    assert _count(session, AppUser) == 0


def test_AC_AU_01_invite_is_valid_until_the_expiry_instant(session: Session) -> None:
    expiry = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    code = _seed_invite(session, expires_at=expiry)
    just_before = AuthService(session, clock=lambda: expiry - timedelta(seconds=1))

    user = just_before.signup("fan@example.com", PASSWORD, code)
    assert user.email == "fan@example.com"


def test_AC_AU_01_invite_is_invalid_at_the_expiry_instant(session: Session) -> None:
    expiry = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    code = _seed_invite(session, expires_at=expiry)
    at_expiry = AuthService(session, clock=lambda: expiry)

    with pytest.raises(ExpiredInviteError):
        at_expiry.signup("fan@example.com", PASSWORD, code)


def test_AC_AU_02_duplicate_email_is_case_insensitive_and_keeps_one_account(
    session: Session,
) -> None:
    code = _seed_invite(session)
    service = AuthService(session)
    first = service.signup("Fan@Example.com", PASSWORD, code)

    with pytest.raises(EmailAlreadyRegisteredError, match="already exists"):
        service.signup("fan@example.COM", PASSWORD, code)

    assert first.id is not None
    assert _count(session, AppUser) == 1
    # The savepoint keeps the caller's transaction usable.
    assert session.scalar(select(AppUser.email)) == "fan@example.com"
    service.commit()
    assert session.scalar(select(AppUser.email)) == "fan@example.com"


def test_AC_AU_02_duplicate_from_a_concurrent_insert_is_rolled_back_and_reported(
    session: Session,
) -> None:
    code = _seed_invite(session)
    service = AuthService(session)
    service.signup("fan@example.com", PASSWORD, code)
    service.commit()

    # Simulate losing the race between the lookup and the insert.
    with (
        patch("app.db.auth_repositories.UserRepository.get_by_email", return_value=None),
        pytest.raises(EmailAlreadyRegisteredError, match="already exists"),
    ):
        service.signup("FAN@EXAMPLE.COM", PASSWORD, code)

    assert _count(session, AppUser) == 1


def test_AC_AU_03_password_is_not_stored_or_returned_in_plaintext(session: Session) -> None:
    code = _seed_invite(session)
    user = AuthService(session).signup("fan@example.com", PASSWORD, code)

    assert PASSWORD not in user.password_hash
    assert PASSWORD not in repr(user)


def test_service_does_not_commit_writes_on_its_own(session: Session) -> None:
    code = _seed_invite(session)
    service = AuthService(session)

    service.signup("fan@example.com", PASSWORD, code)
    assert _count(session, AppUser) == 1

    with Session(session.get_bind()) as other:
        assert _count(other, AppUser) == 0

    service.commit()
    with Session(session.get_bind()) as other:
        assert _count(other, AppUser) == 1


def test_AC_AU_04_valid_credentials_authenticate(session: Session) -> None:
    code = _seed_invite(session)
    service = AuthService(session)
    created = service.signup("Fan@Example.com", PASSWORD, code)
    service.commit()

    authenticated = service.authenticate("FAN@EXAMPLE.COM", PASSWORD)

    assert authenticated.id == created.id


def test_AC_AU_04_unknown_email_and_wrong_password_share_one_generic_error(
    session: Session,
) -> None:
    code = _seed_invite(session)
    service = AuthService(session)
    service.signup("fan@example.com", PASSWORD, code)
    service.commit()

    with pytest.raises(InvalidCredentialsError) as unknown:
        service.authenticate("missing@example.com", PASSWORD)
    with pytest.raises(InvalidCredentialsError) as wrong:
        service.authenticate("fan@example.com", "wrong-password")

    assert str(unknown.value) == str(wrong.value) == "invalid email or password"


def test_AC_AU_04_unknown_email_still_verifies_a_dummy_hash(session: Session) -> None:
    service = AuthService(session)

    with (
        patch("app.services.auth_service.verify_password", return_value=False) as verify,
        pytest.raises(InvalidCredentialsError),
    ):
        service.authenticate("missing@example.com", PASSWORD)

    verify.assert_called_once()
    raw, encoded = verify.call_args.args
    assert raw == PASSWORD
    assert encoded.startswith("$argon2id$")


def test_AC_AU_04_wrong_password_verifies_the_stored_hash(session: Session) -> None:
    code = _seed_invite(session)
    service = AuthService(session)
    created = service.signup("fan@example.com", PASSWORD, code)
    service.commit()

    with (
        patch("app.services.auth_service.verify_password", return_value=False) as verify,
        pytest.raises(InvalidCredentialsError),
    ):
        service.authenticate("fan@example.com", "wrong-password")

    verify.assert_called_once_with("wrong-password", created.password_hash)


def test_AC_AU_04_malformed_stored_hash_fails_generically(session: Session) -> None:
    UserRepository(session).create("fan@example.com", "not-a-password-hash")
    session.commit()

    with pytest.raises(InvalidCredentialsError):
        AuthService(session).authenticate("fan@example.com", PASSWORD)


def test_AC_AU_04_missing_password_hash_fails_generically(session: Session) -> None:
    UserRepository(session).create("fan@example.com", "")
    session.commit()

    with pytest.raises(InvalidCredentialsError):
        AuthService(session).authenticate("fan@example.com", PASSWORD)


def test_get_active_user_returns_the_account(session: Session) -> None:
    code = _seed_invite(session)
    service = AuthService(session)
    created = service.signup("fan@example.com", PASSWORD, code)
    service.commit()

    assert service.get_active_user(created.id).email == "fan@example.com"


def test_get_active_user_rejects_a_missing_account(session: Session) -> None:
    with pytest.raises(UserNotFoundError) as error:
        AuthService(session).get_active_user(999_999)

    assert error.value.user_id == 999_999


def test_inactive_user_error_is_an_unauthenticated_user_error() -> None:
    assert issubclass(InactiveUserError, UserNotFoundError)


def test_auth_errors_never_echo_passwords_or_invite_codes(session: Session) -> None:
    code = _seed_invite(session)
    service = AuthService(session)
    secret_password = "do-not-echo-this-password"

    with pytest.raises(InviteError) as invite_error:
        service.signup("fan@example.com", secret_password, "wrong-code")
    assert secret_password not in str(invite_error.value)
    assert "wrong-code" not in str(invite_error.value)

    service.signup("fan@example.com", secret_password, code)
    service.commit()
    with pytest.raises(InvalidCredentialsError) as credentials_error:
        service.authenticate("fan@example.com", "another-wrong-password")
    assert secret_password not in str(credentials_error.value)
    assert "another-wrong-password" not in str(credentials_error.value)
