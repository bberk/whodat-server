"""Add the optional per-season cup week.

Revision ID: 0006_cup_week
Revises: 0005_invite_optional_league
Create Date: 2026-10-21

A cup week is a single optional regular-season week where head-to-head VP and the W/L/T record do
not apply while high-score, top-half, worst-score VP and points for still count. ``NULL`` means the
season has no cup week, so existing seasons keep their current behaviour.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_cup_week"
down_revision: str | None = "0005_invite_optional_league"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``league_season.cup_week`` column.

    Batch mode rebuilds the table on SQLite, so the column round-trips there as well as on
    Postgres. Existing rows keep ``NULL``, which means no cup week.
    """
    with op.batch_alter_table("league_season") as batch:
        batch.add_column(sa.Column("cup_week", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the cup-week column, returning every season to normal scoring."""
    with op.batch_alter_table("league_season") as batch:
        batch.drop_column("cup_week")
