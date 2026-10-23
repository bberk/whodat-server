"""Wire schemas for Elo history and per-league Elo settings.

Ratings are exact ``Decimal`` values inside the domain and service. They cross the wire as strings
rounded half-up to two decimals (the History page's display precision), never as JSON numbers, so
no binary float is involved. Settings are strings too, rounded to six decimals for readability.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.elo import EloConfig, EloMode
from app.domain.elo import EloSeasonRating as DomainSeasonRating
from app.domain.elo import EloWeekReference as DomainWeekReference
from app.services.elo_service import EloHistoryView, EloTeamView
from app.services.elo_service import EloUnratedTeam as ServiceUnratedTeam
from app.services.elo_service import EloWarning as ServiceWarning

_TWO_PLACES = Decimal("0.01")
_SIX_PLACES = Decimal("0.000001")


def _trim(text: str) -> str:
    """Drop trailing fractional zeros and normalize negative zero."""
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def format_rating(value: Decimal) -> str:
    """Serialize a rating or rating change to two decimals, half-up, without trailing zeros."""
    return _trim(format(value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP), "f"))


def format_setting(value: Decimal) -> str:
    """Serialize a config value to at most six decimals, without trailing zeros."""
    return _trim(format(value.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP), "f"))


class EloConfigValues(BaseModel):
    """The rating configuration that produced a history or a settings response."""

    starting_rating: str
    k_factor: str
    margin_weight: str
    margin_cap: str
    season_regression: str


class EloConfigResponse(EloConfigValues):
    """A league's saved Elo settings (or the defaults)."""

    league_id: int


class EloConfigUpdateRequest(BaseModel):
    """Admin-supplied Elo settings, validated to the documented ranges."""

    model_config = ConfigDict(extra="forbid")

    starting_rating: Decimal = Field(ge=Decimal("1000"), le=Decimal("2000"))
    k_factor: Decimal = Field(ge=Decimal("1"), le=Decimal("100"))
    margin_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    margin_cap: Decimal = Field(ge=Decimal("1"), le=Decimal("200"))
    season_regression: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))


class EloWeek(BaseModel):
    """One chart slot: a completed regular-season week, including cup weeks."""

    index: int
    season: int
    week: int
    is_cup_week: bool
    is_season_start: bool
    rated: bool


class EloSeasonBoundary(BaseModel):
    """A season's first chart index, used for chart markers and labels."""

    season: int
    week_index: int


class EloWeekReference(BaseModel):
    """The season and week where a peak or low occurred."""

    season: int
    week: int


class EloSeasonRating(BaseModel):
    """One franchise's rating within a season, with the post-reset baseline."""

    season: int
    start_rating: str
    end_rating: str
    change: str
    rated_weeks: int


class EloTeam(BaseModel):
    """One franchise's running series and summary values."""

    team_key: str
    team_id: int
    name: str
    owner_name: str | None
    aliases: list[str]
    first_season: int
    last_season: int
    series: list[str | None]
    seasons: list[EloSeasonRating]
    current: str
    last_change: str
    season_change: str
    peak: str
    peak_at: EloWeekReference | None
    low: str
    low_at: EloWeekReference | None
    rated_weeks: int


class EloUnratedTeam(BaseModel):
    """A team with no rated weeks, so the page can say so instead of drawing a flat line."""

    team_key: str
    name: str
    reason: str


class EloWarning(BaseModel):
    """A skipped piece of stored data, surfaced without internal detail or credentials."""

    season: int
    code: str
    message: str


class EloHistoryResponse(BaseModel):
    """Full Elo history for one league and one mode."""

    league_id: int
    mode: EloMode
    seasons: list[int]
    config: EloConfigValues
    weeks: list[EloWeek]
    season_boundaries: list[EloSeasonBoundary]
    teams: list[EloTeam]
    unrated_teams: list[EloUnratedTeam]
    warnings: list[EloWarning]


def config_values(config: EloConfig) -> EloConfigValues:
    """Project domain settings into their string wire form."""
    return EloConfigValues(
        starting_rating=format_setting(config.starting_rating),
        k_factor=format_setting(config.k_factor),
        margin_weight=format_setting(config.margin_weight),
        margin_cap=format_setting(config.margin_cap),
        season_regression=format_setting(config.season_regression),
    )


def to_config_response(league_id: int, config: EloConfig) -> EloConfigResponse:
    """Build the settings response for GET and PUT."""
    values = config_values(config)
    return EloConfigResponse(league_id=league_id, **values.model_dump())


def _season_rating(row: DomainSeasonRating) -> EloSeasonRating:
    """Project one season summary with display-rounded strings."""
    return EloSeasonRating(
        season=row.season,
        start_rating=format_rating(row.start_rating),
        end_rating=format_rating(row.end_rating),
        change=format_rating(row.change),
        rated_weeks=row.rated_weeks,
    )


def _week_ref(row: DomainWeekReference | None) -> EloWeekReference | None:
    """Project a peak/low reference, preserving the "starting rating" null case."""
    if row is None:
        return None
    return EloWeekReference(season=row.season, week=row.week)


def _team(view: EloTeamView) -> EloTeam:
    """Project one franchise with all exact values serialized as strings."""
    history = view.history
    return EloTeam(
        team_key=view.team_key,
        team_id=view.team_id,
        name=view.name,
        owner_name=view.owner_name,
        aliases=list(view.aliases),
        first_season=history.first_season,
        last_season=history.last_season,
        series=[format_rating(value) if value is not None else None for value in history.series],
        seasons=[_season_rating(row) for row in history.seasons],
        current=format_rating(history.current),
        last_change=format_rating(history.last_change),
        season_change=format_rating(history.season_change),
        peak=format_rating(history.peak),
        peak_at=_week_ref(history.peak_at),
        low=format_rating(history.low),
        low_at=_week_ref(history.low_at),
        rated_weeks=history.rated_weeks,
    )


def _unrated(row: ServiceUnratedTeam) -> EloUnratedTeam:
    """Project an unrated-team entry (already provider/credential-free)."""
    return EloUnratedTeam(team_key=row.team_key, name=row.name, reason=row.reason)


def _warning(row: ServiceWarning) -> EloWarning:
    """Project one stored-data warning."""
    return EloWarning(season=row.season, code=row.code, message=row.message)


def to_history_response(view: EloHistoryView) -> EloHistoryResponse:
    """Build the full wire response for one mode."""
    return EloHistoryResponse(
        league_id=view.league_id,
        mode=view.mode,
        seasons=list(view.seasons),
        config=config_values(view.config),
        weeks=[
            EloWeek(
                index=index,
                season=week.season,
                week=week.week,
                is_cup_week=week.is_cup_week,
                is_season_start=week.is_season_start,
                rated=week.rated,
            )
            for index, week in enumerate(view.weeks)
        ],
        season_boundaries=[
            EloSeasonBoundary(season=boundary.season, week_index=boundary.week_index)
            for boundary in view.season_boundaries
        ],
        teams=[_team(team) for team in view.teams],
        unrated_teams=[_unrated(team) for team in view.unrated_teams],
        warnings=[_warning(warning) for warning in view.warnings],
    )


__all__: list[str] = [
    "EloConfigResponse",
    "EloConfigUpdateRequest",
    "EloConfigValues",
    "EloHistoryResponse",
    "format_rating",
    "format_setting",
    "to_config_response",
    "to_history_response",
]
