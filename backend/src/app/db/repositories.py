"""Typed, transaction-neutral repositories for synchronized league data.

Repositories flush their writes so generated ids and updates are visible to subsequent
repository calls in the same session. They never commit or roll back: transaction ownership
belongs to the calling service.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TypeVar

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import League, LeagueEloConfig, LeagueSeason, Matchup, Owner, Score, Team

RowT = TypeVar("RowT")


@dataclass(frozen=True)
class UpsertResult[RowT]:
    """Return an upserted row and whether its persisted values changed."""

    row: RowT
    changed: bool


@dataclass(frozen=True)
class WeeklyVPValues:
    """Decimal persistence values for one team's total VP and four components.

    Conversion from exact domain Fractions is deliberately left to the caller; this class
    defines no rounding or quantization policy.
    """

    victory_points: Decimal
    h2h: Decimal
    top_half: Decimal
    high: Decimal
    low: Decimal


class SyncRepository:
    """Persist and load normalized league sync data using a caller-owned session."""

    def __init__(self, session: Session) -> None:
        """Bind repository methods to a session without taking transaction ownership."""
        self._session = session

    def upsert_league(
        self,
        provider: str,
        external_id: str,
        name: str,
        league_metadata: Mapping[str, object],
        provider_config_ref: str,
    ) -> UpsertResult[League]:
        """Insert or update a league by its provider and external id natural key."""
        values = {
            "name": name,
            "league_metadata": dict(league_metadata),
            "provider_config_ref": provider_config_ref,
        }
        row = self._session.scalar(
            select(League).where(League.provider == provider, League.external_id == external_id)
        )
        if row is None:
            row = League(provider=provider, external_id=external_id, **values)
            self._session.add(row)
            self._session.flush()
            return UpsertResult(row, True)

        changed = self._assign_changed(row, values)
        if changed:
            self._session.flush()
        return UpsertResult(row, changed)

    def upsert_league_season(
        self, league_id: int, season: int, metadata: Mapping[str, object]
    ) -> UpsertResult[LeagueSeason]:
        """Insert or update one league season's settings by its league id and season.

        Settings are scoped to the single season, so refreshing one season leaves every other
        season's stored settings untouched.
        """
        values = {"league_season_metadata": dict(metadata)}
        row = self._session.scalar(
            select(LeagueSeason).where(
                LeagueSeason.league_id == league_id, LeagueSeason.season == season
            )
        )
        if row is None:
            row = LeagueSeason(league_id=league_id, season=season, **values)
            self._session.add(row)
            self._session.flush()
            return UpsertResult(row, True)

        changed = self._assign_changed(row, values)
        if changed:
            self._session.flush()
        return UpsertResult(row, changed)

    def set_league_season_last_refreshed(
        self, league_id: int, season: int, refreshed_at: datetime
    ) -> None:
        """Record the instant a provider-backed sync of this season finished successfully.

        The write is flushed but not committed. The caller decides when the timestamp is visible;
        the sync service sets it only after the whole season has been ingested and recomputed.
        """
        self._session.execute(
            update(LeagueSeason)
            .where(LeagueSeason.league_id == league_id, LeagueSeason.season == season)
            .values(last_refreshed_at=refreshed_at)
        )
        self._session.flush()

    def upsert_owner(
        self, league_id: int, external_id: str, display_name: str
    ) -> UpsertResult[Owner]:
        """Insert or update an owner by league id and provider external id."""
        values = {"display_name": display_name}
        row = self._session.scalar(
            select(Owner).where(Owner.league_id == league_id, Owner.external_id == external_id)
        )
        if row is None:
            row = Owner(league_id=league_id, external_id=external_id, **values)
            self._session.add(row)
            self._session.flush()
            return UpsertResult(row, True)

        changed = self._assign_changed(row, values)
        if changed:
            self._session.flush()
        return UpsertResult(row, changed)

    def upsert_team(
        self,
        league_id: int,
        season: int,
        external_id: str,
        name: str,
        division: str | None,
        owner_id: int | None,
    ) -> UpsertResult[Team]:
        """Insert or update a season team by its league, season, and external id."""
        values = {"name": name, "division": division, "owner_id": owner_id}
        row = self._session.scalar(
            select(Team).where(
                Team.league_id == league_id,
                Team.season == season,
                Team.external_id == external_id,
            )
        )
        if row is None:
            row = Team(
                league_id=league_id,
                season=season,
                external_id=external_id,
                **values,
            )
            self._session.add(row)
            self._session.flush()
            return UpsertResult(row, True)

        changed = self._assign_changed(row, values)
        if changed:
            self._session.flush()
        return UpsertResult(row, changed)

    def upsert_matchup(
        self,
        league_id: int,
        season: int,
        week: int,
        home_team_id: int,
        away_team_id: int | None,
        is_playoff: bool,
        is_complete: bool,
    ) -> UpsertResult[Matchup]:
        """Insert or update a matchup by league, season, week, and home team.

        The home team identifies the stored matchup natural key, including byes where the away
        team is absent.
        """
        values = {
            "away_team_id": away_team_id,
            "is_playoff": is_playoff,
            "is_complete": is_complete,
        }
        row = self._session.scalar(
            select(Matchup).where(
                Matchup.league_id == league_id,
                Matchup.season == season,
                Matchup.week == week,
                Matchup.home_team_id == home_team_id,
            )
        )
        if row is None:
            row = Matchup(
                league_id=league_id,
                season=season,
                week=week,
                home_team_id=home_team_id,
                **values,
            )
            self._session.add(row)
            self._session.flush()
            return UpsertResult(row, True)

        changed = self._assign_changed(row, values)
        if changed:
            self._session.flush()
        return UpsertResult(row, changed)

    def upsert_score(
        self,
        team_id: int,
        league_id: int,
        season: int,
        week: int,
        points: Decimal,
    ) -> UpsertResult[Score]:
        """Insert or correct a team's score, preserving VP until the week is recomputed."""
        if not isinstance(points, Decimal):
            raise TypeError("points must be Decimal")
        values = {"points": points}
        row = self._session.scalar(
            select(Score).where(
                Score.team_id == team_id,
                Score.season == season,
                Score.week == week,
            )
        )
        if row is None:
            row = Score(
                team_id=team_id,
                league_id=league_id,
                season=season,
                week=week,
                points=points,
                victory_points=Decimal(0),
                vp_h2h=Decimal(0),
                vp_top_half=Decimal(0),
                vp_high=Decimal(0),
                vp_low=Decimal(0),
            )
            self._session.add(row)
            self._session.flush()
            return UpsertResult(row, True)

        # League identity is inherited from its team and the unique key is team/season/week.
        changed = self._assign_changed(row, values)
        if changed:
            self._session.flush()
        return UpsertResult(row, changed)

    def delete_matchup(self, matchup: Matchup) -> None:
        """Delete one stale scheduled matchup inside the caller's transaction."""
        self._session.delete(matchup)
        self._session.flush()

    def delete_score(self, score: Score) -> None:
        """Delete one stale team-week score inside the caller's transaction."""
        self._session.delete(score)
        self._session.flush()

    def get_league(self, provider: str, external_id: str) -> League | None:
        """Return a league by its natural key, or None if it is not stored."""
        return self._session.scalar(
            select(League).where(League.provider == provider, League.external_id == external_id)
        )

    def get_league_season(self, league_id: int, season: int) -> LeagueSeason | None:
        """Return one league season's settings, or None if that season is not stored."""
        return self._session.scalar(
            select(LeagueSeason).where(
                LeagueSeason.league_id == league_id, LeagueSeason.season == season
            )
        )

    def get_elo_config(self, league_id: int) -> LeagueEloConfig | None:
        """Return a league's saved Elo settings, or None when it uses the defaults."""
        return self._session.scalar(
            select(LeagueEloConfig).where(LeagueEloConfig.league_id == league_id)
        )

    def upsert_elo_config(
        self,
        league_id: int,
        *,
        starting_rating: Decimal,
        k_factor: Decimal,
        margin_weight: Decimal,
        margin_cap: Decimal,
        season_regression: Decimal,
    ) -> LeagueEloConfig:
        """Create or update the single Elo settings row for a league.

        Values must already be validated Decimals; the repository only persists them and never
        applies rounding or default policy.
        """
        values = {
            "starting_rating": starting_rating,
            "k_factor": k_factor,
            "margin_weight": margin_weight,
            "margin_cap": margin_cap,
            "season_regression": season_regression,
        }
        row = self.get_elo_config(league_id)
        if row is None:
            row = LeagueEloConfig(league_id=league_id, **values)
            self._session.add(row)
            self._session.flush()
            return row
        if self._assign_changed(row, values):
            self._session.flush()
        return row

    def list_league_seasons(self, league_id: int) -> list[LeagueSeason]:
        """Return every stored season for a league in ascending season order."""
        return list(
            self._session.scalars(
                select(LeagueSeason)
                .where(LeagueSeason.league_id == league_id)
                .order_by(LeagueSeason.season)
            ).all()
        )

    def get_owner(self, league_id: int, external_id: str) -> Owner | None:
        """Return an owner by its league-scoped external id, or None if absent."""
        return self._session.scalar(
            select(Owner).where(Owner.league_id == league_id, Owner.external_id == external_id)
        )

    def get_teams(self, league_id: int, season: int) -> list[Team]:
        """Return all teams for a league season in stable primary-key order."""
        return list(
            self._session.scalars(
                select(Team)
                .where(Team.league_id == league_id, Team.season == season)
                .order_by(Team.id)
            ).all()
        )

    def list_teams(self, league_id: int) -> list[Team]:
        """Return every season-specific team for a league, ascending by season then id."""
        return list(
            self._session.scalars(
                select(Team).where(Team.league_id == league_id).order_by(Team.season, Team.id)
            ).all()
        )

    def list_matchups(self, league_id: int) -> list[Matchup]:
        """Return every stored matchup for a league in chronological, stable order."""
        return list(
            self._session.scalars(
                select(Matchup)
                .where(Matchup.league_id == league_id)
                .order_by(Matchup.season, Matchup.week, Matchup.id)
            ).all()
        )

    def list_scores(self, league_id: int) -> list[Score]:
        """Return every stored score for a league in chronological, stable order."""
        return list(
            self._session.scalars(
                select(Score)
                .where(Score.league_id == league_id)
                .order_by(Score.season, Score.week, Score.team_id)
            ).all()
        )

    def get_week_matchups(self, league_id: int, season: int, week: int) -> list[Matchup]:
        """Return every stored matchup for a league season week in stable order."""
        return list(
            self._session.scalars(
                select(Matchup)
                .where(
                    Matchup.league_id == league_id,
                    Matchup.season == season,
                    Matchup.week == week,
                )
                .order_by(Matchup.home_team_id)
            ).all()
        )

    def get_week_scores(self, league_id: int, season: int, week: int) -> list[Score]:
        """Return every stored score for a league season week in stable team order."""
        return list(
            self._session.scalars(
                select(Score)
                .where(
                    Score.league_id == league_id,
                    Score.season == season,
                    Score.week == week,
                )
                .order_by(Score.team_id)
            ).all()
        )

    def persist_week_vp(
        self,
        league_id: int,
        season: int,
        week: int,
        values_by_team: Mapping[int, WeeklyVPValues],
    ) -> None:
        """Persist weekly totals and all components for exactly the stored week score rows.

        The supplied team ids must match the week's score rows exactly, preventing a partial
        recompute from leaving stale VP on other teams. Writes are flushed but not committed.
        """
        if any(
            not isinstance(value, Decimal)
            for values in values_by_team.values()
            for value in (
                values.victory_points,
                values.h2h,
                values.top_half,
                values.high,
                values.low,
            )
        ):
            raise TypeError("all VP values must be Decimal")

        scores = self.get_week_scores(league_id, season, week)
        score_ids = {score.team_id for score in scores}
        supplied_ids = set(values_by_team)
        if score_ids != supplied_ids:
            raise ValueError(
                "VP team ids must exactly match stored week scores "
                f"(missing={sorted(score_ids - supplied_ids)}, "
                f"unexpected={sorted(supplied_ids - score_ids)})"
            )

        for score in scores:
            values = values_by_team[score.team_id]
            score.victory_points = values.victory_points
            score.vp_h2h = values.h2h
            score.vp_top_half = values.top_half
            score.vp_high = values.high
            score.vp_low = values.low
        if scores:
            self._session.flush()

    @staticmethod
    def _assign_changed(row: RowT, values: Mapping[str, object]) -> bool:
        """Assign changed field values to a mapped row and return whether anything differed."""
        changed = False
        for name, value in values.items():
            if getattr(row, name) != value:
                setattr(row, name, value)
                changed = True
        return changed
