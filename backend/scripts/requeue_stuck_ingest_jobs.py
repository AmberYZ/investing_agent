#!/usr/bin/env python3
"""
Reset ingest jobs stuck in 'processing' (e.g. after worker crash) back to 'queued'
so the worker will pick them up on next run.

Run from the backend directory:
    .venv/bin/python scripts/requeue_stuck_ingest_jobs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from sqlalchemy import update

from app.db import engine
from app.models import IngestJob


def requeue_stuck_jobs() -> int:
    with engine.begin() as conn:
        result = conn.execute(
            update(IngestJob)
            .where(IngestJob.status == "processing")
            .values(status="queued", started_at=None, error_message=None)
        )
        return result.rowcount


if __name__ == "__main__":
    n = requeue_stuck_jobs()
    print(f"Requeued {n} stuck ingest job(s) (processing -> queued).")
