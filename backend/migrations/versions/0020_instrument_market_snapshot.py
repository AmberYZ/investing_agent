"""Add instrument_market_snapshot for per-ticker cached metrics (basket rows).

Revision ID: 0020_instrument_market_snapshot
Revises: 0019_theme_market_snapshot
Create Date: 2026-03-06

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_instrument_market_snapshot"
down_revision = "0019_theme_market_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "instrument_market_snapshot" in insp.get_table_names():
        return
    op.create_table(
        "instrument_market_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "snapshot_date", name="uq_instrument_market_snapshot_symbol_date"),
    )
    op.create_index(op.f("ix_instrument_market_snapshot_symbol"), "instrument_market_snapshot", ["symbol"], unique=False)
    op.create_index(op.f("ix_instrument_market_snapshot_snapshot_date"), "instrument_market_snapshot", ["snapshot_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_instrument_market_snapshot_snapshot_date"), table_name="instrument_market_snapshot")
    op.drop_index(op.f("ix_instrument_market_snapshot_symbol"), table_name="instrument_market_snapshot")
    op.drop_table("instrument_market_snapshot")
