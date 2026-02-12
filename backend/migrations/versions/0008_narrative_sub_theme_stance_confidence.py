"""Add narratives.sub_theme, narrative_stance, confidence_level.

Revision ID: 0008_narrative_sub_theme_stance_confidence
Revises: 0007_theme_merge_reinforcement
Create Date: 2026-02-10

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0008_narrative_sub_theme_stance_confidence"
down_revision = "0007_theme_merge_reinforcement"
branch_labels = None
depends_on = None


def _narratives_has_column(conn, name: str) -> bool:
    insp = inspect(conn)
    cols = [c["name"] for c in insp.get_columns("narratives")]
    return name in cols


def _narratives_has_index(conn, index_name: str) -> bool:
    insp = inspect(conn)
    indexes = insp.get_indexes("narratives")
    return any(idx["name"] == index_name for idx in indexes)


def upgrade() -> None:
    conn = op.get_bind()
    if not _narratives_has_column(conn, "sub_theme"):
        op.add_column(
            "narratives",
            sa.Column("sub_theme", sa.String(128), nullable=True),
        )
    if not _narratives_has_column(conn, "narrative_stance"):
        op.add_column(
            "narratives",
            sa.Column("narrative_stance", sa.String(16), nullable=True),
        )
    if not _narratives_has_column(conn, "confidence_level"):
        op.add_column(
            "narratives",
            sa.Column("confidence_level", sa.String(16), nullable=True),
        )
    if not _narratives_has_index(conn, "ix_narratives_sub_theme"):
        op.create_index(
            op.f("ix_narratives_sub_theme"),
            "narratives",
            ["sub_theme"],
            unique=False,
        )
    if not _narratives_has_index(conn, "ix_narratives_narrative_stance"):
        op.create_index(
            op.f("ix_narratives_narrative_stance"),
            "narratives",
            ["narrative_stance"],
            unique=False,
        )
    if not _narratives_has_index(conn, "ix_narratives_theme_id_sub_theme"):
        op.create_index(
            "ix_narratives_theme_id_sub_theme",
            "narratives",
            ["theme_id", "sub_theme"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_narratives_theme_id_sub_theme", table_name="narratives")
    op.drop_index(op.f("ix_narratives_narrative_stance"), table_name="narratives")
    op.drop_index(op.f("ix_narratives_sub_theme"), table_name="narratives")
    op.drop_column("narratives", "confidence_level")
    op.drop_column("narratives", "narrative_stance")
    op.drop_column("narratives", "sub_theme")
