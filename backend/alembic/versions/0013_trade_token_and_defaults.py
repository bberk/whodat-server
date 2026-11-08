"""Update trade tracker config default repo values and add Discord token column.

Revision ID: 0013_trade_token_and_defaults
Revises: 0012_trade_tracker
Create Date: 2026-11-07

Removes default repository owner and repository name strings, setting the server default to empty
string (""), and adds an encrypted Discord bot token column (``discord_token_encrypted``) to support
private Discord server announcements ingestion.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_trade_token_and_defaults"
down_revision: str | None = "0012_trade_tracker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Clear default repo values and add encrypted Discord token column."""
    with op.batch_alter_table("league_trade_config") as batch:
        batch.alter_column(
            "repo_owner",
            server_default="",
            existing_type=sa.Text(),
            existing_nullable=False,
        )
        batch.alter_column(
            "repo_name",
            server_default="",
            existing_type=sa.Text(),
            existing_nullable=False,
        )
        batch.add_column(sa.Column("discord_token_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    """Restore hardcoded repo defaults and drop encrypted Discord token column."""
    with op.batch_alter_table("league_trade_config") as batch:
        batch.drop_column("discord_token_encrypted")
        batch.alter_column(
            "repo_name",
            server_default="whodat-trades",
            existing_type=sa.Text(),
            existing_nullable=False,
        )
        batch.alter_column(
            "repo_owner",
            server_default="bberk",
            existing_type=sa.Text(),
            existing_nullable=False,
        )
