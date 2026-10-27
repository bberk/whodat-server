"""Add the per-league WAPDate display flag.

Revision ID: 0009_league_show_wapdate
Revises: 0008_elo_config
Create Date: 2026-10-26

The WAPDate standings section is a four-week worst-team quirk that not every league uses. A league
admin can hide it from the standings page; the preference belongs to the league, not to a season,
and it is display-only (no stored VP, win, or points-for value changes). Every existing league
keeps showing the section, so the column is non-null with a true server default and no backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_league_show_wapdate"
down_revision: str | None = "0008_elo_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``league.show_wapdate`` defaulting to true.

    Batch mode rebuilds the table on SQLite, so the non-null column with its server default
    round-trips there as well as on Postgres. Existing rows receive the default, which keeps every
    league showing the section exactly as before.
    """
    with op.batch_alter_table("league") as batch:
        batch.add_column(
            sa.Column("show_wapdate", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    """Drop the display flag; the standings page shows the section again."""
    with op.batch_alter_table("league") as batch:
        batch.drop_column("show_wapdate")
