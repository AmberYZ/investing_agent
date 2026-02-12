"""Add documents.modified_at for document timestamp (e.g. file mtime).

Revision ID: 0005_document_modified_at
Revises: 0004_theme_embedding
Create Date: 2026-02-08

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_document_modified_at"
down_revision = "0004_theme_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_documents_modified_at"),
        "documents",
        ["modified_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_modified_at"), table_name="documents")
    op.drop_column("documents", "modified_at")
