"""Add theme.embedding for semantic similarity (theme deduplication).

Revision ID: 0004_theme_embedding
Revises: 0003_theme_relation_daily
Create Date: 2026-02-08

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_theme_embedding"
down_revision = "0003_theme_relation_daily"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "themes",
        sa.Column("embedding", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("themes", "embedding")
