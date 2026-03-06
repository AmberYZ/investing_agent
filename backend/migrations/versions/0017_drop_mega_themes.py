"""Drop mega_themes, narrative_mega_themes, mega_theme_mentions_daily (revert LLM megathemes).

Revision ID: 0017_drop_mega_themes
Revises: 0016_mega_themes
Create Date: 2026-03-05

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_drop_mega_themes"
down_revision = "0016_mega_themes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "mega_theme_mentions_daily" in tables:
        op.drop_index(op.f("ix_mega_theme_mentions_daily_date"), table_name="mega_theme_mentions_daily")
        op.drop_table("mega_theme_mentions_daily")
    if "narrative_mega_themes" in tables:
        op.drop_index(op.f("ix_narrative_mega_themes_narrative_id"), table_name="narrative_mega_themes")
        op.drop_index(op.f("ix_narrative_mega_themes_mega_theme_id"), table_name="narrative_mega_themes")
        op.drop_table("narrative_mega_themes")
    if "mega_themes" in tables:
        op.drop_index(op.f("ix_mega_themes_label"), table_name="mega_themes")
        op.drop_table("mega_themes")


def downgrade() -> None:
    op.create_table(
        "mega_themes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mega_themes_label"), "mega_themes", ["label"], unique=False)

    op.create_table(
        "narrative_mega_themes",
        sa.Column("narrative_id", sa.Integer(), nullable=False),
        sa.Column("mega_theme_id", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("source", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(["mega_theme_id"], ["mega_themes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["narrative_id"], ["narratives.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("narrative_id", "mega_theme_id"),
    )
    op.create_index(op.f("ix_narrative_mega_themes_mega_theme_id"), "narrative_mega_themes", ["mega_theme_id"], unique=False)
    op.create_index(op.f("ix_narrative_mega_themes_narrative_id"), "narrative_mega_themes", ["narrative_id"], unique=False)

    op.create_table(
        "mega_theme_mentions_daily",
        sa.Column("mega_theme_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("doc_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("share_of_voice", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["mega_theme_id"], ["mega_themes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("mega_theme_id", "date"),
    )
    op.create_index(op.f("ix_mega_theme_mentions_daily_date"), "mega_theme_mentions_daily", ["date"], unique=False)
