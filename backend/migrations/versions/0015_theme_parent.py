"""Add themes.parent_theme_id for theme hierarchy.

Revision ID: 0015_theme_parent
Revises: 0014_document_content_type
Create Date: 2026-02-18

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_theme_parent"
down_revision = "0014_document_content_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("themes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_theme_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_themes_parent_theme_id_themes",
            "themes",
            ["parent_theme_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_themes_parent_theme_id", ["parent_theme_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("themes", schema=None) as batch_op:
        batch_op.drop_index("ix_themes_parent_theme_id")
        batch_op.drop_constraint("fk_themes_parent_theme_id_themes", type_="foreignkey")
        batch_op.drop_column("parent_theme_id")
