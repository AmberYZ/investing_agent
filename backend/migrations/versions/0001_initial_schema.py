"""Initial schema for documents, chunks, themes, narratives, evidence, and related tables.

This revision bootstraps the core data model described in the project plan.
It delegates actual DDL creation to SQLAlchemy's Base.metadata.create_all so
that the tables stay aligned with the ORM models in app.models.
"""
from __future__ import annotations

from alembic import op

from app.models import Base


# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables defined on Base.metadata.

    This includes:
    - documents
    - ingest_jobs
    - chunks
    - themes
    - theme_aliases
    - narratives
    - narrative_aliases
    - evidence
    - feedback
    - theme_mentions_daily
    - narrative_mentions_daily
    plus associated indexes and constraints.
    """
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop all tables defined on Base.metadata.

    This is a coarse-grained downgrade that removes the core schema.
    """
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)

