"""Add provider-projected active-week scores.

Revision ID: 0011_projected_scores
Revises: 0010_team_final_standing
Create Date: 2026-11-01

Projections are external provider data, so they cannot be computed at read time: the standings
endpoints never call ESPN, and a member may not hold credentials. Sync stores the active week's
projected team scores here and records the season's last successful projection refresh separately
from a full-season sync. A projection is never a stored result and never earns VP; the standings
service computes the projected week's VP from these rows only when the caller asks for it.

The table is child-first in the league/season deletion order: it references both ``team`` and
``league``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_projected_scores"
down_revision: str | None = "0010_team_final_standing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the projections table and add the season's projection-refresh timestamp."""
    op.create_table(
        "projected_score",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("points", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], name="fk_projected_score_team_id_team"),
        sa.ForeignKeyConstraint(
            ["league_id"], ["league.id"], name="fk_projected_score_league_id_league"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "team_id", "season", "week", name="uq_projected_score_team_season_week"
        ),
    )
    op.create_index(
        "ix_projected_score_league_season_week",
        "projected_score",
        ["league_id", "season", "week"],
        unique=False,
    )
    with op.batch_alter_table("league_season") as batch:
        batch.add_column(
            sa.Column("projections_refreshed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Drop the projections table and the season projection-refresh timestamp."""
    with op.batch_alter_table("league_season") as batch:
        batch.drop_column("projections_refreshed_at")
    op.drop_index("ix_projected_score_league_season_week", table_name="projected_score")
    op.drop_table("projected_score")
