"""Create the normalized initial application schema.

Revision ID: 0002_initial_schema
Revises: 0001_baseline
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_initial_schema"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all normalized application tables and their natural-key constraints."""
    op.create_table(
        "league",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("provider_config_ref", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "external_id", name="uq_league_provider_external_id"),
    )
    op.create_table(
        "owner",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["league_id"], ["league.id"], name="fk_owner_league_id_league"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("league_id", "external_id", name="uq_owner_league_external_id"),
    )
    op.create_table(
        "team",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("division", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["league_id"], ["league.id"], name="fk_team_league_id_league"),
        sa.ForeignKeyConstraint(["owner_id"], ["owner.id"], name="fk_team_owner_id_owner"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "league_id", "season", "external_id", name="uq_team_league_season_external_id"
        ),
    )
    op.create_table(
        "matchup",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("home_team_id", sa.Integer(), nullable=False),
        sa.Column("away_team_id", sa.Integer(), nullable=True),
        sa.Column("is_playoff", sa.Boolean(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["away_team_id"], ["team.id"], name="fk_matchup_away_team_id_team"),
        sa.ForeignKeyConstraint(["home_team_id"], ["team.id"], name="fk_matchup_home_team_id_team"),
        sa.ForeignKeyConstraint(["league_id"], ["league.id"], name="fk_matchup_league_id_league"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "league_id", "season", "week", "home_team_id", name="uq_matchup_league_season_week_home"
        ),
    )
    op.create_table(
        "score",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("points", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("victory_points", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("vp_h2h", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("vp_top_half", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("vp_high", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("vp_low", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["league_id"], ["league.id"], name="fk_score_league_id_league"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], name="fk_score_team_id_team"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "season", "week", name="uq_score_team_season_week"),
    )
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owner.id"], name="fk_app_user_owner_id_owner"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
    )


def downgrade() -> None:
    """Drop application tables in dependency-safe reverse order."""
    op.drop_table("app_user")
    op.drop_table("score")
    op.drop_table("matchup")
    op.drop_table("team")
    op.drop_table("owner")
    op.drop_table("league")
