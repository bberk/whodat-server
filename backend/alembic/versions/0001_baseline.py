"""baseline

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-17

No-op baseline. The real schema is added in milestone M2 (see ARCHITECTURE.md section 4). It
exists so that `alembic upgrade head` and `alembic downgrade base` both succeed in M0.
"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the baseline (nothing yet)."""


def downgrade() -> None:
    """Drop the baseline (nothing yet)."""
