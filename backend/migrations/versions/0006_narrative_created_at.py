"""Add narratives.created_at for when the narrative first appeared.

Revision ID: 0006_narrative_created_at
Revises: 0005_document_modified_at
Create Date: 2026-02-09

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_narrative_created_at"
down_revision = "0005_document_modified_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "narratives",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE narratives SET created_at = first_seen WHERE created_at IS NULL")
    with op.batch_alter_table("narratives") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    op.create_index(
        op.f("ix_narratives_created_at"),
        "narratives",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_narratives_created_at"), table_name="narratives")
    op.drop_column("narratives", "created_at")
