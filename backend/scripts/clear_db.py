#!/usr/bin/env python3
"""
Clear all rows from the database tables. Tables and schema are left intact.

Run from the backend directory:
    .venv/bin/python scripts/clear_db.py

Or from repo root:
    backend/.venv/bin/python backend/scripts/clear_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend is on path when run as script
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from sqlalchemy import delete

from app.db import engine
from app.models import (
    Base,
    Chunk,
    Document,
    Evidence,
    IngestJob,
    Narrative,
    NarrativeMentionsDaily,
    Theme,
    ThemeAlias,
    ThemeMentionsDaily,
    ThemeRelationDaily,
)


def clear_all_tables() -> None:
    """Delete all rows in dependency order (children before parents)."""
    tables_in_order = [
        Evidence,
        NarrativeMentionsDaily,
        ThemeMentionsDaily,
        ThemeRelationDaily,
        ThemeAlias,
        Chunk,
        IngestJob,
        Narrative,
        Theme,
        Document,
    ]

    with engine.begin() as conn:
        for model in tables_in_order:
            result = conn.execute(delete(model))
            print(f"  {model.__tablename__}: deleted {result.rowcount} row(s)")


if __name__ == "__main__":
    print("Clearing all data (tables will remain)...")
    clear_all_tables()
    print("Done.")
