"""Theme merge reinforcement: store source label + embedding when user merges themes.

Revision ID: 0007_theme_merge_reinforcement
Revises: 0006_narrative_created_at
Create Date: 2026-02-09

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0007_theme_merge_reinforcement"
down_revision = "0006_narrative_created_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if inspect(conn).has_table("theme_merge_reinforcement"):
        return
    op.create_table(
        "theme_merge_reinforcement",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_label", sa.String(512), nullable=False),
        sa.Column("source_embedding", sa.JSON(), nullable=True),
        sa.Column("target_theme_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_theme_id"], ["themes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_theme_merge_reinforcement_source_label"),
        "theme_merge_reinforcement",
        ["source_label"],
        unique=False,
    )
    op.create_index(
        op.f("ix_theme_merge_reinforcement_target_theme_id"),
        "theme_merge_reinforcement",
        ["target_theme_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_theme_merge_reinforcement_created_at"),
        "theme_merge_reinforcement",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not inspect(conn).has_table("theme_merge_reinforcement"):
        return
    op.drop_index(op.f("ix_theme_merge_reinforcement_created_at"), table_name="theme_merge_reinforcement")
    op.drop_index(op.f("ix_theme_merge_reinforcement_target_theme_id"), table_name="theme_merge_reinforcement")
    op.drop_index(op.f("ix_theme_merge_reinforcement_source_label"), table_name="theme_merge_reinforcement")
    op.drop_table("theme_merge_reinforcement")
