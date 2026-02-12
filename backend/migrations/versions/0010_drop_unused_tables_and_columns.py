"""Drop unused tables and columns.

Revision ID: 0010_drop_unused_tables_and_columns
Revises: 0009_theme_sub_theme_metrics
Create Date: 2026-02-10

Drops: narrative_aliases, feedback; documents.language, published_at, source_metadata;
evidence.chunk_id, confidence; narratives.stance, status.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0010_drop_unused_tables_and_columns"
down_revision = "0009_theme_sub_theme_metrics"
branch_labels = None
depends_on = None


def _has_table(conn, name: str) -> bool:
    return inspect(conn).has_table(name)


def _has_column(conn, table: str, column: str) -> bool:
    if not _has_table(conn, table):
        return False
    cols = [c["name"] for c in inspect(conn).get_columns(table)]
    return column in cols


def _has_index(conn, table: str, index_name: str) -> bool:
    if not _has_table(conn, table):
        return False
    indexes = inspect(conn).get_indexes(table)
    return any(idx["name"] == index_name for idx in indexes)


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # Clean up any leftover temp tables from a previous failed run (SQLite batch)
    if dialect == "sqlite":
        for tmp in ("_alembic_tmp_documents", "_alembic_tmp_evidence", "_alembic_tmp_narratives"):
            try:
                op.execute(f"DROP TABLE IF EXISTS {tmp}")
            except Exception:
                pass

    # Drop unused tables (order: no FKs between them)
    if _has_table(conn, "narrative_aliases"):
        op.drop_table("narrative_aliases")
    if _has_table(conn, "feedback"):
        op.drop_table("feedback")

    # Drop columns from documents (one batch per table for SQLite)
    docs_drop = [c for c in ("language", "published_at", "source_metadata") if _has_column(conn, "documents", c)]
    if docs_drop:
        if dialect == "sqlite":
            with op.batch_alter_table("documents", schema=None) as batch_op:
                for c in docs_drop:
                    batch_op.drop_column(c)
        else:
            for c in docs_drop:
                op.drop_column("documents", c)

    # Drop columns from evidence
    ev_drop = [c for c in ("chunk_id", "confidence") if _has_column(conn, "evidence", c)]
    if ev_drop:
        if dialect == "sqlite":
            with op.batch_alter_table("evidence", schema=None) as batch_op:
                for c in ev_drop:
                    batch_op.drop_column(c)
        else:
            for c in ev_drop:
                op.drop_column("evidence", c)

    # Drop columns from narratives (drop indexes first, then one batch)
    if _has_index(conn, "narratives", "ix_narratives_stance"):
        op.drop_index("ix_narratives_stance", table_name="narratives")
    if _has_index(conn, "narratives", "ix_narratives_status"):
        op.drop_index("ix_narratives_status", table_name="narratives")
    nar_drop = [c for c in ("stance", "status") if _has_column(conn, "narratives", c)]
    if nar_drop:
        if dialect == "sqlite":
            with op.batch_alter_table("narratives", schema=None) as batch_op:
                for c in nar_drop:
                    batch_op.drop_column(c)
        else:
            for c in nar_drop:
                op.drop_column("narratives", c)


def downgrade() -> None:
    # Re-create tables and columns for rollback (minimal definitions)
    op.create_table(
        "narrative_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("narrative_id", sa.Integer(), nullable=False),
        sa.Column("alias_statement", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(32), server_default="system"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_by", sa.String(64), server_default="user"),
    )

    conn = op.get_bind()
    dialect = conn.dialect.name

    def add_col(table: str, column: sa.Column):
        if dialect == "sqlite":
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.add_column(column)
        else:
            op.add_column(table, column)

    add_col("documents", sa.Column("language", sa.String(32), nullable=True))
    add_col("documents", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    add_col("documents", sa.Column("source_metadata", sa.JSON(), nullable=True))
    add_col("evidence", sa.Column("chunk_id", sa.Integer(), nullable=True))
    add_col("evidence", sa.Column("confidence", sa.Float(), nullable=True))
    add_col("narratives", sa.Column("stance", sa.String(16), server_default="unlabeled"))
    add_col("narratives", sa.Column("status", sa.String(24), server_default="unlabeled"))
