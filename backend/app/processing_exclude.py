"""
Exclude ingested documents from the processing pipeline (PDF/text extraction, embeddings, LLM).

Raw bytes remain in storage and the Document row stays; only ingest jobs are marked skipped.
Configuration: processing_exclude.json next to watch_dirs.json (see app.watch_dirs_config state_dir).
"""
from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models import Document
from app.settings import settings

logger = logging.getLogger("investing_agent.processing_exclude")


def _state_dir() -> Path:
    if getattr(settings, "state_dir", None) and settings.state_dir.strip():
        return Path(settings.state_dir.strip()).resolve()
    return Path(__file__).resolve().parent / "prompts"


def processing_exclude_path() -> Path:
    return _state_dir() / "processing_exclude.json"


@dataclass(frozen=True)
class _ExcludeRules:
    sha256: frozenset[str]
    filename_globs: tuple[str, ...]
    filename_contains: tuple[str, ...]
    source_uri_contains: tuple[str, ...]


_rules_cache: _ExcludeRules | None = None
_rules_cache_mtime: float | None = None


def _as_str_list(val: Any, key: str) -> list[str]:
    if val is None:
        return []
    if not isinstance(val, list):
        logger.warning("processing_exclude.json: %r must be a list, ignoring", key)
        return []
    out: list[str] = []
    for item in val:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _load_rules_uncached() -> _ExcludeRules:
    path = processing_exclude_path()
    if not path.exists():
        return _ExcludeRules(
            sha256=frozenset(),
            filename_globs=(),
            filename_contains=(),
            source_uri_contains=(),
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not read %s: %s", path, e)
        return _ExcludeRules(frozenset(), (), (), ())

    if not isinstance(data, dict):
        logger.warning("processing_exclude.json root must be an object, ignoring")
        return _ExcludeRules(frozenset(), (), (), ())

    sha_raw = _as_str_list(data.get("sha256"), "sha256")
    sha256 = frozenset(s.lower() for s in sha_raw if len(s) == 64)
    globs = tuple(_as_str_list(data.get("filename_globs"), "filename_globs"))
    fn_contains = tuple(s.lower() for s in _as_str_list(data.get("filename_contains"), "filename_contains"))
    uri_contains = tuple(s.lower() for s in _as_str_list(data.get("source_uri_contains"), "source_uri_contains"))

    return _ExcludeRules(
        sha256=sha256,
        filename_globs=globs,
        filename_contains=fn_contains,
        source_uri_contains=uri_contains,
    )


def get_processing_exclude_rules() -> _ExcludeRules:
    """Return rules, reloading the JSON file when it changes on disk."""
    global _rules_cache, _rules_cache_mtime
    path = processing_exclude_path()
    try:
        mtime = path.stat().st_mtime if path.exists() else -1.0
    except OSError:
        mtime = -2.0
    if _rules_cache is not None and _rules_cache_mtime == mtime:
        return _rules_cache
    rules = _load_rules_uncached()
    _rules_cache = rules
    _rules_cache_mtime = mtime
    return rules


def processing_exclude_match_reason(doc: Document) -> str | None:
    """
    If this document should skip processing, return a short human-readable reason; else None.
    """
    rules = get_processing_exclude_rules()
    if not (
        rules.sha256
        or rules.filename_globs
        or rules.filename_contains
        or rules.source_uri_contains
    ):
        return None

    digest = (doc.sha256 or "").strip().lower()
    if digest and digest in rules.sha256:
        return "Skipped: sha256 listed in processing_exclude.json"

    basename = Path(doc.filename or "").name
    base_lower = basename.lower()

    for needle in rules.filename_contains:
        if needle and needle in base_lower:
            return f"Skipped: filename contains {needle!r} (processing_exclude.json)"

    for pattern in rules.filename_globs:
        if not pattern:
            continue
        if fnmatch.fnmatch(base_lower, pattern.lower()) or fnmatch.fnmatch(basename, pattern):
            return f"Skipped: filename matches glob {pattern!r} (processing_exclude.json)"

    uri = (doc.source_uri or "").lower()
    if uri:
        for needle in rules.source_uri_contains:
            if needle and needle in uri:
                return f"Skipped: source_uri contains {needle!r} (processing_exclude.json)"

    return None
