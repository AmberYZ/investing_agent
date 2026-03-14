#!/usr/bin/env python3
"""
One-time migration: copy blobs from local storage to GCS and update document URIs in the DB.

Use when switching from STORAGE_BACKEND=local to STORAGE_BACKEND=gcs. Reads Document rows
from the current database; for each gcs_raw_uri / gcs_text_uri that is file://, reads the
file from local disk, uploads to GCS with the same key convention (raw/..., text/<id>.txt),
then updates the document record to the new gs:// URI.

Prereqs:
  - GCS_BUCKET (and optionally GCS_PREFIX) set in .env; STORAGE_BACKEND can still be local
    for this run since we read from local and write to GCS explicitly.
  - pip install -r backend/requirements.txt -r backend/requirements-gcp.txt
  - gcloud auth application-default login (or GOOGLE_APPLICATION_CREDENTIALS)

Usage:
  Run from the backend directory so DATABASE_URL and LOCAL_STORAGE_DIR resolve to the same
  dev.db and .local_storage the backend uses (paths are cwd-relative):
    cd backend && PYTHONPATH=. .venv/bin/python ../scripts/migrate_local_storage_to_gcs.py [--dry-run]
  Recommended: run with --dry-run first to list what would be migrated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure backend is on path and .env is loaded (settings loads from repo root when imported)
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root / "backend") not in sys.path:
    sys.path.insert(0, str(_repo_root / "backend"))

from app.settings import settings
from app.db import SessionLocal
from app.models import Document
from app.storage.local import LocalStorage
from app.storage.gcs import GcsStorage


def _file_uri_to_storage_key(uri: str) -> str | None:
    """Derive storage key from a file:// URI (path after 'raw/' or 'text/' under the storage root)."""
    if not uri.startswith("file://"):
        return None
    path = Path(uri[7:].lstrip("/"))
    parts = path.parts
    for i, p in enumerate(parts):
        if p == "raw" and i + 1 < len(parts):
            return "/".join(parts[i:])
        if p == "text" and i + 1 < len(parts):
            return "/".join(parts[i:])
    return None


def run(dry_run: bool) -> None:
    if not settings.gcs_bucket:
        print("Set GCS_BUCKET in .env (and optionally GCS_PREFIX). Exiting.", file=sys.stderr)
        sys.exit(1)

    local = LocalStorage(settings.local_storage_dir)
    gcs = GcsStorage(bucket=settings.gcs_bucket, prefix=settings.gcs_prefix)

    db = SessionLocal()
    try:
        docs = db.query(Document).all()
        blobs_migrated = 0
        docs_updated = 0
        errors = 0
        for doc in docs:
            updates = {}
            # Raw blob
            if doc.gcs_raw_uri and doc.gcs_raw_uri.startswith("file://"):
                key = _file_uri_to_storage_key(doc.gcs_raw_uri)
                if not key:
                    print(f"  doc_id={doc.id}: could not derive key from raw uri", file=sys.stderr)
                    errors += 1
                    continue
                try:
                    data = local.download_bytes(uri=doc.gcs_raw_uri)
                    content_type = (doc.content_type or "application/pdf").strip() or "application/pdf"
                    if not dry_run:
                        obj = gcs.upload_bytes(key=key, data=data, content_type=content_type)
                        updates["gcs_raw_uri"] = obj.uri
                    else:
                        print(f"  doc_id={doc.id}: would upload raw key={key} ({len(data)} bytes)")
                    blobs_migrated += 1
                except Exception as e:
                    print(f"  doc_id={doc.id}: raw upload failed: {e}", file=sys.stderr)
                    errors += 1
            # Text blob
            if doc.gcs_text_uri and doc.gcs_text_uri.startswith("file://"):
                key = _file_uri_to_storage_key(doc.gcs_text_uri)
                if not key:
                    print(f"  doc_id={doc.id}: could not derive key from text uri", file=sys.stderr)
                    errors += 1
                    continue
                try:
                    data = local.download_bytes(uri=doc.gcs_text_uri)
                    if not dry_run:
                        obj = gcs.upload_bytes(
                            key=key,
                            data=data,
                            content_type="text/plain; charset=utf-8",
                        )
                        updates["gcs_text_uri"] = obj.uri
                    else:
                        print(f"  doc_id={doc.id}: would upload text key={key} ({len(data)} bytes)")
                    blobs_migrated += 1
                except Exception as e:
                    print(f"  doc_id={doc.id}: text upload failed: {e}", file=sys.stderr)
                    errors += 1
            if updates and not dry_run:
                for k, v in updates.items():
                    setattr(doc, k, v)
                db.commit()
                docs_updated += 1
        if dry_run:
            print(f"Dry run: would migrate {blobs_migrated} blobs across {len(docs)} documents, errors {errors}")
        else:
            print(f"Migrated {blobs_migrated} blobs, updated {docs_updated} documents, errors {errors}")
        if errors:
            sys.exit(1)
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate local storage blobs to GCS and update document URIs.")
    ap.add_argument("--dry-run", action="store_true", help="Only list what would be migrated; do not upload or update DB.")
    args = ap.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
