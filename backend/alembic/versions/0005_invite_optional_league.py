"""Allow admin invites that are not tied to a league.

Revision ID: 0005_invite_optional_league
Revises: 0004_auth_memberships
Create Date: 2026-10-19

An admin invite can be minted before any league exists, so ``invite.league_id`` becomes nullable.
The foreign key and its index stay in place; member invites continue to carry a league.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_invite_optional_league"
down_revision: str | None = "0004_auth_memberships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make ``invite.league_id`` nullable, preserving the foreign key and index.

    Batch mode rebuilds the table on SQLite so the column round-trips there as well as on Postgres.
    """
    with op.batch_alter_table("invite") as batch:
        batch.alter_column("league_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Restore ``NOT NULL`` on ``invite.league_id``.

    This is only valid while every stored invite belongs to a league. Null-league invites cannot
    satisfy the restored constraint, so the downgrade fails with a clear error before touching the
    schema instead of surfacing a table-rebuild or constraint error.
    """
    null_count = (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM invite WHERE league_id IS NULL"))
        .scalar_one()
    )
    if null_count:
        raise RuntimeError(
            "cannot downgrade 0005_invite_optional_league: "
            f"{null_count} invite row(s) have no league_id; "
            "delete or assign them to a league before downgrading"
        )

    with op.batch_alter_table("invite") as batch:
        batch.alter_column("league_id", existing_type=sa.Integer(), nullable=False)
