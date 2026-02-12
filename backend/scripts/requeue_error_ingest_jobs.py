#!/usr/bin/env python3
"""
Reset ingest jobs in 'error' back to 'queued' so the worker will retry them.

Use this after fixing the cause of failures (e.g. API key, network) or to retry
jobs that were cancelled via cancel_ingest_jobs.py.

Run from the backend directory:
    .venv/bin/python scripts/requeue_error_ingest_jobs.py
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


def requeue_error_jobs() -> int:
    with engine.begin() as conn:
        result = conn.execute(
            update(IngestJob)
            .where(IngestJob.status == "error")
            .values(
                status="queued",
                started_at=None,
                finished_at=None,
                error_message=None,
            )
        )
        return result.rowcount


if __name__ == "__main__":
    n = requeue_error_jobs()
    print(f"Requeued {n} error ingest job(s) (error -> queued). Worker will retry them.")
