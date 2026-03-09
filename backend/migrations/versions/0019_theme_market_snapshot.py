"""Add theme_market_snapshot for daily cached market metrics (trading digest).

Revision ID: 0019_theme_market_snapshot
Revises: 0018_theme_trading_digest
Create Date: 2026-03-06

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_theme_market_snapshot"
down_revision = "0018_theme_trading_digest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "theme_market_snapshot" in insp.get_table_names():
        return
    op.create_table(
        "theme_market_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["theme_id"], ["themes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("theme_id", "snapshot_date", name="uq_theme_market_snapshot_theme_date"),
    )
    op.create_index(op.f("ix_theme_market_snapshot_snapshot_date"), "theme_market_snapshot", ["snapshot_date"], unique=False)
    op.create_index(op.f("ix_theme_market_snapshot_theme_id"), "theme_market_snapshot", ["theme_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_theme_market_snapshot_theme_id"), table_name="theme_market_snapshot")
    op.drop_index(op.f("ix_theme_market_snapshot_snapshot_date"), table_name="theme_market_snapshot")
    op.drop_table("theme_market_snapshot")
