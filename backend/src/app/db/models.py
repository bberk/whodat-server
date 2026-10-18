"""Normalized SQLAlchemy models for leagues, teams, matchups, and scores."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    """Provide creation and modification timestamps to each persisted entity."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class League(TimestampMixin, Base):
    """A provider-backed fantasy football league."""

    __tablename__ = "league"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_league_provider_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    league_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    provider_config_ref: Mapped[str] = mapped_column(Text, nullable=False)


class Owner(TimestampMixin, Base):
    """A league member who may own one or more season-specific teams."""

    __tablename__ = "owner"
    __table_args__ = (
        UniqueConstraint("league_id", "external_id", name="uq_owner_league_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("league.id", name="fk_owner_league_id_league"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)


class Team(TimestampMixin, Base):
    """A league team in a particular season."""

    __tablename__ = "team"
    __table_args__ = (
        UniqueConstraint(
            "league_id", "season", "external_id", name="uq_team_league_season_external_id"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("league.id", name="fk_team_league_id_league"), nullable=False
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    division: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owner.id", name="fk_team_owner_id_owner"), nullable=True
    )


class Matchup(TimestampMixin, Base):
    """A scheduled home/away pairing for a given week and season."""

    __tablename__ = "matchup"
    __table_args__ = (
        UniqueConstraint(
            "league_id", "season", "week", "home_team_id", name="uq_matchup_league_season_week_home"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("league.id", name="fk_matchup_league_id_league"), nullable=False
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    home_team_id: Mapped[int] = mapped_column(
        ForeignKey("team.id", name="fk_matchup_home_team_id_team"), nullable=False
    )
    away_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("team.id", name="fk_matchup_away_team_id_team"), nullable=True
    )
    is_playoff: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)


class Score(TimestampMixin, Base):
    """A team's points and VP components for one season week."""

    __tablename__ = "score"
    __table_args__ = (
        UniqueConstraint("team_id", "season", "week", name="uq_score_team_season_week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(
        ForeignKey("team.id", name="fk_score_team_id_team"), nullable=False
    )
    league_id: Mapped[int] = mapped_column(
        ForeignKey("league.id", name="fk_score_league_id_league"), nullable=False
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    victory_points: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    vp_h2h: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    vp_top_half: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    vp_high: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    vp_low: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)


class AppUser(TimestampMixin, Base):
    """An account optionally linked to a league owner."""

    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("email", name="uq_app_user_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owner.id", name="fk_app_user_owner_id_owner"), nullable=True
    )
