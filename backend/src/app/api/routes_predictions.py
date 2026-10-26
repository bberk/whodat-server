"""Playoff-odds route (ARCHITECTURE.md section 8).

The endpoint is member-only like the standings routes: unauthenticated callers get 401 and
non-members or unknown leagues get 404. Invalid iteration or seed values are structured 422s from
FastAPI's query validation, so no service work starts for them. A simulation is a CPU-bound sync
handler, which Starlette runs in its threadpool, and a light per-user-per-league limiter protects
the CPU from repeated unique-seed requests.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AfterValidator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.params import LeagueIdPath, SeasonPath
from app.api.rate_limit import RateLimiter
from app.api.routes_standings import MemberDep, _raise_standings_error
from app.api.schemas_auth import PublicUser, error_detail
from app.api.schemas_predictions import PlayoffOddsResponse, to_playoff_odds_response
from app.db.session import get_session
from app.domain.predictions import (
    DEFAULT_STRENGTH_WEIGHT,
    STRENGTH_WEIGHT_MAX,
    STRENGTH_WEIGHT_MIN,
    normalize_strength_weight,
)
from app.services.prediction_service import (
    CACHE_CONTROL,
    CACHE_MAX_ENTRIES,
    DEFAULT_ITERATIONS,
    MAX_ITERATIONS,
    MAX_SEED,
    MIN_ITERATIONS,
    PredictionService,
    iterations_cap_for_role,
)
from app.services.standings_service import StandingsServiceError

router = APIRouter(prefix="/api/v1", tags=["playoff-odds"])

CurrentUserDep = Annotated[PublicUser, Depends(get_current_user)]

#: Requests allowed per member per league per window. This protects simulation CPU, not auth.
_PREDICTION_RATE_LIMIT = 30
_PREDICTION_RATE_WINDOW_SECONDS = 60.0
_LIMITER = RateLimiter(
    limit=_PREDICTION_RATE_LIMIT,
    window_seconds=_PREDICTION_RATE_WINDOW_SECONDS,
    max_keys=CACHE_MAX_ENTRIES * 4,
)


def get_prediction_limiter() -> RateLimiter:
    """Return the process-wide playoff-odds limiter (tests override it with a fake clock)."""
    return _LIMITER


LimiterDep = Annotated[RateLimiter, Depends(get_prediction_limiter)]


def check_prediction_rate_limit(
    league_id: LeagueIdPath,
    current_user: CurrentUserDep,
    limiter: LimiterDep,
) -> None:
    """Reject a member's repeated playoff-odds requests for one league with 429."""
    decision = limiter.check(f"{current_user.id}|{league_id}|playoff-odds")
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail("rate_limited", "Playoff odds are rate limited"),
            headers={"Retry-After": str(decision.retry_after)},
        )


RateLimitDep = Annotated[None, Depends(check_prediction_rate_limit)]


def get_prediction_service(
    session: Annotated[Session, Depends(get_session)],
) -> PredictionService:
    """Build the playoff-odds service on the request's shared session."""
    return PredictionService(session)


PredictionServiceDep = Annotated[PredictionService, Depends(get_prediction_service)]

IterationsQuery = Annotated[
    int,
    Query(
        ge=MIN_ITERATIONS,
        le=MAX_ITERATIONS,
        description="Number of simulated seasons.",
    ),
]
SeedQuery = Annotated[
    int | None,
    Query(ge=0, le=MAX_SEED, description="Explicit seed; derived from the inputs when omitted."),
]
StrengthWeightQuery = Annotated[
    Decimal,
    Query(
        ge=STRENGTH_WEIGHT_MIN,
        le=STRENGTH_WEIGHT_MAX,
        allow_inf_nan=False,
        description=(
            "Team-strength weight: 0 makes every remaining matchup even, 1 is the default model, "
            "and up to 10 amplifies stronger teams. Decimals are accepted, with at most 18 "
            "decimal places."
        ),
    ),
    AfterValidator(normalize_strength_weight),
]


@router.get(
    "/leagues/{league_id}/seasons/{season}/playoff-odds",
    response_model=PlayoffOddsResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": "The iteration count is above the authenticated role's cap.",
        },
        status.HTTP_409_CONFLICT: {
            "description": "The season is stored but is not the league's current season.",
        },
    },
)
def get_playoff_odds(
    league_id: LeagueIdPath,
    season: SeasonPath,
    response: Response,
    _member: MemberDep,
    current_user: CurrentUserDep,
    _rate: RateLimitDep,
    service: PredictionServiceDep,
    iterations: IterationsQuery = DEFAULT_ITERATIONS,
    seed: SeedQuery = None,
    strength_weight: StrengthWeightQuery = DEFAULT_STRENGTH_WEIGHT,
) -> PlayoffOddsResponse:
    """Return per-team playoff, bye, division-title, and championship probabilities.

    Only the league's latest stored season is simulated. An older stored season returns a
    structured 409 ``season_not_current`` without reading simulation inputs or touching the cache;
    an unknown league or unstored season keeps the standings-style 404. ``strength_weight`` scales
    team strength in future weeks only; it never changes stored data, the provider, or current
    totals. Regular members may request at most 10,000 iterations; admins may request up to 100,000.
    A larger request returns a structured 403 before any simulation runs.
    """
    cap = iterations_cap_for_role(current_user.role)
    if iterations > cap:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(
                "iterations_not_allowed",
                f"This role may request at most {cap:,} simulated seasons",
            ),
        )
    try:
        odds = service.get_playoff_odds(
            league_id,
            season,
            iterations=iterations,
            seed=seed,
            strength_weight=strength_weight,
        )
    except StandingsServiceError as error:
        _raise_standings_error(error)
    response.headers["Cache-Control"] = CACHE_CONTROL
    return to_playoff_odds_response(odds)
