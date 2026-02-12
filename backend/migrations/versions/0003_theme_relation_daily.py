"""Add theme_relation_daily for relation-type breakdown by day.

Revision ID: 0003_theme_relation_daily
Revises: 0002_relation
Create Date: 2026-02-08

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_theme_relation_daily"
down_revision = "0002_relation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # SQLite: avoid "table already exists" when create_all() created it first
    if conn.dialect.name == "sqlite":
        r = conn.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='theme_relation_daily'"
        ))
        if r.scalar() is not None:
            return
    op.create_table(
        "theme_relation_daily",
        sa.Column("theme_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("consensus_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contrarian_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refinement_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_angle_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["theme_id"], ["themes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("theme_id", "date"),
    )


def downgrade() -> None:
    op.drop_table("theme_relation_daily")
