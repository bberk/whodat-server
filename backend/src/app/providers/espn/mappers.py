"""Pure mapping functions from ESPN types to provider DTOs.

These functions contain NO side effects and NO HTTP calls. They convert
espn_api objects into the normalized DTOs defined in providers.base.
"""

from decimal import Decimal

from app.providers.base import (
    LeagueDTO,
    MatchupDTO,
    MatchupSideDTO,
    OwnerDTO,
    TeamDTO,
)
from app.providers.espn._types import (
    ESPNLeagueProto,
    ESPNTeamProto,
)


def _quantize_points(value: float) -> Decimal:
    """Convert a float score to Decimal with 2 decimal places.

    ESPN reports scores as floats. We convert via string to avoid float
    precision issues, then quantize to 2 decimal places per ARCHITECTURE.md.
    """
    return Decimal(str(value)).quantize(Decimal("0.01"))


def map_league(league: ESPNLeagueProto, external_id: str) -> LeagueDTO:
    """Map an ESPN league to a normalized LeagueDTO.

    The metadata dict includes settings the sync service may need:
    - regular_season_length: number of regular season weeks
    - team_count: number of teams in the league
    - scoring_type: ESPN's scoring type (e.g., "H2H_POINTS")
    - division_count: number of divisions (0 if none)
    """
    return LeagueDTO(
        external_id=external_id,
        name=league.settings.name,
        metadata={
            "regular_season_length": league.settings.reg_season_count,
            "team_count": league.settings.team_count,
            "scoring_type": league.settings.scoring_type,
            "division_count": len(league.settings.division_map),
        },
    )


def map_owners(league: ESPNLeagueProto) -> list[OwnerDTO]:
    """Map ESPN members to normalized OwnerDTOs.

    ESPN members are dicts with 'id', 'firstName', 'lastName', 'displayName'.
    We use 'displayName' if present, otherwise combine first and last name.
    """
    owners: list[OwnerDTO] = []
    for member in league.members:
        member_id = str(member["id"])
        display_name = member.get("displayName")
        if not display_name:
            first = member.get("firstName", "")
            last = member.get("lastName", "")
            display_name = f"{first} {last}".strip() or "Unknown"
        owners.append(OwnerDTO(external_id=member_id, display_name=display_name))
    return owners


def map_teams(league: ESPNLeagueProto) -> list[TeamDTO]:
    """Map ESPN teams to normalized TeamDTOs.

    Division name is mapped to None if empty string.
    Owner linking uses the first owner in the team's owners list.
    """
    teams: list[TeamDTO] = []
    for team in league.teams:
        team_id = str(team.team_id)
        name = team.team_name
        division = team.division_name if team.division_name else None
        owner_id = None
        if team.owners:
            first_owner = team.owners[0]
            owner_id = str(first_owner["id"])
        teams.append(
            TeamDTO(
                external_id=team_id,
                name=name,
                division=division,
                owner_external_id=owner_id,
            )
        )
    return teams


def _get_team_outcome(team: ESPNTeamProto, week: int) -> str:
    """Get a team's outcome for a given week (1-indexed).

    Returns 'U' (undecided) if the week is out of range.
    """
    if 1 <= week <= len(team.outcomes):
        return team.outcomes[week - 1]
    return "U"


def map_matchups(league: ESPNLeagueProto, week: int) -> list[MatchupDTO]:
    """Map ESPN matchups for a week to normalized MatchupDTOs.

    Uses league.scoreboard(week) to get matchups, then determines completion
    status from team outcomes. Byes are represented as away=None.

    Points are quantized to 2 decimal places per ARCHITECTURE.md.
    """
    scoreboard_matchups = league.scoreboard(week)
    matchups: list[MatchupDTO] = []

    # Build team lookup for outcome checking
    teams_by_id = {team.team_id: team for team in league.teams}

    for espn_matchup in scoreboard_matchups:
        home_team_id = espn_matchup._home_team_id
        away_team_id = espn_matchup._away_team_id

        # Home side
        home_points = _quantize_points(espn_matchup.home_score)
        home_side = MatchupSideDTO(
            team_external_id=str(home_team_id),
            points=home_points,
        )

        # Away side (None for byes)
        if away_team_id == 0:
            away_side = None
        else:
            away_points = _quantize_points(espn_matchup.away_score)
            away_side = MatchupSideDTO(
                team_external_id=str(away_team_id),
                points=away_points,
            )

        # Determine completion status from team outcomes
        home_team = teams_by_id.get(home_team_id)
        is_complete = False
        if home_team:
            outcome = _get_team_outcome(home_team, week)
            is_complete = outcome != "U"

        matchups.append(
            MatchupDTO(
                week=week,
                home=home_side,
                away=away_side,
                is_playoff=espn_matchup.is_playoff,
                is_complete=is_complete,
            )
        )

    return matchups
