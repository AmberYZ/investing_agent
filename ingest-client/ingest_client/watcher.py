from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import requests
from dotenv import load_dotenv


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_watch_dirs(api_base: str) -> List[Path] | None:
    """Fetch watch directories from API. Returns None on failure or empty."""
    url = f"{api_base}/settings/watch-dirs"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"[ingest] Watch-dirs API returned {r.status_code} from {url}")
            if r.status_code == 404:
                print(f"[ingest]   → Backend may be running old code. Restart the backend (e.g. restart ./dev.sh) so it loads the watch-dirs route.")
            elif r.status_code == 503:
                print(f"[ingest]   → 503 Service Unavailable. Check .env: PAUSE_INGEST=false and MAX_QUEUED_INGEST_JOBS (or cancel stuck jobs in Admin). If you did not set these, something else on port 8000 may be returning 503.")
            return None
        data = r.json()
        raw = data.get("watch_dirs")
        if not isinstance(raw, list) or len(raw) == 0:
            print("[ingest] Watch-dirs API returned empty list")
            return None
        dirs = []
        for item in raw:
            if isinstance(item, dict) and item.get("path"):
                path_str = str(item["path"]).strip()
                nickname = (item.get("nickname") or "").strip()
            elif isinstance(item, str) and item.strip():
                path_str = item.strip()
                nickname = ""
            else:
                continue
            p = Path(path_str).expanduser()
            if not p.exists():
                label = f" ({nickname})" if nickname else ""
                print(f"[ingest] Skipping watch path{label}: path does not exist: {p!r}")
                print(f"[ingest]   Tip: Run the ingest client from Terminal (e.g. ./dev.sh); container paths may not be visible to all processes.")
                continue
            if not p.is_dir():
                label = f" ({nickname})" if nickname else ""
                print(f"[ingest] Skipping watch path{label}: not a directory: {p!r}")
                continue
            dirs.append(p)
        if not dirs:
            print("[ingest] No watch paths from API exist on this machine; nothing to watch")
            return None
        return dirs
    except requests.RequestException as e:
        print(f"[ingest] Could not fetch watch-dirs from {url}: {e}")
        print(f"[ingest]   → Is the backend running? Start it with ./dev.sh or: cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"[ingest] Watch-dirs API error: {e}")
        return None


def _read_watch_dirs_from_file(repo_root: Path) -> List[Path] | None:
    """Read watch_dirs from backend/app/prompts/watch_dirs.json (same file the backend uses). Use when API is unavailable."""
    file_path = repo_root / "backend" / "app" / "prompts" / "watch_dirs.json"
    if not file_path.exists():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        raw = data.get("watch_dirs")
        if not isinstance(raw, list) or len(raw) == 0:
            return None
        dirs = []
        for item in raw:
            if isinstance(item, dict) and item.get("path"):
                path_str = str(item["path"]).strip()
                nickname = (item.get("nickname") or "").strip()
            elif isinstance(item, str) and item.strip():
                path_str = item.strip()
                nickname = ""
            else:
                continue
            p = Path(path_str).expanduser()
            if not p.exists():
                label = f" ({nickname})" if nickname else ""
                print(f"[ingest] Skipping watch path{label}: path does not exist: {p!r}")
                continue
            if not p.is_dir():
                label = f" ({nickname})" if nickname else ""
                print(f"[ingest] Skipping watch path{label}: not a directory: {p!r}")
                continue
            dirs.append(p)
        return dirs if dirs else None
    except (json.JSONDecodeError, OSError):
        return None


def _resolve_watch_dirs(repo_root: Path, api_base: str) -> List[Path]:
    """Get list of directories to watch: API first, then watch_dirs.json file, then env WATCH_DIR, then default."""
    dirs = _fetch_watch_dirs(api_base)
    if dirs:
        print(f"[ingest] Using {len(dirs)} watch directory/ies from Admin API:")
        for d in dirs:
            print(f"[ingest]   - {d}")
        return dirs
    # API unavailable (404, down, or empty): try same config file the backend uses (Admin UI writes it via backend)
    dirs = _read_watch_dirs_from_file(repo_root)
    if dirs:
        print(f"[ingest] Using {len(dirs)} watch directory/ies from config file (API unavailable):")
        for d in dirs:
            print(f"[ingest]   - {d}")
        return dirs
    raw = os.environ.get("WATCH_DIR", "").strip()
    watch_dir = Path(raw).expanduser() if raw else None
    if watch_dir and watch_dir.exists() and watch_dir.is_dir():
        print(f"[ingest] Watch-dirs API unavailable and no config file; using WATCH_DIR from .env: {watch_dir}")
        return [watch_dir]
    default = repo_root / "watch_pdfs"
    default.mkdir(parents=True, exist_ok=True)
    if not raw:
        print(f"[ingest] Watch-dirs API unavailable and WATCH_DIR not set; using default: {default}")
    else:
        print(f"[ingest] Watch-dirs API unavailable and WATCH_DIR path does not exist: {raw!r}; using {default}")
    print(f"[ingest] Drop PDF files here and they will be ingested automatically.")
    return [default]


def main() -> None:
    # Load repo root .env (same place backend/worker use), regardless of CWD
    repo_root = Path(__file__).resolve().parent.parent.parent
    load_dotenv(repo_root / ".env")

    api_base = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    poll_seconds = int(os.environ.get("POLL_SECONDS", "5"))

    print(f"[ingest] Backend API: {api_base} (from API_BASE_URL in .env)")
    watch_dirs = _resolve_watch_dirs(repo_root, api_base)

    # Dedupe by file content (sha256) within this watcher process.
    # The backend also dedupes by sha256, so this is an extra local guardrail.
    seen_digests: set[str] = set()

    while True:
        # Refetch watch dirs every cycle so config changes (saved from Admin UI) apply within one poll
        fresh = _fetch_watch_dirs(api_base)
        if fresh is not None:
            watch_dirs = fresh

        pdfs_list: List[Path] = []
        for watch_dir in watch_dirs:
            try:
                # rglob so we find PDFs in subdirectories too (e.g. .../WeChat/baiguanFeed_wechat/file.pdf)
                pdfs_list.extend(watch_dir.rglob("*.pdf"))
            except OSError:
                pass

        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0

        pdfs = sorted(set(pdfs_list), key=_mtime)

        for p in pdfs:
            try:
                digest = _file_sha256(p)
                if digest in seen_digests:
                    continue

                # Use file's modification time (or creation time on macOS) as document date for themes/charts
                try:
                    stat = p.stat()
                    # Prefer birth time (creation) on systems that have it, else mtime (modification)
                    file_ts = getattr(stat, "st_birthtime", None) or stat.st_mtime
                    modified_at = datetime.fromtimestamp(file_ts, tz=timezone.utc).isoformat()
                except OSError:
                    modified_at = None
                with p.open("rb") as f:
                    files = {"file": (p.name, f, "application/pdf")}
                    data = {
                        "source_type": "pdf",
                        "source_name": "wechat",
                        "source_uri": str(p),
                    }
                    if modified_at:
                        data["modified_at"] = modified_at
                    r = requests.post(f"{api_base}/ingest-file", files=files, data=data, timeout=120)
                r.raise_for_status()
                seen_digests.add(digest)
                print(f"Ingested {p.name} (sha256={digest[:12]}): {r.json()}")
            except Exception as e:  # noqa: BLE001
                print(f"Failed {p}: {e}")

        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()

