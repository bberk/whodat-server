"""Add invite-only accounts and many-to-many league memberships.

Revision ID: 0004_auth_memberships
Revises: 0003_league_season
Create Date: 2026-10-19

``app_user`` loses its league-specific owner association and gains a role. Owner associations and
encrypted ESPN credentials now live on ``user_league``, one row per (user, league) pair, and
``invite`` stores only a one-way hash of each invite code.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_auth_memberships"
down_revision: str | None = "0003_league_season"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_SERVER_DEFAULT = sa.text("'member'")


def upgrade() -> None:
    """Add the role column, drop the account owner link, and create auth tables."""
    with op.batch_alter_table("app_user") as batch:
        batch.add_column(
            sa.Column("role", sa.Text(), nullable=False, server_default=ROLE_SERVER_DEFAULT)
        )
        batch.drop_column("owner_id")

    op.create_table(
        "invite",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default=ROLE_SERVER_DEFAULT),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["league_id"], ["league.id"], name="fk_invite_league_id_league"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_invite_code_hash"),
    )
    op.create_index("ix_invite_league_id", "invite", ["league_id"])

    op.create_table(
        "user_league",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("espn_s2_encrypted", sa.Text(), nullable=True),
        sa.Column("espn_swid_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_user_league_user_id_app_user"
        ),
        sa.ForeignKeyConstraint(
            ["league_id"], ["league.id"], name="fk_user_league_league_id_league"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owner.id"], name="fk_user_league_owner_id_owner"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "league_id", name="uq_user_league_user_id_league_id"),
    )
    op.create_index("ix_user_league_league_id", "user_league", ["league_id"])


def downgrade() -> None:
    """Drop memberships and invites, then restore the account-level owner link."""
    op.drop_table("user_league")
    op.drop_table("invite")

    with op.batch_alter_table("app_user") as batch:
        batch.drop_column("role")
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_app_user_owner_id_owner",
            "owner",
            ["owner_id"],
            ["id"],
        )
