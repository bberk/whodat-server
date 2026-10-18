"""Internal protocol types for the ESPN adapter.

These protocols describe the minimal subset of ``espn_api.football`` types the
adapter consumes. Tests build lightweight fakes that satisfy the same shape so
no HTTP calls or real ESPN data ever reach the adapter under test.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class ESPNSettingsProto(Protocol):
    """Subset of :class:`espn_api.football.Settings` the adapter reads."""

    reg_season_count: int
    team_count: int
    name: str
    division_map: dict[int, str]
    scoring_type: str | None


class ESPNTeamProto(Protocol):
    """Subset of :class:`espn_api.football.Team` the adapter reads."""

    team_id: int
    team_name: str
    division_name: str
    owners: Sequence[Mapping[str, Any]]
    scores: Sequence[float]
    outcomes: Sequence[str]


class ESPNMatchupProto(Protocol):
    """Subset of :class:`espn_api.football.Matchup` the adapter reads."""

    _home_team_id: int
    _away_team_id: int
    home_score: float
    away_score: float
    is_playoff: bool


class ESPNLeagueProto(Protocol):
    """Subset of :class:`espn_api.football.League` the adapter reads."""

    league_id: int
    settings: ESPNSettingsProto
    teams: Sequence[ESPNTeamProto]
    members: Sequence[Mapping[str, Any]]
    currentMatchupPeriod: int

    def scoreboard(self, week: int) -> Sequence[ESPNMatchupProto]: ...
