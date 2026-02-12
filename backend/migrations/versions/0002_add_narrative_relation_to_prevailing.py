"""Add relation_to_prevailing to narratives.

Revision ID: 0002_relation
Revises: 0001_initial_schema
Create Date: 2026-02-08

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_relation"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "narratives",
        sa.Column("relation_to_prevailing", sa.String(24), nullable=False, server_default="consensus"),
    )
    op.create_index("ix_narratives_relation_to_prevailing", "narratives", ["relation_to_prevailing"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_narratives_relation_to_prevailing", table_name="narratives")
    op.drop_column("narratives", "relation_to_prevailing")
