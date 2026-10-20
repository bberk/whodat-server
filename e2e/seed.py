"""Seed one deterministic league for the Playwright end-to-end suite.

The seeder never calls ESPN. It builds a :class:`~app.providers.fake.FakeProvider` from the
checked-in ``e2e/fixture.json``, runs the real sync service, and creates an admin account, an
admin membership, and admin/member invites with fixed codes. Running it again is safe: sync
upserts by natural key, invites are updated in place, and the admin password hash is refreshed.

It expects the schema to exist (``alembic upgrade head``). The configured ``DATABASE_URL`` decides
the database, so the same script works against local SQLite and the CI Postgres service.
"""

# ruff: noqa: E402  # the imports below must follow the sys.path shim.

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Make `app` importable when the script is run directly from the repository root or by CI.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))

from sqlalchemy.orm import Session

from app.api.schemas_standings import to_standings_response, to_vp_history_response
from app.db.auth_repositories import InviteRepository, MembershipRepository, UserRepository
from app.db.models import ROLE_ADMIN, ROLE_MEMBER, AppUser
from app.db.session import get_session_factory
from app.providers.base import (
    LeagueDTO,
    LeagueRef,
    MatchupDTO,
    MatchupSideDTO,
    OwnerDTO,
    TeamDTO,
    WeekStatus,
)
from app.providers.fake import FakeProvider
from app.security.invite_codes import hash_invite_code
from app.security.passwords import hash_password
from app.services.auth_service import AuthService
from app.services.standings_service import StandingsService
from app.services.sync_service import SyncService

FIXTURE_PATH = _ROOT / "e2e" / "fixture.json"

#: Leagues reached through the HTTP API are stored under the ESPN provider id, even though the
#: e2e data comes from the FakeProvider. A member can then join the existing league by external id.
API_PROVIDER_ID = "espn"

#: Invites and therefore the seeded account stay valid far beyond any e2e run.
INVITE_LIFETIME = timedelta(days=3650)


def _owner_dtos(teams: list[dict[str, Any]]) -> list[OwnerDTO]:
    """Build one owner per team, named as the fixture says."""
    return [
        OwnerDTO(external_id=f"owner-{index}", display_name=team["owner"])
        for index, team in enumerate(teams, start=1)
    ]


def _team_dtos(teams: list[dict[str, Any]]) -> list[TeamDTO]:
    """Build team DTOs with divisions and the owner external ids created above."""
    return [
        TeamDTO(
            external_id=team["externalId"],
            name=team["name"],
            division=team["division"],
            owner_external_id=f"owner-{index}",
        )
        for index, team in enumerate(teams, start=1)
    ]


def _matchup_dtos(weeks: dict[str, list[dict[str, str]]]) -> dict[int, list[MatchupDTO]]:
    """Turn the fixture's JSON weeks into completed regular-season matchups."""
    return {
        int(week): [
            MatchupDTO(
                week=int(week),
                home=MatchupSideDTO(
                    team_external_id=item["home"], points=Decimal(item["homePoints"])
                ),
                away=MatchupSideDTO(
                    team_external_id=item["away"], points=Decimal(item["awayPoints"])
                ),
                is_playoff=False,
                is_complete=True,
            )
            for item in items
        ]
        for week, items in weeks.items()
    }


def _provider(fixture: dict[str, Any]) -> FakeProvider:
    """Build a FakeProvider for the single fixture league season."""
    league = fixture["league"]
    teams = _team_dtos(fixture["teams"])
    matchups = _matchup_dtos(fixture["weeks"])
    seed = {
        (league["externalId"], league["season"]): (
            LeagueDTO(
                external_id=league["externalId"],
                name=league["name"],
                metadata={
                    "regular_season_length": league["regularSeasonLength"],
                    "team_count": len(teams),
                },
            ),
            _owner_dtos(fixture["teams"]),
            teams,
            matchups,
            WeekStatus(last_completed_week=max(matchups)),
        )
    }
    return FakeProvider(seed)


def _ensure_invite(
    session: Session,
    *,
    league_id: int | None,
    code: str,
    role: str,
    now: datetime,
) -> None:
    """Create the invite or refresh its role, league, and expiry so reruns stay valid.

    A member invite names its league; an admin invite is league-less (AC-AU-17).
    """
    repository = InviteRepository(session)
    code_hash = hash_invite_code(code)
    invite = repository.get_by_code_hash(code_hash)
    expires_at = now + INVITE_LIFETIME
    if invite is None:
        repository.create(league_id, code_hash, expires_at, role=role)
        return
    invite.league_id = league_id
    invite.role = role
    invite.expires_at = expires_at
    session.flush()


def _ensure_admin(session: Session, fixture: dict[str, Any]) -> AppUser:
    """Create the admin from the admin invite, or refresh its password and role on a rerun."""
    credentials = fixture["users"]["admin"]
    email = credentials["email"]
    password = credentials["password"]
    users = UserRepository(session)
    admin = users.get_by_email(email)
    if admin is None:
        AuthService(session).signup(email, password, fixture["inviteCodes"]["admin"])
        admin = users.get_by_email(email)
        if admin is None:  # pragma: no cover - signup either persists the row or raises
            raise RuntimeError("admin account was not created")
    else:
        admin.password_hash = hash_password(password)
        admin.role = ROLE_ADMIN
        session.flush()
    # The fixture promises a known password; verify the seeded account can actually use it.
    AuthService(session).authenticate(email, password)
    return admin


def _check(errors: list[str], label: str, actual: object, expected: object) -> None:
    """Record a readable mismatch instead of stopping at the first difference."""
    if actual != expected:
        errors.append(f"{label}: expected {expected!r}, got {actual!r}")


def _validate(
    session: Session, fixture: dict[str, Any], league_id: int, weeks: list[int]
) -> list[str]:
    """Compare the persisted standings and history with the fixture's golden values."""
    league = fixture["league"]
    season = league["season"]
    service = StandingsService(session)
    standings = to_standings_response(service.get_standings(league_id, season))
    history = to_vp_history_response(service.get_vp_history(league_id, season))
    errors: list[str] = []

    _check(errors, "completed_weeks", standings.completed_weeks, len(weeks))
    _check(errors, "history.weeks", history.weeks, weeks)

    actual_rows = {row.team_name: row for row in standings.overall}
    for expected in fixture["expected"]["overall"]:
        row = actual_rows.get(expected["team"])
        if row is None:
            errors.append(f"overall: missing team {expected['team']!r}")
            continue
        label = f"overall[{expected['team']}]"
        _check(errors, f"{label}.rank", row.rank, expected["rank"])
        _check(errors, f"{label}.owner", row.owner_name, expected["owner"])
        _check(errors, f"{label}.division", row.division, expected["division"])
        _check(errors, f"{label}.vp", row.victory_points, expected["victoryPoints"])
        _check(errors, f"{label}.wins", row.wins, expected["wins"])
        _check(errors, f"{label}.losses", row.losses, expected["losses"])
        _check(errors, f"{label}.ties", row.ties, expected["ties"])
        _check(
            errors,
            f"{label}.points_for",
            Decimal(row.points_for),
            Decimal(expected["pointsFor"]),
        )
        _check(errors, f"{label}.weekly_vp", row.weekly_vp, expected["weeklyVp"])

    actual_divisions = [
        (division.name, [(row.team_name, row.rank) for row in division.standings])
        for division in standings.divisions
    ]
    expected_divisions = [
        (
            division["name"],
            [(team["team"], team["rank"]) for team in division["teams"]],
        )
        for division in fixture["expected"]["divisions"]
    ]
    _check(errors, "divisions", actual_divisions, expected_divisions)

    actual_history = {team.team_name: (team.weekly, team.cumulative) for team in history.teams}
    for expected in fixture["expected"]["history"]:
        label = f"history[{expected['team']}]"
        actual = actual_history.get(expected["team"])
        if actual is None:
            errors.append(f"{label}: missing team")
            continue
        _check(errors, f"{label}.weekly", list(actual[0]), expected["weekly"])
        _check(errors, f"{label}.cumulative", list(actual[1]), expected["cumulative"])

    return errors


def seed() -> int:
    """Apply the fixture, validate it against the golden values, and commit."""
    fixture: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    league = fixture["league"]
    weeks = sorted(int(week) for week in fixture["weeks"])
    now = datetime.now(UTC)

    factory = get_session_factory()
    with factory() as session:
        summary = SyncService(_provider(fixture), session).sync_league(
            LeagueRef(external_id=league["externalId"]),
            API_PROVIDER_ID,
            league["season"],
            weeks=weeks,
        )

        _ensure_invite(
            session,
            league_id=None,
            code=fixture["inviteCodes"]["admin"],
            role=ROLE_ADMIN,
            now=now,
        )
        _ensure_invite(
            session,
            league_id=summary.league_id,
            code=fixture["inviteCodes"]["member"],
            role=ROLE_MEMBER,
            now=now,
        )
        admin = _ensure_admin(session, fixture)
        memberships = MembershipRepository(session)
        if memberships.get(admin.id, summary.league_id) is None:
            memberships.create(admin.id, summary.league_id)

        errors = _validate(session, fixture, summary.league_id, weeks)
        if errors:
            session.rollback()
            print("e2e seed validation failed:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 1

        session.commit()
        print(
            "e2e seed: "
            f"league={summary.league_id} season={league['season']} "
            f"teams={len(fixture['teams'])} weeks={','.join(str(week) for week in weeks)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(seed())
