"""
Megathemes (clusters of related themes) for timeline visualization.
Display-only clustering by embedding similarity; daily volume per cluster.
Short-lived themes are filtered out so the timeline shows sustained narratives.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Document, Evidence, Narrative, Theme, ThemeMentionsDaily
from app.worker import _cosine_similarity

logger = logging.getLogger("investing_agent.theme_clusters")

# Softer than merge threshold (0.92) so we get broader display clusters (e.g. Iran + oil + Hormuz).
CLUSTER_SIMILARITY_THRESHOLD = 0.78

# Short-lived: exclude if evidence in <= 2 distinct days AND total doc_count < 3.
SHORT_LIVED_MAX_DAYS = 2
SHORT_LIVED_MIN_DOCS = 3


def _doc_timestamp():
    return func.coalesce(Document.modified_at, Document.received_at)


def _get_theme_daily_counts_from_evidence(
    db: Session,
    start: dt.date,
    end: dt.date,
    theme_ids: list[int] | None = None,
) -> tuple[dict[int, dict[dt.date, int]], dict[int, int], dict[int, int]]:
    """
    Returns (theme_date_mentions, theme_doc_count, theme_distinct_days).
    theme_date_mentions: theme_id -> date -> mention_count
    theme_doc_count: theme_id -> total distinct docs in range
    theme_distinct_days: theme_id -> distinct days with evidence
    """
    doc_date = func.date(_doc_timestamp())
    q = (
        db.query(
            Narrative.theme_id,
            doc_date.label("date"),
            func.count(Evidence.id).label("mention_count"),
            func.count(func.distinct(Document.id)).label("doc_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(doc_date >= start, doc_date <= end)
    )
    if theme_ids is not None:
        q = q.filter(Narrative.theme_id.in_(theme_ids))
    rows = q.group_by(Narrative.theme_id, doc_date).all()

    theme_date_mentions: dict[int, dict[dt.date, int]] = {}
    theme_doc_count: dict[int, int] = {}
    theme_distinct_days: dict[int, int] = {}

    for r in rows:
        tid = r.theme_id
        try:
            d = r.date if isinstance(r.date, dt.date) else dt.datetime.strptime(str(r.date)[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        mention_count = int(r.mention_count or 0)
        doc_count_this_day = int(r.doc_count or 0)

        if tid not in theme_date_mentions:
            theme_date_mentions[tid] = {}
        theme_date_mentions[tid][d] = mention_count

        theme_doc_count[tid] = theme_doc_count.get(tid, 0) + doc_count_this_day
        theme_distinct_days[tid] = theme_distinct_days.get(tid, 0) + 1

    return theme_date_mentions, theme_doc_count, theme_distinct_days


def _get_theme_daily_counts_from_mentions_daily(
    db: Session,
    start: dt.date,
    end: dt.date,
    theme_ids: list[int] | None = None,
) -> dict[int, dict[dt.date, int]]:
    """When ThemeMentionsDaily is populated, use it for daily counts. Returns theme_id -> date -> mention_count."""
    q = (
        db.query(ThemeMentionsDaily.theme_id, ThemeMentionsDaily.date, ThemeMentionsDaily.mention_count)
        .filter(ThemeMentionsDaily.date >= start, ThemeMentionsDaily.date <= end)
    )
    if theme_ids is not None:
        q = q.filter(ThemeMentionsDaily.theme_id.in_(theme_ids))
    rows = q.all()

    theme_date_mentions: dict[int, dict[dt.date, int]] = {}
    for r in rows:
        tid = r.theme_id
        d = r.date
        if tid not in theme_date_mentions:
            theme_date_mentions[tid] = {}
        theme_date_mentions[tid][d] = int(r.mention_count or 0)
    return theme_date_mentions


def _filter_short_lived(
    theme_ids: list[int],
    theme_doc_count: dict[int, int],
    theme_distinct_days: dict[int, int],
) -> list[int]:
    """Exclude themes that have evidence in only 1-2 days and < SHORT_LIVED_MIN_DOCS docs."""
    return [
        tid
        for tid in theme_ids
        if not (
            theme_distinct_days.get(tid, 0) <= SHORT_LIVED_MAX_DAYS
            and theme_doc_count.get(tid, 0) < SHORT_LIVED_MIN_DOCS
        )
    ]


def _union_find_clusters(pairs: list[tuple[int, int]]) -> list[set[int]]:
    """Turn list of (a, b) pairs into list of disjoint sets (union-find)."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for a, b in pairs:
        union(a, b)

    groups: dict[int, set[int]] = {}
    for x in parent:
        root = find(x)
        if root not in groups:
            groups[root] = set()
        groups[root].add(x)
    return list(groups.values())


def _cluster_themes_by_embedding(
    themes: list[Theme],
    threshold: float = CLUSTER_SIMILARITY_THRESHOLD,
) -> list[set[int]]:
    """Group themes with embedding similarity >= threshold. Returns list of sets of theme ids."""
    with_emb = [t for t in themes if t.embedding and len(t.embedding or []) > 0]
    if not with_emb:
        # No embeddings: each theme is its own cluster
        return [{t.id} for t in themes]
    pairs: list[tuple[int, int]] = []
    for i in range(len(with_emb)):
        for j in range(i + 1, len(with_emb)):
            sim = _cosine_similarity(with_emb[i].embedding or [], with_emb[j].embedding or [])
            if sim >= threshold:
                pairs.append((with_emb[i].id, with_emb[j].id))
    if not pairs:
        return [{t.id} for t in themes]
    clusters = _union_find_clusters(pairs)
    # Include themes without embedding as singletons
    clustered_ids = {tid for s in clusters for tid in s}
    for t in themes:
        if t.id not in clustered_ids:
            clusters.append({t.id})
    return clusters


@dataclass
class MegathemeNode:
    id: str
    label: str
    theme_ids: list[int]
    mention_count_by_date: dict[str, int]  # "YYYY-MM-DD" -> count


def compute_megathemes(
    db: Session,
    start: dt.date,
    end: dt.date,
    cluster_threshold: float = CLUSTER_SIMILARITY_THRESHOLD,
    filter_short_lived: bool = True,
) -> list[MegathemeNode]:
    """
    Compute megathemes (clusters) for the date range with daily volume.
    - Gets theme-level daily counts (from Evidence or ThemeMentionsDaily).
    - Filters out short-lived themes if filter_short_lived.
    - Clusters by embedding similarity; assigns stable id and label per cluster.
    - Returns nodes with mention_count_by_date for every day in [start, end].
    """
    # 1) Theme-level daily counts and short-lived stats from Evidence
    theme_date_mentions_ev, theme_doc_count, theme_distinct_days = _get_theme_daily_counts_from_evidence(
        db, start, end, theme_ids=None
    )
    theme_ids_all = sorted(theme_date_mentions_ev.keys())
    if not theme_ids_all:
        # Try ThemeMentionsDaily
        theme_date_mentions_tmd = _get_theme_daily_counts_from_mentions_daily(db, start, end, theme_ids=None)
        theme_ids_all = sorted(theme_date_mentions_tmd.keys())
        theme_date_mentions_ev = {tid: {} for tid in theme_ids_all}
        for tid in theme_ids_all:
            for d, cnt in theme_date_mentions_tmd.get(tid, {}).items():
                theme_date_mentions_ev.setdefault(tid, {})[d] = theme_date_mentions_ev.get(tid, {}).get(d, 0) + cnt
        theme_doc_count = {tid: sum(theme_date_mentions_tmd.get(tid, {}).values()) for tid in theme_ids_all}
        theme_distinct_days = {tid: len(theme_date_mentions_tmd.get(tid, {})) for tid in theme_ids_all}
    if not theme_ids_all:
        return []

    # 2) Prefer ThemeMentionsDaily for daily counts when available (merge with evidence so we have all days)
    has_mentions_daily = db.query(ThemeMentionsDaily.theme_id).filter(
        ThemeMentionsDaily.theme_id.in_(theme_ids_all),
        ThemeMentionsDaily.date >= start,
        ThemeMentionsDaily.date <= end,
    ).limit(1).first() is not None
    if has_mentions_daily:
        tmd = _get_theme_daily_counts_from_mentions_daily(db, start, end, theme_ids_all)
        for tid, by_date in tmd.items():
            if tid not in theme_date_mentions_ev:
                theme_date_mentions_ev[tid] = {}
            for d, cnt in by_date.items():
                theme_date_mentions_ev[tid][d] = theme_date_mentions_ev[tid].get(d, 0) + cnt

    # 3) Filter short-lived
    if filter_short_lived:
        theme_ids_all = _filter_short_lived(theme_ids_all, theme_doc_count, theme_distinct_days)
    if not theme_ids_all:
        return []

    # 4) Load themes with embeddings
    themes = db.query(Theme).filter(Theme.id.in_(theme_ids_all)).all()
    themes_by_id = {t.id: t for t in themes}

    # 5) Cluster by embedding
    clusters = _cluster_themes_by_embedding(themes, threshold=cluster_threshold)

    # 6) Build list of all dates in range
    all_dates: list[dt.date] = []
    d = start
    while d <= end:
        all_dates.append(d)
        d += dt.timedelta(days=1)

    # 7) Build MegathemeNode per cluster
    nodes: list[MegathemeNode] = []
    for cluster_ids in clusters:
        cluster_ids = sorted(cluster_ids)
        if not cluster_ids:
            continue
        # Stable id: hash of sorted ids so same cluster gets same id across calls
        stable_key = hashlib.sha256(",".join(str(x) for x in cluster_ids).encode()).hexdigest()[:12]
        node_id = f"mg_{stable_key}"
        # Label: theme with highest total mentions in range
        total_by_theme = {
            tid: sum(theme_date_mentions_ev.get(tid, {}).values())
            for tid in cluster_ids
        }
        best_theme_id = max(cluster_ids, key=lambda tid: total_by_theme.get(tid, 0))
        t = themes_by_id.get(best_theme_id)
        label = t.canonical_label if t else "Unknown"

        # Daily counts: sum over themes in cluster
        mention_count_by_date: dict[str, int] = {}
        for date in all_dates:
            date_str = date.isoformat()
            total = 0
            for tid in cluster_ids:
                total += theme_date_mentions_ev.get(tid, {}).get(date, 0)
            mention_count_by_date[date_str] = total

        nodes.append(
            MegathemeNode(
                id=node_id,
                label=label,
                theme_ids=cluster_ids,
                mention_count_by_date=mention_count_by_date,
            )
        )

    return nodes
