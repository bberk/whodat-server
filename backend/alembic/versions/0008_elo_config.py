"""Add the per-league Elo settings table.

Revision ID: 0008_elo_config
Revises: 0007_season_last_refreshed
Create Date: 2026-10-22

The History page's rating formula is configurable per league. A missing row means "use the
defaults", so no backfill is needed: every existing league keeps the documented start rating,
K-factor, margin bonus, and season regression until an admin saves settings. History itself stays
derived from stored matchups and scores; this table holds settings only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_elo_config"
down_revision: str | None = "0007_season_last_refreshed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the one-row-per-league Elo settings table."""
    op.create_table(
        "elo_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "league_id",
            sa.Integer(),
            sa.ForeignKey("league.id", name="fk_elo_config_league_id_league"),
            nullable=False,
        ),
        sa.Column("starting_rating", sa.Numeric(10, 4), nullable=False, server_default="1500"),
        sa.Column("k_factor", sa.Numeric(8, 4), nullable=False, server_default="24"),
        sa.Column("margin_weight", sa.Numeric(8, 4), nullable=False, server_default="0.25"),
        sa.Column("margin_cap", sa.Numeric(8, 4), nullable=False, server_default="50"),
        sa.Column(
            "season_regression",
            sa.Numeric(12, 10),
            nullable=False,
            server_default="0.3333333333",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("league_id", name="uq_elo_config_league_id"),
    )


def downgrade() -> None:
    """Drop the settings table; every league returns to the defaults."""
    op.drop_table("elo_config")
