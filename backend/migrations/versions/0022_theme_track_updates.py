"""Add theme.track_updates for storing latest status from digest refresh.

Revision ID: 0022_theme_track_updates
Revises: 0021_theme_track_items
Create Date: 2026-03-14

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0022_theme_track_updates"
down_revision = "0021_theme_track_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("themes")]
    if "track_updates" in cols:
        return
    op.add_column("themes", sa.Column("track_updates", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("themes", "track_updates")
