"""Add universe_insights_cache for cross-universe market insights page.

Revision ID: 0023_universe_insights
Revises: 0022_theme_track_updates
Create Date: 2026-06-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_universe_insights"
down_revision = "0022_theme_track_updates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "universe_insights_cache" in insp.get_table_names():
        return
    op.create_table(
        "universe_insights_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False, server_default="14d"),
        sa.Column("insights_json", sa.Text(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period", name="uq_universe_insights_cache_period"),
    )


def downgrade() -> None:
    op.drop_table("universe_insights_cache")
