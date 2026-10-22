"""Add the per-season last-refreshed timestamp.

Revision ID: 0007_season_last_refreshed
Revises: 0006_cup_week
Create Date: 2026-10-22

The admin seasons table shows when each stored season last synced from the provider. The value is
written only by a successful provider sync (add league, add season, per-season refresh, or the CLI
sync) and never by admin edits such as the cup week. Existing seasons keep ``NULL`` ("Never").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_season_last_refreshed"
down_revision: str | None = "0006_cup_week"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``league_season.last_refreshed_at`` timestamp.

    Batch mode rebuilds the table on SQLite, so the column round-trips there as well as on
    Postgres. Existing rows keep ``NULL``, which the UI displays as "Never".
    """
    with op.batch_alter_table("league_season") as batch:
        batch.add_column(sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop the timestamp, returning every season to "unknown last refresh"."""
    with op.batch_alter_table("league_season") as batch:
        batch.drop_column("last_refreshed_at")
