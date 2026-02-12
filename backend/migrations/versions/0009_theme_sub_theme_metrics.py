"""Add theme_sub_theme_metrics and theme_sub_theme_mentions_daily.

Revision ID: 0009_theme_sub_theme_metrics
Revises: 0008_narrative_sub_theme_stance_confidence
Create Date: 2026-02-10

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0009_theme_sub_theme_metrics"
down_revision = "0008_narrative_sub_theme_stance_confidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if insp.has_table("theme_sub_theme_metrics"):
        return
    op.create_table(
        "theme_sub_theme_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_id", sa.Integer(), nullable=False),
        sa.Column("sub_theme", sa.String(128), nullable=False),
        sa.Column("novelty_type", sa.String(24), nullable=True),
        sa.Column("narrative_stage", sa.String(24), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["theme_id"], ["themes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("theme_id", "sub_theme", name="uq_theme_sub_theme_metrics_theme_sub_theme"),
    )
    op.create_index(
        op.f("ix_theme_sub_theme_metrics_theme_id"),
        "theme_sub_theme_metrics",
        ["theme_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_theme_sub_theme_metrics_sub_theme"),
        "theme_sub_theme_metrics",
        ["sub_theme"],
        unique=False,
    )

    op.create_table(
        "theme_sub_theme_mentions_daily",
        sa.Column("theme_id", sa.Integer(), nullable=False),
        sa.Column("sub_theme", sa.String(128), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("doc_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["theme_id"], ["themes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("theme_id", "sub_theme", "date"),
    )


def downgrade() -> None:
    op.drop_table("theme_sub_theme_mentions_daily")
    op.drop_index(op.f("ix_theme_sub_theme_metrics_sub_theme"), table_name="theme_sub_theme_metrics")
    op.drop_index(op.f("ix_theme_sub_theme_metrics_theme_id"), table_name="theme_sub_theme_metrics")
    op.drop_table("theme_sub_theme_metrics")
