"""Add trade tracker configuration and multi-draft auction budget tables.

Revision ID: 0012_trade_tracker
Revises: 0011_projected_scores
Create Date: 2026-11-07

Dynasty and keeper fantasy football leagues track trades announced in Discord and exchange auction
draft dollars across multiple future draft years. This migration creates:
- ``league.has_trades_enabled``: per-league opt-in display flag.
- ``league_trade_config``: per-league settings for the GitHub trade ledger repository, Discord
  channel ID, starting auction budget, and team/owner alias mapping.
- ``league_trade``: ingested trades recorded from the Git repository.
- ``league_trade_party``: participants in each trade with players and draft picks exchanged.
- ``league_trade_budget_delta``: auction dollar adjustments partitioned by draft year.

Cascading foreign keys ensure child-first deletion cleanups succeed on Postgres.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_trade_tracker"
down_revision: str | None = "0011_projected_scores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the trade tracker tables and add the league opt-in flag."""
    with op.batch_alter_table("league") as batch:
        batch.add_column(
            sa.Column(
                "has_trades_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    op.create_table(
        "league_trade_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "league_id",
            sa.Integer(),
            sa.ForeignKey(
                "league.id",
                name="fk_league_trade_config_league_id_league",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("discord_channel_id", sa.Text(), nullable=True),
        sa.Column("repo_owner", sa.Text(), nullable=False, server_default="bberk"),
        sa.Column("repo_name", sa.Text(), nullable=False, server_default="whodat-trades"),
        sa.Column("branch", sa.Text(), nullable=False, server_default="main"),
        sa.Column("github_token_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "base_auction_budget",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="200.00",
        ),
        sa.Column("team_aliases", sa.JSON(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_commit", sa.Text(), nullable=True),
        sa.Column("last_sync_status", sa.Text(), nullable=False, server_default="idle"),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("last_discord_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discord_sync_status", sa.Text(), nullable=False, server_default="idle"),
        sa.Column("last_discord_sync_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("league_id", name="uq_league_trade_config_league_id"),
    )

    op.create_table(
        "league_trade",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "league_id",
            sa.Integer(),
            sa.ForeignKey(
                "league.id",
                name="fk_league_trade_league_id_league",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("external_trade_id", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agreement_season", sa.Integer(), nullable=False),
        sa.Column("is_settled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("discord_url", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("raw_yaml", sa.Text(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "league_id", "external_trade_id", name="uq_league_trade_league_external_id"
        ),
    )
    op.create_index("ix_league_trade_league_id", "league_trade", ["league_id"])

    op.create_table(
        "league_trade_party",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "trade_id",
            sa.Integer(),
            sa.ForeignKey(
                "league_trade.id",
                name="fk_league_trade_party_trade_id_trade",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "league_id",
            sa.Integer(),
            sa.ForeignKey(
                "league.id",
                name="fk_league_trade_party_league_id_league",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey(
                "owner.id",
                name="fk_league_trade_party_owner_id_owner",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("franchise_key", sa.Text(), nullable=True),
        sa.Column("team_name_raw", sa.Text(), nullable=False),
        sa.Column("players_sent", sa.JSON(), nullable=False),
        sa.Column("players_received", sa.JSON(), nullable=False),
        sa.Column("draft_picks_sent", sa.JSON(), nullable=False),
        sa.Column("draft_picks_received", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_league_trade_party_trade_id", "league_trade_party", ["trade_id"])
    op.create_index("ix_league_trade_party_league_id", "league_trade_party", ["league_id"])
    op.create_index("ix_league_trade_party_owner_id", "league_trade_party", ["owner_id"])

    op.create_table(
        "league_trade_budget_delta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "party_id",
            sa.Integer(),
            sa.ForeignKey(
                "league_trade_party.id",
                name="fk_league_trade_budget_delta_party_id_party",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "league_id",
            sa.Integer(),
            sa.ForeignKey(
                "league.id",
                name="fk_league_trade_budget_delta_league_id_league",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("draft_year", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_budget_delta_league_year",
        "league_trade_budget_delta",
        ["league_id", "draft_year"],
    )
    op.create_index(
        "ix_budget_delta_party_id",
        "league_trade_budget_delta",
        ["party_id"],
    )


def downgrade() -> None:
    """Drop the trade tracker tables and remove the league opt-in flag."""
    op.drop_table("league_trade_budget_delta")
    op.drop_table("league_trade_party")
    op.drop_table("league_trade")
    op.drop_table("league_trade_config")
    with op.batch_alter_table("league") as batch:
        batch.drop_column("has_trades_enabled")
