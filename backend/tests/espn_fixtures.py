"""Test helpers for ESPN provider tests.

Provides utilities to load fixtures and create fake League objects that
satisfy the ESPNLeagueProto Protocol for offline testing.
"""

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent.parent.parent / "docs" / "fixtures" / "espn"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture file by name."""
    fixture_path = FIXTURES_DIR / name
    with open(fixture_path, encoding="utf-8") as f:
        return json.load(f)


class FakeSettings:
    """Fake ESPN settings object for testing."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.name: str = data["name"]
        self.reg_season_count: int = data["scheduleSettings"]["matchupPeriodCount"]
        self.team_count: int = data["size"]
        self.scoring_type: str | None = data.get("scoringSettings", {}).get("scoringType")
        self.playoff_team_count: int | None = data["scheduleSettings"].get("playoffTeamCount")
        # Build division map
        self.division_map: dict[int, str] = {}
        for div in data["scheduleSettings"].get("divisions", []):
            self.division_map[div["id"]] = div["name"]


class FakeTeam:
    """Fake ESPN team object for testing."""

    def __init__(self, data: dict[str, Any], week_outcomes: list[str]) -> None:
        self.team_id: int = data["id"]
        self.team_name: str = data["name"]
        self.division_id: int = data.get("divisionId", 0)
        # Division name is set by the league, not the team data
        self.division_name: str = ""  # Will be set by FakeLeague
        # Owner IDs (list of member IDs)
        self.owners: list[dict[str, Any]] = []
        for owner_id in data.get("owners", []):
            self.owners.append({"id": owner_id})
        # Scores and outcomes per week (1-indexed, stored as 0-indexed list)
        self.scores: list[float] = []
        self.outcomes: list[str] = week_outcomes


class FakeMatchup:
    """Fake ESPN matchup object for testing."""

    def __init__(self, data: dict[str, Any]) -> None:
        home = data.get("home", {})
        away = data.get("away", {})
        self._home_team_id: int = home.get("teamId", 0)
        self._away_team_id: int = away.get("teamId", 0)
        self.home_score: float = home.get("totalPoints", 0.0)
        self.away_score: float = away.get("totalPoints", 0.0)
        self.is_playoff: bool = data.get("matchupPeriodId", 1) > 14  # Simple heuristic


class FakeLeague:
    """Fake ESPN league object for testing."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.league_id: int = data["league_id"]
        self.currentMatchupPeriod: int = data["status"]["currentMatchupPeriod"]
        self.settings: FakeSettings = FakeSettings(data["settings"])
        self.members: list[dict[str, Any]] = data["members"]

        # Build teams with week outcomes
        self.teams: list[FakeTeam] = []
        schedule_by_team = self._build_schedule_by_team(data)
        for team_data in data["teams"]:
            team_id = team_data["id"]
            week_outcomes = schedule_by_team.get(team_id, [])
            team = FakeTeam(team_data, week_outcomes)
            team.division_name = self.settings.division_map.get(team.division_id, "")
            self.teams.append(team)

        # Store schedule for scoreboard
        self._schedule = data.get("schedule", [])

    def _build_schedule_by_team(self, data: dict[str, Any]) -> dict[int, list[str]]:
        """Build a mapping of team_id -> list of outcomes per week."""
        schedule: dict[int, list[str]] = {}
        for matchup in data.get("schedule", []):
            week = matchup["matchupPeriodId"]
            home_id = matchup.get("home", {}).get("teamId", 0)
            away_id = matchup.get("away", {}).get("teamId", 0)
            winner = matchup.get("winner", "UNDECIDED")

            # Initialize lists if needed
            if home_id not in schedule:
                schedule[home_id] = []
            if away_id and away_id not in schedule:
                schedule[away_id] = []

            # Extend lists to current week
            while len(schedule[home_id]) < week:
                schedule[home_id].append("U")
            if away_id:
                while len(schedule[away_id]) < week:
                    schedule[away_id].append("U")

            # Set outcome for this week
            if winner == "HOME":
                schedule[home_id][week - 1] = "W"
                if away_id:
                    schedule[away_id][week - 1] = "L"
            elif winner == "AWAY":
                schedule[home_id][week - 1] = "L"
                if away_id:
                    schedule[away_id][week - 1] = "W"
            elif winner == "TIE":
                schedule[home_id][week - 1] = "T"
                if away_id:
                    schedule[away_id][week - 1] = "T"
            # UNDECIDED stays as "U"

        return schedule

    def scoreboard(self, week: int) -> list[FakeMatchup]:
        """Return matchups for a given week."""
        return [
            FakeMatchup(matchup) for matchup in self._schedule if matchup["matchupPeriodId"] == week
        ]


def create_fake_league(fixture_name: str) -> FakeLeague:
    """Load a fixture and create a FakeLeague object."""
    data = load_fixture(fixture_name)
    return FakeLeague(data)
