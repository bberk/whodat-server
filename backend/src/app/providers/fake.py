"""Deterministic in-memory provider for tests and local development."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from app.providers.base import (
    LeagueDTO,
    LeagueRef,
    MatchupDTO,
    OwnerDTO,
    TeamDTO,
    WeekStatus,
)

type _LeagueKey = tuple[str, int]
type _FakeLeagueSeed = tuple[
    LeagueDTO,
    Sequence[OwnerDTO],
    Sequence[TeamDTO],
    Mapping[int, Sequence[MatchupDTO]],
    WeekStatus,
]


@dataclass(frozen=True)
class _LeagueSnapshot:
    league: LeagueDTO
    owners: tuple[OwnerDTO, ...]
    teams: tuple[TeamDTO, ...]
    matchups: Mapping[int, tuple[MatchupDTO, ...]]
    week_status: WeekStatus


class FakeProvider:
    """Serve seeded normalized data without I/O and protect stored sequences."""

    provider_id = "fake"

    def __init__(self, seed_data: Mapping[_LeagueKey, _FakeLeagueSeed]) -> None:
        """Copy seed sequences into an immutable snapshot keyed by league and season.

        Each seed tuple contains the league, owners, teams, week-to-matchups mapping,
        and current week status, in that order.
        """
        snapshots: dict[_LeagueKey, _LeagueSnapshot] = {}
        for key, seed in seed_data.items():
            league, owners, teams, matchups, week_status = seed
            weekly_matchups = MappingProxyType(
                {week: tuple(items) for week, items in matchups.items()}
            )
            snapshots[key] = _LeagueSnapshot(
                league=league,
                owners=tuple(owners),
                teams=tuple(teams),
                matchups=weekly_matchups,
                week_status=week_status,
            )
        self._snapshots: Mapping[_LeagueKey, _LeagueSnapshot] = MappingProxyType(snapshots)

    def fetch_league(self, league_ref: LeagueRef, season: int) -> LeagueDTO:
        """Return the seeded league, or raise KeyError for an unknown league season."""
        return self._snapshot(league_ref, season).league

    def fetch_owners(self, league_ref: LeagueRef, season: int) -> list[OwnerDTO]:
        """Return a fresh list of seeded owners for the league season."""
        return list(self._snapshot(league_ref, season).owners)

    def fetch_teams(self, league_ref: LeagueRef, season: int) -> list[TeamDTO]:
        """Return a fresh list of seeded teams for the league season."""
        return list(self._snapshot(league_ref, season).teams)

    def fetch_matchups(self, league_ref: LeagueRef, season: int, week: int) -> list[MatchupDTO]:
        """Return a fresh matchup list, raising KeyError for an unseeded week."""
        return list(self._snapshot(league_ref, season).matchups[week])

    def current_week(self, league_ref: LeagueRef, season: int) -> WeekStatus:
        """Return the seeded completed-week status for the league season."""
        return self._snapshot(league_ref, season).week_status

    def _snapshot(self, league_ref: LeagueRef, season: int) -> _LeagueSnapshot:
        return self._snapshots[(league_ref.external_id, season)]
