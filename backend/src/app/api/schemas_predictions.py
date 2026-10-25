"""Response schemas and serialization for playoff odds (ARCHITECTURE.md section 8).

Probabilities and their Wilson intervals cross the wire as fixed four-decimal strings. The
frontend parses them to numbers only for bar geometry and sorting; the visible value comes from
the string.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel

from app.services.prediction_service import (
    MODEL,
    Probability,
)
from app.services.prediction_service import (
    PlayoffOdds as ServicePlayoffOdds,
)

_FOUR_PLACES = Decimal("0.0001")


class ProbabilityInterval(BaseModel):
    """A probability estimate and its Wilson 95% interval, as fixed four-decimal strings."""

    probability: str
    low: str
    high: str


class TeamPlayoffOdds(BaseModel):
    """One team's playoff, bye, and division-title estimates."""

    team_id: int
    team_name: str
    division: str
    playoff: ProbabilityInterval
    bye: ProbabilityInterval
    division_title: ProbabilityInterval


class PlayoffOddsModel(BaseModel):
    """Versioned model parameters, so a stored result can be reproduced and interpreted."""

    version: str
    shrink_games: int
    residual_mix_games: int
    score_precision: str
    tiebreak_uses_points_for: bool


class PlayoffOddsResponse(BaseModel):
    """Per-team playoff odds plus the metadata needed to read them."""

    league_id: int
    season: int
    status: Literal["ok", "unavailable"]
    reason: (
        Literal[
            "no_completed_weeks",
            "missing_playoff_field",
            "incomplete_schedule",
            "unsupported_division_shape",
        ]
        | None
    )
    iterations: int
    seed: int | None
    input_version: str
    model: PlayoffOddsModel
    confidence: Literal["low", "normal"] | None
    completed_weeks: int
    remaining_weeks: list[int]
    playoff_field: int | None
    division_count: int
    teams: list[TeamPlayoffOdds]


def format_probability(value: Decimal) -> str:
    """Serialize a probability or interval bound as a fixed four-decimal string."""
    return format(value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP), "f")


def _interval(probability: Probability) -> ProbabilityInterval:
    """Project one probability triple with the same rounding for value and bounds."""
    return ProbabilityInterval(
        probability=format_probability(probability.value),
        low=format_probability(probability.low),
        high=format_probability(probability.high),
    )


def to_playoff_odds_response(odds: ServicePlayoffOdds) -> PlayoffOddsResponse:
    """Build the wire response for one league season's playoff odds."""
    return PlayoffOddsResponse(
        league_id=odds.league_id,
        season=odds.season,
        status=odds.status,
        reason=odds.reason,
        iterations=odds.iterations,
        seed=odds.seed,
        input_version=odds.input_version,
        model=PlayoffOddsModel(
            version=MODEL.version,
            shrink_games=MODEL.shrink_games,
            residual_mix_games=MODEL.residual_mix_games,
            score_precision=MODEL.score_precision,
            tiebreak_uses_points_for=MODEL.tiebreak_uses_points_for,
        ),
        confidence=odds.confidence,
        completed_weeks=odds.completed_weeks,
        remaining_weeks=list(odds.remaining_weeks),
        playoff_field=odds.playoff_field,
        division_count=odds.division_count,
        teams=[
            TeamPlayoffOdds(
                team_id=team.team_id,
                team_name=team.team_name,
                division=team.division,
                playoff=_interval(team.playoff),
                bye=_interval(team.bye),
                division_title=_interval(team.division_title),
            )
            for team in odds.teams
        ],
    )
