"""Add documents.content_type for text/HTML ingest (e.g. Substack).

Revision ID: 0014_document_content_type
Revises: 0013_theme_user_notes
Create Date: 2026-02-14

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_document_content_type"
down_revision = "0013_theme_user_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("content_type", sa.String(64), nullable=False, server_default="application/pdf"),
    )


def downgrade() -> None:
    op.drop_column("documents", "content_type")
