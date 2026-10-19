"""Normalized SQLAlchemy models for leagues, teams, matchups, and scores."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
VALID_ROLES: frozenset[str] = frozenset({ROLE_ADMIN, ROLE_MEMBER})


def _checked_role(value: str) -> str:
    """Return a supported role, raising for anything outside the documented values."""
    if value not in VALID_ROLES:
        raise ValueError(f"invalid role {value!r}; expected one of {sorted(VALID_ROLES)}")
    return value


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
    seasons: Mapped[list[LeagueSeason]] = relationship(
        back_populates="league", order_by="LeagueSeason.season"
    )


class LeagueSeason(TimestampMixin, Base):
    """Provider settings for one league season.

    Settings that can differ between seasons (regular season length, team count, division count,
    scoring type, playoff configuration) live here rather than on ``league``, so a sync of one
    season never overwrites another season's settings. ``league.name`` stays the single league
    name; there is deliberately no per-season name column.
    """

    __tablename__ = "league_season"
    __table_args__ = (
        UniqueConstraint("league_id", "season", name="uq_league_season_league_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("league.id", name="fk_league_season_league_id_league"), nullable=False
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    league_season_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    league: Mapped[League] = relationship(back_populates="seasons")


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
    """An account with an email, password hash, and role.

    The role is validated here rather than by a database enum so that SQLite and Postgres share
    the same schema while unsupported values still fail before they are persisted. Owner
    associations live on :class:`UserLeague`, not on the account.
    """

    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("email", name="uq_app_user_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default=ROLE_MEMBER, server_default=ROLE_MEMBER
    )

    @validates("role")
    def _validate_role(self, _key: str, value: str) -> str:
        return _checked_role(value)


class Invite(TimestampMixin, Base):
    """A league invite that grants admin or member access until it expires.

    Only a one-way hash of the raw code is stored. ``expires_at`` is supplied by the caller (the
    admin CLI applies the documented seven-day default); the repository reports whether a stored
    invite is still valid.
    """

    __tablename__ = "invite"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_invite_code_hash"),
        Index("ix_invite_league_id", "league_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("league.id", name="fk_invite_league_id_league"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default=ROLE_MEMBER, server_default=ROLE_MEMBER
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    league: Mapped[League] = relationship()

    @validates("role")
    def _validate_role(self, _key: str, value: str) -> str:
        return _checked_role(value)


class UserLeague(TimestampMixin, Base):
    """A user's membership in a league, with optional owner association and credentials.

    The two credential columns hold the self-describing encrypted tokens produced by the security
    layer; this module never sees plaintext credentials. A user may belong to many leagues and a
    league may have many members, but each (user, league) pair is unique.
    """

    __tablename__ = "user_league"
    __table_args__ = (
        UniqueConstraint("user_id", "league_id", name="uq_user_league_user_id_league_id"),
        Index("ix_user_league_league_id", "league_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", name="fk_user_league_user_id_app_user"), nullable=False
    )
    league_id: Mapped[int] = mapped_column(
        ForeignKey("league.id", name="fk_user_league_league_id_league"), nullable=False
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("owner.id", name="fk_user_league_owner_id_owner"), nullable=True
    )
    espn_s2_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    espn_swid_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    user: Mapped[AppUser] = relationship()
    league: Mapped[League] = relationship()
    owner: Mapped[Owner | None] = relationship()
