"""Add theme.created_by (system | user).

Revision ID: 0012_theme_created_by
Revises: 0011_theme_instruments
Create Date: 2026-02-13

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_theme_created_by"
down_revision = "0011_theme_instruments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("themes", sa.Column("created_by", sa.String(32), server_default="system", nullable=False))
    op.create_index("ix_themes_created_by", "themes", ["created_by"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_themes_created_by", table_name="themes")
    op.drop_column("themes", "created_by")
