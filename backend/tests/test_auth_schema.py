"""Repository behaviour for invite-only accounts and league memberships.

Shape (columns, keys, indexes) is owned by test_db_schema.py; these tests cover storage behaviour:
email casing, duplicate rejection, role validation, invite expiry, credential round-trip, membership
listings, and owner associations. SQLite is the default engine; set ``AUTH_TEST_DATABASE_URL`` to
the worktree-local PostgreSQL URL to run the same assertions against Postgres.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.auth_repositories import (
    DuplicateEmailError,
    DuplicateMembershipError,
    InviteRepository,
    MembershipNotFoundError,
    MembershipRepository,
    UserRepository,
)
from app.db.base import Base
from app.db.models import AppUser, Invite, League, Owner


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated database and a caller-owned ORM session."""
    engine = create_engine(os.environ.get("AUTH_TEST_DATABASE_URL", "sqlite://"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db_session:
            yield db_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_league(session: Session, external_id: str = "league-1") -> tuple[League, Owner]:
    """Create one league and owner for membership and invite tests."""
    league = League(
        provider="fake",
        external_id=external_id,
        name="League",
        league_metadata={},
        provider_config_ref="ref",
    )
    session.add(league)
    session.flush()
    owner = Owner(league_id=league.id, external_id=f"owner-{external_id}", display_name="Owner")
    session.add(owner)
    session.flush()
    return league, owner


def test_app_user_role_accepts_only_admin_and_member(session: Session) -> None:
    """Role values are validated in the model layer rather than by a database enum."""
    user = UserRepository(session).create("admin@example.com", "hash", role="admin")
    assert user.role == "admin"

    with pytest.raises(ValueError, match="invalid role"):
        AppUser(email="other@example.com", password_hash="hash", role="superuser")

    member = UserRepository(session).create("member@example.com", "hash")
    assert member.role == "member"


def test_invite_code_hash_is_unique(session: Session) -> None:
    """Two invites cannot share a code hash."""
    league, _ = _seed_league(session)
    repository = InviteRepository(session)
    expires_at = datetime.now(UTC) + timedelta(days=7)
    repository.create(league.id, "same-hash", expires_at)

    with pytest.raises(IntegrityError), session.begin_nested():
        repository.create(league.id, "same-hash", expires_at)


def test_invite_role_accepts_only_admin_and_member() -> None:
    """The invite role is validated in the model layer."""
    with pytest.raises(ValueError, match="invalid role"):
        Invite(league_id=1, code_hash="hash", role="owner", expires_at=datetime.now(UTC))


def test_user_repository_lowercases_email_and_rejects_duplicates(session: Session) -> None:
    """Email storage and lookup are case-insensitive (AC-AU-02)."""
    repository = UserRepository(session)
    user = repository.create("  Fan@Example.COM ", "hash")

    assert user.email == "fan@example.com"
    assert repository.get_by_email("FAN@EXAMPLE.COM") is user
    assert repository.get_by_id(user.id) is user
    assert repository.get_by_id(999_999) is None
    assert repository.get_by_email("missing@example.com") is None
    with pytest.raises(ValueError, match="must not be empty"):
        repository.create("   ", "hash")

    with pytest.raises(DuplicateEmailError, match="already exists"), session.begin_nested():
        repository.create("fan@example.com", "other-hash")


def test_user_repository_resurfaces_non_unique_integrity_errors(session: Session) -> None:
    """Only duplicate-email violations become DuplicateEmailError."""
    with pytest.raises(IntegrityError):
        UserRepository(session).create("no-password@example.com", None)  # type: ignore[arg-type]
    session.rollback()


def test_membership_repository_rejects_duplicate_joins(session: Session) -> None:
    """A membership is unique per (user, league) pair (AC-AU-05)."""
    league, _ = _seed_league(session)
    user = UserRepository(session).create("member@example.com", "hash")
    repository = MembershipRepository(session)
    repository.create(user.id, league.id)

    with (
        pytest.raises(DuplicateMembershipError, match="already belongs"),
        session.begin_nested(),
    ):
        repository.create(user.id, league.id)


def test_membership_repository_lists_only_the_requested_users_or_league(
    session: Session,
) -> None:
    """Membership lists are scoped and stable for both directions of the many-to-many."""
    first_league, _ = _seed_league(session, "league-1")
    second_league, _ = _seed_league(session, "league-2")
    first_user = UserRepository(session).create("first@example.com", "hash")
    second_user = UserRepository(session).create("second@example.com", "hash")
    other_user = UserRepository(session).create("other@example.com", "hash")
    repository = MembershipRepository(session)
    first = repository.create(first_user.id, second_league.id)
    second = repository.create(first_user.id, first_league.id)
    third = repository.create(second_user.id, first_league.id)
    repository.create(other_user.id, second_league.id)

    assert repository.get(first_user.id, first_league.id) is second
    assert repository.get(other_user.id, first_league.id) is None
    assert repository.list_for_user(first_user.id) == [second, first]
    assert repository.list_for_league(first_league.id) == [second, third]


def test_membership_repository_sets_and_clears_the_owner_association(session: Session) -> None:
    """A membership can point at one owner in its league and be cleared again."""
    league, owner = _seed_league(session)
    user = UserRepository(session).create("fan@example.com", "hash")
    repository = MembershipRepository(session)
    membership = repository.create(user.id, league.id)

    assert repository.set_owner(user.id, league.id, owner.id) is membership
    assert membership.owner_id == owner.id
    assert repository.set_owner(user.id, league.id, None) is membership
    assert membership.owner_id is None


def test_membership_repository_stores_and_clears_opaque_credentials(session: Session) -> None:
    """Encrypted tokens round-trip through the two columns without being interpreted."""
    league, _ = _seed_league(session)
    user = UserRepository(session).create("fan@example.com", "hash")
    repository = MembershipRepository(session)
    membership = repository.create(user.id, league.id)

    s2_token = "ciphertext-one"
    swid_token = "ciphertext-two"
    stored = repository.set_credentials(
        user.id,
        league.id,
        espn_s2_encrypted=s2_token,
        espn_swid_encrypted=swid_token,
    )
    assert stored is membership
    assert membership.espn_s2_encrypted == s2_token
    assert membership.espn_swid_encrypted == swid_token

    cleared = repository.clear_credentials(user.id, league.id)
    assert cleared is membership
    assert membership.espn_s2_encrypted is None
    assert membership.espn_swid_encrypted is None


def test_membership_repository_requires_an_existing_membership(session: Session) -> None:
    """Owner and credential updates fail clearly when the membership does not exist."""
    repository = MembershipRepository(session)
    with pytest.raises(MembershipNotFoundError):
        repository.set_owner(1, 1, None)
    with pytest.raises(MembershipNotFoundError):
        repository.set_credentials(
            1, 1, espn_s2_encrypted="ciphertext-one", espn_swid_encrypted="ciphertext-two"
        )
    with pytest.raises(MembershipNotFoundError):
        repository.clear_credentials(1, 1)


def test_invite_repository_returns_the_hashed_row(session: Session) -> None:
    """Lookups use the hash, and an unknown hash returns None."""
    league, _ = _seed_league(session)
    repository = InviteRepository(session)
    expires_at = datetime.now(UTC) + timedelta(days=7)
    invite = repository.create(league.id, "stored-hash", expires_at, role="admin")

    found = repository.get_by_code_hash("stored-hash")
    assert found is invite
    assert found is not None
    assert found.role == "admin"
    assert found.expires_at is not None
    assert repository.get_by_code_hash("raw-code") is None


def test_invite_validity_ends_at_the_expiry_instant(session: Session) -> None:
    """An invite is valid strictly before expires_at; the boundary itself is expired."""
    league, _ = _seed_league(session)
    repository = InviteRepository(session)
    expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    invite = repository.create(league.id, "boundary-hash", expires_at)

    assert repository.is_valid(invite, now=expires_at - timedelta(seconds=1))
    assert repository.is_valid(invite, now=expires_at - timedelta(days=7))
    assert not repository.is_valid(invite, now=expires_at)
    assert not repository.is_valid(invite, now=expires_at + timedelta(seconds=1))
    assert repository.is_valid(invite)


def test_invite_validity_treats_naive_timestamps_as_utc(session: Session) -> None:
    """SQLite reloads timestamps without an offset; comparison still uses UTC."""
    league, _ = _seed_league(session)
    repository = InviteRepository(session)
    expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    repository.create(league.id, "naive-hash", expires_at)
    session.expire_all()

    reloaded = repository.get_by_code_hash("naive-hash")
    assert reloaded is not None
    naive_now = (expires_at - timedelta(seconds=1)).replace(tzinfo=None)
    assert repository.is_valid(reloaded, now=naive_now)
    naive_expiry = expires_at.replace(tzinfo=None)
    assert not repository.is_valid(reloaded, now=naive_expiry)
