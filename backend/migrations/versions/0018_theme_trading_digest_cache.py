"""Add theme_trading_digest_cache for basket trading-oriented view.

Revision ID: 0018_theme_trading_digest
Revises: 0017_drop_mega_themes
Create Date: 2026-03-06

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_theme_trading_digest"
down_revision = "0017_drop_mega_themes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "theme_trading_digest_cache" in insp.get_table_names():
        return
    op.create_table(
        "theme_trading_digest_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(16), server_default="30d", nullable=False),
        sa.Column("prevailing", sa.Text(), nullable=True),
        sa.Column("what_changed", sa.Text(), nullable=True),
        sa.Column("what_market_waiting", sa.Text(), nullable=True),
        sa.Column("worries", sa.Text(), nullable=True),
        sa.Column("trade_ideas", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["theme_id"], ["themes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_theme_trading_digest_cache_theme_id"), "theme_trading_digest_cache", ["theme_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_theme_trading_digest_cache_theme_id"), table_name="theme_trading_digest_cache")
    op.drop_table("theme_trading_digest_cache")
