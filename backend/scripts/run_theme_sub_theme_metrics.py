#!/usr/bin/env python3
"""Compute theme_sub_theme_metrics (novelty_type, narrative_stage) from narrative statistics.
Run after run_daily_aggregations. Can be scheduled (e.g. weekly) or run on-demand."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.aggregations import compute_theme_sub_theme_metrics
from app.db import SessionLocal, init_db

if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        compute_theme_sub_theme_metrics(db, theme_id=None)
        print("Theme sub-theme metrics computed.")
    finally:
        db.close()
