"""
Persist theme read state (theme_id -> last read timestamp) so it survives backend restarts.
Stored in a JSON file next to watch_dirs. Single global store (no per-user in MVP).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_READ_STATE_FILE = _PROMPT_DIR / "theme_read_state.json"
_MAX_ENTRIES = 500


def _load_raw() -> dict[str, str]:
    if not _READ_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(_READ_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_raw(data: dict[str, str]) -> None:
    _PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    _READ_STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_theme_read_state() -> dict[int, str]:
    """Return theme_id -> ISO timestamp when last marked read."""
    raw = _load_raw()
    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            tid = int(k)
            if tid > 0 and v:
                out[tid] = v
        except ValueError:
            continue
    return out


def mark_themes_read(theme_ids: list[int]) -> dict[int, str]:
    """Set last-read timestamp to now for the given theme ids. Returns current full state."""
    now = datetime.now(timezone.utc).isoformat()
    data = _load_raw()
    for tid in theme_ids:
        if tid > 0:
            data[str(tid)] = now
    if len(data) > _MAX_ENTRIES:
        items = sorted(data.items(), key=lambda x: x[1], reverse=True)[:_MAX_ENTRIES]
        data = dict(items)
    _save_raw(data)
    return get_theme_read_state()
