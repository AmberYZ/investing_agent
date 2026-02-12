"""
Persist and load watch directories for the ingest client (PDF watcher).
Stored in prompts/watch_dirs.json; falls back to env WATCH_DIR if file missing.
Each entry has path and optional nickname. Tracks config_updated_at for UI.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_WATCH_DIRS_FILE = _PROMPT_DIR / "watch_dirs.json"


def _normalize_entry(entry: Any) -> tuple[str, str] | None:
    """Return (path, nickname) or None if invalid."""
    if isinstance(entry, str) and entry.strip():
        return (str(Path(entry.strip()).expanduser().resolve()), "")
    if isinstance(entry, dict) and entry.get("path"):
        path = str(entry["path"]).strip()
        if not path:
            return None
        nickname = str(entry.get("nickname") or "").strip()
        return (str(Path(path).expanduser().resolve()), nickname)
    return None


def get_watch_dirs() -> list[dict[str, str]]:
    """Return list of {path, nickname}. From file if present, else env WATCH_DIR."""
    if _WATCH_DIRS_FILE.exists():
        try:
            data = json.loads(_WATCH_DIRS_FILE.read_text(encoding="utf-8"))
            dirs = data.get("watch_dirs")
            if isinstance(dirs, list):
                out = []
                for e in dirs:
                    norm = _normalize_entry(e)
                    if norm:
                        out.append({"path": norm[0], "nickname": norm[1]})
                return out
            return []
        except (json.JSONDecodeError, OSError):
            pass
    raw = os.environ.get("WATCH_DIR", "").strip()
    if raw:
        return [{"path": str(Path(raw).expanduser().resolve()), "nickname": ""}]
    return []


def get_config_updated_at() -> str | None:
    """Return ISO timestamp when watch_dirs config was last saved, or None."""
    if not _WATCH_DIRS_FILE.exists():
        return None
    try:
        data = json.loads(_WATCH_DIRS_FILE.read_text(encoding="utf-8"))
        ts = data.get("config_updated_at")
        return str(ts) if ts else None
    except (json.JSONDecodeError, OSError):
        return None


def get_watch_dir_paths() -> list[str]:
    """Return only paths (for ingest client)."""
    return [e["path"] for e in get_watch_dirs()]


def set_watch_dirs(watch_dirs: list[dict[str, str]]) -> None:
    """Overwrite stored watch directories. Each item: {path, nickname?}. Sets config_updated_at."""
    _PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    normalized = []
    for e in watch_dirs:
        norm = _normalize_entry(e)
        if norm:
            normalized.append({"path": norm[0], "nickname": norm[1]})
    now = datetime.now(timezone.utc).isoformat()
    _WATCH_DIRS_FILE.write_text(
        json.dumps({"watch_dirs": normalized, "config_updated_at": now}, indent=2),
        encoding="utf-8",
    )
