"""Theme instruments (stocks/ETFs per theme).

Revision ID: 0011_theme_instruments
Revises: 0010_drop_unused_tables_and_columns
Create Date: 2026-02-12

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_theme_instruments"
down_revision = "0010_drop_unused_tables_and_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "theme_instruments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("type", sa.String(16), nullable=False, server_default="stock"),
        sa.Column("source", sa.String(24), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["theme_id"], ["themes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("theme_id", "symbol", name="uq_theme_instruments_theme_symbol"),
    )
    op.create_index("ix_theme_instruments_theme_id", "theme_instruments", ["theme_id"], unique=False)
    op.create_index("ix_theme_instruments_symbol", "theme_instruments", ["symbol"], unique=False)
    op.create_index("ix_theme_instruments_source", "theme_instruments", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_theme_instruments_source", table_name="theme_instruments")
    op.drop_index("ix_theme_instruments_symbol", table_name="theme_instruments")
    op.drop_index("ix_theme_instruments_theme_id", table_name="theme_instruments")
    op.drop_table("theme_instruments")
