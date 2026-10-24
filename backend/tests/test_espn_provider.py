"""Tests for the ESPN provider adapter (M3).

These tests use sanitized fixtures and never call the live ESPN API (AC-DB-07).
They verify the adapter correctly maps ESPN data to normalized DTOs with exact
Decimal points (AC-PR-01), handles byes, completed/incomplete weeks, and
playoffs, and never leaks credentials (AC-DB-08).
"""

from decimal import Decimal

import pytest

from app.providers.base import LeagueRef
from app.providers.espn import ESPNLeagueProvider
from tests.espn_fixtures import create_fake_league


class TestESPNLeagueProviderMetadata:
    """Test fetch_league returns correct metadata."""

    def test_AC_PR_01_league_metadata_is_normalized(self) -> None:
        """League metadata includes regular_season_length, team_count, scoring_type."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_basic.json")
        )
        league_ref = LeagueRef(external_id="12345")

        league_dto = provider.fetch_league(league_ref, 2024)

        assert league_dto.external_id == "12345"
        assert league_dto.name == "Test League"
        assert league_dto.metadata["regular_season_length"] == 14
        assert league_dto.metadata["team_count"] == 4
        assert league_dto.metadata["scoring_type"] == "H2H_POINTS"
        assert league_dto.metadata["division_count"] == 1
        assert league_dto.metadata["playoff_team_count"] == 4


class TestESPNLeagueProviderOwners:
    """Test fetch_owners returns correct owner data."""

    def test_AC_PR_01_owners_are_normalized(self) -> None:
        """Owners are mapped from ESPN members with external_id and display_name."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_basic.json")
        )
        league_ref = LeagueRef(external_id="12345")

        owners = provider.fetch_owners(league_ref, 2024)

        assert len(owners) == 4
        assert owners[0].external_id == "owner-1"
        assert owners[0].display_name == "John D."
        assert owners[1].external_id == "owner-2"
        assert owners[1].display_name == "Jane S."


class TestESPNLeagueProviderTeams:
    """Test fetch_teams returns correct team data."""

    def test_AC_PR_01_teams_are_normalized(self) -> None:
        """Teams are mapped with external_id, name, division, and owner_external_id."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_basic.json")
        )
        league_ref = LeagueRef(external_id="12345")

        teams = provider.fetch_teams(league_ref, 2024)

        assert len(teams) == 4
        assert teams[0].external_id == "1"
        assert teams[0].name == "Team Alpha"
        assert teams[0].division == "Division 1"
        assert teams[0].owner_external_id == "owner-1"


class TestESPNLeagueProviderMatchups:
    """Test fetch_matchups returns correct matchup data with exact Decimal points."""

    def test_AC_PR_01_matchup_points_are_exact_two_place_decimals(self) -> None:
        """Matchup points are Decimals quantized to exactly 2 decimal places, not floats."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_basic.json")
        )
        league_ref = LeagueRef(external_id="12345")

        matchups = provider.fetch_matchups(league_ref, 2024, 1)

        assert len(matchups) == 2

        # First matchup: team 1 vs team 2. 120.5 becomes 120.50; 95.0 becomes 95.00.
        m1 = matchups[0]
        assert m1.week == 1
        assert m1.home.team_external_id == "1"
        assert m1.home.points == Decimal("120.50")
        assert str(m1.home.points) == "120.50"
        assert m1.away is not None
        assert m1.away.team_external_id == "2"
        assert m1.away.points == Decimal("95.00")
        assert str(m1.away.points) == "95.00"
        assert m1.is_playoff is False
        assert m1.is_complete is True

        # Second matchup: team 3 vs team 4.
        m2 = matchups[1]
        assert m2.home.team_external_id == "3"
        assert m2.home.points == Decimal("110.00")
        assert m2.away is not None
        assert m2.away.team_external_id == "4"
        assert m2.away.points == Decimal("100.00")

    def test_AC_DB_11_future_schedule_has_pairings_but_no_scores(self) -> None:
        """The provider exposes unplayed home/away slots without inventing zero scores."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_basic.json")
        )

        matchups = provider.fetch_matchups(LeagueRef(external_id="12345"), 2024, 2)

        pairings = [
            (m.home.team_external_id, m.away.team_external_id if m.away else None) for m in matchups
        ]
        assert pairings == [("4", "1"), ("2", "3")]
        assert all(not matchup.is_complete for matchup in matchups)
        assert all(matchup.home.points is None for matchup in matchups)
        assert all(matchup.away is None or matchup.away.points is None for matchup in matchups)


class TestESPNLeagueProviderByes:
    """Test bye week handling."""

    def test_bye_week_away_is_none(self) -> None:
        """Teams with no opponent have away=None in their matchup."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_bye.json")
        )
        league_ref = LeagueRef(external_id="12346")

        # Week 2 has a bye for team 4
        matchups = provider.fetch_matchups(league_ref, 2024, 2)

        # Find the matchup where team 4 is home (bye week)
        team4_matchup = next(m for m in matchups if m.home.team_external_id == "4")
        assert team4_matchup.away is None
        assert team4_matchup.home.points is None


class TestESPNLeagueProviderCompletion:
    """Test completed/incomplete week detection."""

    def test_completed_week_is_complete(self) -> None:
        """Matchups from past weeks are marked is_complete=True."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_basic.json")
        )
        league_ref = LeagueRef(external_id="12345")

        # Week 1 is complete (currentMatchupPeriod=2)
        matchups = provider.fetch_matchups(league_ref, 2024, 1)
        assert all(m.is_complete for m in matchups)

    def test_incomplete_week_is_not_complete(self) -> None:
        """Matchups from current week are marked is_complete=False."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_incomplete.json")
        )
        league_ref = LeagueRef(external_id="12347")

        # Week 2 is in progress (currentMatchupPeriod=2)
        matchups = provider.fetch_matchups(league_ref, 2024, 2)
        assert all(not m.is_complete for m in matchups)


class TestESPNLeagueProviderPlayoffs:
    """Test playoff week detection."""

    def test_playoff_weeks_are_marked(self) -> None:
        """Matchups with playoffTierType != 'NONE' are marked is_playoff=True."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_playoffs.json")
        )
        league_ref = LeagueRef(external_id="12348")

        # Week 14 is regular season
        regular_matchups = provider.fetch_matchups(league_ref, 2024, 14)
        assert all(not m.is_playoff for m in regular_matchups)

        # Week 15 is playoffs
        playoff_matchups = provider.fetch_matchups(league_ref, 2024, 15)
        assert all(m.is_playoff for m in playoff_matchups)


class TestESPNLeagueProviderCurrentWeek:
    """Test current_week returns correct WeekStatus."""

    def test_current_week_returns_last_completed_regular_season_week(self) -> None:
        """current_week returns the latest completed regular season week."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_basic.json")
        )
        league_ref = LeagueRef(external_id="12345")

        # currentMatchupPeriod=2, so week 1 is complete
        status = provider.current_week(league_ref, 2024)
        assert status.last_completed_week == 1

    def test_current_week_returns_none_before_first_week(self) -> None:
        """current_week returns None when no weeks have completed."""

        # Create a league where currentMatchupPeriod=1 (week 1 in progress)
        def make_preseason_league(*args, **kwargs):
            league = create_fake_league("league_basic.json")
            league.currentMatchupPeriod = 1
            return league

        provider = ESPNLeagueProvider(league_factory=make_preseason_league)
        league_ref = LeagueRef(external_id="12345")

        status = provider.current_week(league_ref, 2024)
        assert status.last_completed_week is None

    def test_current_week_caps_at_regular_season_length(self) -> None:
        """current_week caps at regular_season_length when in playoffs."""
        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_playoffs.json")
        )
        league_ref = LeagueRef(external_id="12348")

        # currentMatchupPeriod=15 (playoffs), regular_season_length=14
        status = provider.current_week(league_ref, 2024)
        assert status.last_completed_week == 14


class TestESPNLeagueProviderCaching:
    """Test that league objects are cached."""

    def test_league_is_cached_per_external_id_and_season(self) -> None:
        """The same league object is reused for the same (external_id, season)."""
        call_count = 0

        def counting_factory(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return create_fake_league("league_basic.json")

        provider = ESPNLeagueProvider(league_factory=counting_factory)
        league_ref = LeagueRef(external_id="12345")

        # First call creates the league
        provider.fetch_league(league_ref, 2024)
        assert call_count == 1

        # Second call reuses the cached league
        provider.fetch_owners(league_ref, 2024)
        assert call_count == 1

        # Different season creates a new league
        provider.fetch_league(league_ref, 2025)
        assert call_count == 2

        # Different external_id creates a new league
        league_ref2 = LeagueRef(external_id="99999")
        provider.fetch_league(league_ref2, 2024)
        assert call_count == 3


class TestESPNLeagueProviderCredentials:
    """Test credential handling and redaction (AC-DB-08)."""

    def test_AC_DB_08_credentials_not_in_league_factory_args_when_empty(self) -> None:
        """Empty credentials are not passed to the league factory."""
        received_kwargs = {}

        def capturing_factory(*args, **kwargs):
            received_kwargs.update(kwargs)
            return create_fake_league("league_basic.json")

        provider = ESPNLeagueProvider(league_factory=capturing_factory, espn_s2="", swid="")
        league_ref = LeagueRef(external_id="12345")

        provider.fetch_league(league_ref, 2024)

        # Empty credentials should not be passed
        assert "espn_s2" not in received_kwargs
        assert "swid" not in received_kwargs

    def test_AC_DB_08_credentials_passed_when_present(self) -> None:
        """Non-empty credentials are passed to the league factory."""
        received_kwargs = {}

        def capturing_factory(*args, **kwargs):
            received_kwargs.update(kwargs)
            return create_fake_league("league_basic.json")

        provider = ESPNLeagueProvider(
            league_factory=capturing_factory, espn_s2="test_s2_value", swid="test_swid_value"
        )
        league_ref = LeagueRef(external_id="12345")

        provider.fetch_league(league_ref, 2024)

        assert received_kwargs["espn_s2"] == "test_s2_value"
        assert received_kwargs["swid"] == "test_swid_value"

    def test_AC_AU_13_adapter_never_reads_environment_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ESPN_S2/ESPN_SWID in the environment never reach the league factory implicitly."""
        monkeypatch.setenv("ESPN_S2", "environment-s2-must-be-ignored")
        monkeypatch.setenv("ESPN_SWID", "environment-swid-must-be-ignored")
        received_kwargs = {}

        def capturing_factory(*args, **kwargs):
            received_kwargs.update(kwargs)
            return create_fake_league("league_basic.json")

        provider = ESPNLeagueProvider(league_factory=capturing_factory)
        provider.fetch_league(LeagueRef(external_id="12345"), 2024)

        assert "espn_s2" not in received_kwargs
        assert "swid" not in received_kwargs

    def test_AC_DB_08_credentials_not_in_error_messages(self) -> None:
        """If the league factory raises, credentials are not in the error."""

        def failing_factory(*args, **kwargs):
            raise ValueError("League not found")

        provider = ESPNLeagueProvider(
            league_factory=failing_factory, espn_s2="secret_s2", swid="secret_swid"
        )
        league_ref = LeagueRef(external_id="12345")

        with pytest.raises(ValueError, match="League not found") as exc_info:
            provider.fetch_league(league_ref, 2024)

        error_message = str(exc_info.value)
        assert "secret_s2" not in error_message
        assert "secret_swid" not in error_message


class TestESPNLeagueProviderEdgeCases:
    """Test edge cases and fallback behavior."""

    def test_owner_mapping_without_display_name(self) -> None:
        """Owner mapping falls back to first+last name when displayName is missing."""
        from tests.espn_fixtures import FakeLeague

        data = {
            "league_id": 99999,
            "year": 2024,
            "status": {
                "currentMatchupPeriod": 2,
                "firstScoringPeriod": 1,
                "finalScoringPeriod": 14,
                "latestScoringPeriod": 7,
            },
            "settings": {
                "name": "Test League",
                "size": 2,
                "scheduleSettings": {
                    "matchupPeriodCount": 14,
                    "divisions": [],
                    "playoffTeamCount": 4,
                },
                "scoringSettings": {"scoringType": "H2H_POINTS"},
            },
            "members": [
                {"id": "owner-1", "firstName": "John", "lastName": "Doe"},  # No displayName
                {"id": "owner-2"},  # Minimal member data
            ],
            "teams": [
                {
                    "id": 1,
                    "name": "Team 1",
                    "divisionId": 0,
                    "owners": ["owner-1"],
                    "record": {
                        "overall": {
                            "wins": 1,
                            "losses": 0,
                            "ties": 0,
                            "pointsFor": 100.0,
                            "pointsAgainst": 50.0,
                        }
                    },
                },
                {
                    "id": 2,
                    "name": "Team 2",
                    "divisionId": 0,
                    "owners": ["owner-2"],
                    "record": {
                        "overall": {
                            "wins": 0,
                            "losses": 1,
                            "ties": 0,
                            "pointsFor": 50.0,
                            "pointsAgainst": 100.0,
                        }
                    },
                },
            ],
            "schedule": [],
        }
        league = FakeLeague(data)
        provider = ESPNLeagueProvider(league_factory=lambda *args, **kwargs: league)
        league_ref = LeagueRef(external_id="99999")

        owners = provider.fetch_owners(league_ref, 2024)

        assert len(owners) == 2
        assert owners[0].display_name == "John Doe"  # Fallback to first+last
        assert owners[1].display_name == "Unknown"  # No name data at all

    def test_team_outcome_out_of_range(self) -> None:
        """Team outcome returns 'U' when week is out of range."""
        from app.providers.espn.mappers import _get_team_outcome
        from tests.espn_fixtures import FakeTeam

        team_data = {
            "id": 1,
            "name": "Team 1",
            "divisionId": 0,
            "owners": [],
        }
        team = FakeTeam(team_data, ["W", "L"])  # Only 2 weeks of data

        # Valid weeks
        assert _get_team_outcome(team, 1) == "W"
        assert _get_team_outcome(team, 2) == "L"

        # Out of range weeks
        assert _get_team_outcome(team, 0) == "U"  # Week 0 doesn't exist
        assert _get_team_outcome(team, 3) == "U"  # Week 3 not in data


class TestESPNLeagueProviderRegistry:
    """Test that the ESPN provider can be registered explicitly."""

    def test_espn_provider_registered_explicitly(self) -> None:
        """The ESPN provider is registered through the registry, not auto-registered."""
        from app.providers.registry import ProviderRegistry

        provider = ESPNLeagueProvider(
            league_factory=lambda *args, **kwargs: create_fake_league("league_basic.json")
        )
        registry = ProviderRegistry()

        registry.register(provider)

        assert registry.get("espn") is provider
