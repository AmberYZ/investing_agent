"""Helpers for resolving local filesystem paths used as document raw sources."""

from __future__ import annotations

from pathlib import Path


def existing_local_file(uri_or_path: str | None) -> Path | None:
    """Return Path if uri_or_path points at an existing local file; else None.

    Accepts absolute/relative paths or file:// URIs. Skips http(s)/gs://.
    """
    if not uri_or_path or not isinstance(uri_or_path, str):
        return None
    s = uri_or_path.strip()
    if not s:
        return None
    lower = s.lower()
    if lower.startswith(("http://", "https://", "gs://")):
        return None
    if lower.startswith("file://"):
        s = s[len("file://") :]
    path = Path(s).expanduser()
    try:
        if path.is_file():
            return path.resolve()
    except OSError:
        return None
    return None


def file_uri(path: Path) -> str:
    return f"file://{path.resolve()}"
