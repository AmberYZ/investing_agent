"""
Persist followed theme IDs (user's basket). Stored in a JSON file next to theme_read_state.
Single global store (no per-user in MVP).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_FOLLOWED_FILE = _PROMPT_DIR / "followed_themes.json"
_MAX_ENTRIES = 500


def _load_raw() -> dict[str, str]:
    """Return { theme_id: added_at_iso }."""
    if not _FOLLOWED_FILE.exists():
        return {}
    try:
        data = json.loads(_FOLLOWED_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and k.isdigit()}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_raw(data: dict[str, str]) -> None:
    _PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    _FOLLOWED_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_followed_theme_ids() -> list[int]:
    """Return ordered list of followed theme IDs (newest first by added_at)."""
    raw = _load_raw()
    items = [(int(k), v) for k, v in raw.items() if k.isdigit()]
    items.sort(key=lambda x: x[1], reverse=True)
    return [tid for tid, _ in items]


def follow_theme(theme_id: int) -> bool:
    """Add theme to followed. Returns True if added, False if already followed."""
    if theme_id <= 0:
        return False
    data = _load_raw()
    key = str(theme_id)
    if key in data:
        return False
    data[key] = datetime.now(timezone.utc).isoformat()
    if len(data) > _MAX_ENTRIES:
        items = sorted(data.items(), key=lambda x: x[1], reverse=True)[:_MAX_ENTRIES]
        data = dict(items)
    _save_raw(data)
    return True


def unfollow_theme(theme_id: int) -> bool:
    """Remove theme from followed. Returns True if removed, False if was not followed."""
    if theme_id <= 0:
        return False
    data = _load_raw()
    key = str(theme_id)
    if key not in data:
        return False
    del data[key]
    _save_raw(data)
    return True


def is_followed(theme_id: int) -> bool:
    """Return whether the theme is in the followed list."""
    return theme_id > 0 and str(theme_id) in _load_raw()
