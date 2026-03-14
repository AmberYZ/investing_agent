"""Add theme.track_items for user-defined things to track.

Revision ID: 0021_theme_track_items
Revises: 0020_instrument_market_snapshot
Create Date: 2026-03-14

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021_theme_track_items"
down_revision = "0020_instrument_market_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("themes")]
    if "track_items" in cols:
        return
    op.add_column("themes", sa.Column("track_items", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("themes", "track_items")
