#!/usr/bin/env python3
"""
Cancel all queued and processing ingest jobs (set status=error so worker won't pick them up).

Run from the backend directory:
    .venv/bin/python scripts/cancel_ingest_jobs.py
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


def cancel_pending_jobs() -> int:
    with engine.begin() as conn:
        result = conn.execute(
            update(IngestJob)
            .where(IngestJob.status.in_(["queued", "processing"]))
            .values(status="error", error_message="cancelled")
        )
        return result.rowcount


if __name__ == "__main__":
    n = cancel_pending_jobs()
    print(f"Cancelled {n} ingest job(s).")
