#!/usr/bin/env python3
"""
Print all ingest jobs as JSON (for the admin page when the backend HTTP route is not available).

Run from the backend directory:
    .venv/bin/python scripts/list_ingest_jobs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from sqlalchemy.orm import joinedload

from app.db import SessionLocal
from app.models import IngestJob


def list_jobs(limit: int = 500) -> list[dict]:
    db = SessionLocal()
    try:
        jobs = (
            db.query(IngestJob)
            .options(joinedload(IngestJob.document))
            .order_by(IngestJob.created_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()
    out = []
    for j in jobs:
        doc = j.document
        out.append({
            "id": j.id,
            "document_id": j.document_id,
            "filename": doc.filename if doc else None,
            "source_name": doc.source_name if doc else None,
            "source_type": doc.source_type if doc else None,
            "status": j.status,
            "error_message": j.error_message,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        })
    return out


if __name__ == "__main__":
    limit = 500
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass
    jobs = list_jobs(limit=limit)
    print(json.dumps(jobs))
