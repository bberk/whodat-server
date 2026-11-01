"""Add each season team's final finishing position.

Revision ID: 0010_team_final_standing
Revises: 0009_league_show_wapdate
Create Date: 2026-11-01

The provider reports each team's final position for a season once the playoffs are decided
(ESPN's ``rankFinal``/``rankCalculatedFinal``). Storing it on the season's team row lets the
standings page mark the champion and podium and lets the history page count championships and
last-place regular-season finishes. The value includes the playoffs and is never derived from
regular-season Victory Points. Existing rows keep ``NULL`` ("not reported yet"), so no champion is
claimed for a season that has not been re-synced.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_team_final_standing"
down_revision: str | None = "0009_league_show_wapdate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable final standing to each season team row.

    Batch mode rebuilds the table on SQLite, so the column round-trips there as well as on
    Postgres. Existing teams keep ``NULL`` until a provider sync reports a final rank.
    """
    with op.batch_alter_table("team") as batch:
        batch.add_column(sa.Column("final_standing", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the final standing; the standings and history pages stop claiming season records."""
    with op.batch_alter_table("team") as batch:
        batch.drop_column("final_standing")
