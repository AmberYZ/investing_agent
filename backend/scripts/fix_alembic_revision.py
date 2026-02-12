#!/usr/bin/env python3
"""Fix alembic_version when it points to a revision that no longer exists (e.g. 0008_sub_theme).
Sets version to 0007_theme_merge_reinforcement so 'alembic upgrade head' can run 0008 and 0009.
Run from backend dir: python scripts/fix_alembic_revision.py
Then: alembic upgrade head
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.db import engine

TARGET_REVISION = "0007_theme_merge_reinforcement"


def main() -> None:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        current = row[0] if row else None
        print(f"Current alembic_version: {current!r}")
        conn.execute(text("UPDATE alembic_version SET version_num = :rev"), {"rev": TARGET_REVISION})
        conn.commit()
        print(f"Updated to: {TARGET_REVISION!r}")
    print("Now run: alembic upgrade head")


if __name__ == "__main__":
    main()
