"""Add theme.user_notes.

Revision ID: 0013_theme_user_notes
Revises: 0012_theme_created_by
Create Date: 2026-02-13

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_theme_user_notes"
down_revision = "0012_theme_created_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("themes", sa.Column("user_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("themes", "user_notes")
