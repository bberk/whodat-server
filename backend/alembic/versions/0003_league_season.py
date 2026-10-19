"""Create the per-season league settings table.

Revision ID: 0003_league_season
Revises: 0002_initial_schema
Create Date: 2026-10-18

Each league season gets its own row so a season can be refreshed independently and per-season
provider settings are not overwritten by another season. ``league`` keeps its own ``metadata``
column (provider-level settings) and its ``name``; neither moves here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_league_season"
down_revision: str | None = "0002_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the league_season table and its natural-key constraint."""
    op.create_table(
        "league_season",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["league_id"], ["league.id"], name="fk_league_season_league_id_league"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("league_id", "season", name="uq_league_season_league_season"),
    )


def downgrade() -> None:
    """Drop the per-season settings table."""
    op.drop_table("league_season")
