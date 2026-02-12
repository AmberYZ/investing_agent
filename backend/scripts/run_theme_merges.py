#!/usr/bin/env python3
"""
Run the theme merge algorithm on existing themes.

Step 1: Discover merge candidates (substring, token Dice, embedding similarity, optional LLM).
Step 2: For each group, merge every non-canonical theme into the canonical one.

Run from the backend directory (with .env loaded for DB and optional Vertex/LLM):

    .venv/bin/python scripts/run_theme_merges.py              # apply all suggested merges
    .venv/bin/python scripts/run_theme_merges.py --dry-run     # only print what would be merged

Or call the API manually:
    GET  /admin/themes/suggest-merges   → see suggested groups (theme_ids, labels, canonical_theme_id)
    POST /admin/themes/merge             → body: {"source_theme_id": N, "target_theme_id": M}
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

# Load .env from repo root so DATABASE_URL and optional Vertex/LLM work
try:
    import dotenv
    repo_root = _backend.parent
    dotenv.load_dotenv(repo_root / ".env")
except Exception:
    pass

from app.db import SessionLocal, init_db
from app.theme_merge import compute_merge_candidates, execute_theme_merge


def main(dry_run: bool) -> None:
    init_db()
    db = SessionLocal()
    try:
        merge_sets = compute_merge_candidates(db)
        if not merge_sets:
            print("No merge candidates found.")
            return
        print(f"Found {len(merge_sets)} merge group(s).")
        total_merges = 0
        for ms in merge_sets:
            target = ms.canonical_theme_id
            sources = [tid for tid in ms.theme_ids if tid != target]
            labels_str = " | ".join(ms.labels) if ms.labels else str(ms.theme_ids)
            print(f"  Group: {labels_str}")
            print(f"    Keep theme_id={target}, merge into it: {sources}")
            if dry_run:
                total_merges += len(sources)
                continue
            for source_id in sources:
                n = execute_theme_merge(db, source_id, target)
                print(f"    Merged {source_id} -> {target} (narratives_moved={n})")
                total_merges += 1
        if dry_run:
            print(f"Dry run: would perform {total_merges} merge(s). Run without --dry-run to apply.")
        else:
            db.commit()
            print(f"Done. Performed {total_merges} merge(s).")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run theme merge algorithm on existing themes.")
    parser.add_argument("--dry-run", action="store_true", help="Only print suggested merges, do not apply")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
