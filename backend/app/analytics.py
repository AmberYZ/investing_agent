"""
Investor analytics: trending, sentiment rankings, inflections, debated, archived.
Simple heuristics (two-window comparisons, counts/ratios) for sparse theme-level data.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.insights import compute_debate
from app.models import Document, Evidence, Narrative, Theme, ThemeMentionsDaily


def _doc_timestamp():
    return func.coalesce(Document.modified_at, Document.received_at)


def _theme_out(t: Theme, last_updated: Optional[dt.datetime], is_new: bool = False):
    from app.schemas import ThemeOut
    return ThemeOut(
        id=t.id,
        canonical_label=t.canonical_label,
        description=t.description,
        last_updated=last_updated,
        is_new=is_new,
    )


def _themes_with_last_updated(db: Session, theme_ids: Optional[list[int]] = None):
    """Return (Theme, last_updated) for all themes or given ids."""
    q = (
        db.query(Theme, func.max(Narrative.last_seen).label("last_updated"))
        .outerjoin(Narrative, Narrative.theme_id == Theme.id)
        .group_by(Theme.id)
    )
    if theme_ids is not None:
        q = q.filter(Theme.id.in_(theme_ids))
    return q.all()


def _sov_from_evidence(
    db: Session,
    start: dt.date,
    end: dt.date,
) -> dict[int, float]:
    """Compute sum of daily share-of-voice per theme from Evidence (doc_count/total_docs per day). Use when ThemeMentionsDaily is empty."""
    doc_date = func.date(_doc_timestamp())
    theme_doc_rows = (
        db.query(
            Narrative.theme_id,
            doc_date.label("date"),
            func.count(func.distinct(Document.id)).label("doc_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(doc_date >= start, doc_date < end)
        .group_by(Narrative.theme_id, doc_date)
        .all()
    )
    if not theme_doc_rows:
        return {}
    total_rows = (
        db.query(doc_date.label("date"), func.count(Document.id).label("total"))
        .select_from(Document)
        .filter(doc_date >= start, doc_date < end)
        .group_by(doc_date)
        .all()
    )
    def _date_key(val):
        if val is None:
            return None
        if hasattr(val, "isoformat"):
            return val.isoformat()[:10]
        return str(val)[:10]
    total_by_date = {}
    for row in total_rows:
        k = _date_key(getattr(row.date, "date", None) or row.date)
        if k:
            total_by_date[k] = int(row.total or 0)
    by_theme: dict[int, float] = {}
    for r in theme_doc_rows:
        tid = r.theme_id
        k = _date_key(getattr(r.date, "date", None) or r.date)
        total = total_by_date.get(k, 0) if k else 0
        sov = float(r.doc_count or 0) / total if total > 0 else 0.0
        by_theme[tid] = by_theme.get(tid, 0.0) + sov
    return by_theme


def get_trending_themes(
    db: Session,
    recent_days: int = 7,
    prior_days: int = 30,
    limit: int = 100,
) -> list:
    """Themes where share of voice (SoV) in recent window > prior window. Uses % SoV so adding data sources does not distort relative attention."""
    today = dt.date.today()
    recent_start = today - dt.timedelta(days=recent_days)
    prior_start = today - dt.timedelta(days=recent_days + prior_days)
    # Sum share_of_voice per theme in each window (daily SoV = theme's share that day)
    recent_rows = (
        db.query(
            ThemeMentionsDaily.theme_id,
            func.coalesce(func.sum(ThemeMentionsDaily.share_of_voice), 0).label("total"),
        )
        .filter(
            ThemeMentionsDaily.date >= recent_start,
            ThemeMentionsDaily.date < today,
        )
        .group_by(ThemeMentionsDaily.theme_id)
        .all()
    )
    prior_rows = (
        db.query(
            ThemeMentionsDaily.theme_id,
            func.coalesce(func.sum(ThemeMentionsDaily.share_of_voice), 0).label("total"),
        )
        .filter(
            ThemeMentionsDaily.date >= prior_start,
            ThemeMentionsDaily.date < recent_start,
        )
        .group_by(ThemeMentionsDaily.theme_id)
        .all()
    )
    recent_by_id = {r.theme_id: float(r.total or 0) for r in recent_rows}
    prior_by_id = {r.theme_id: float(r.total or 0) for r in prior_rows}
    # Fallback: if ThemeMentionsDaily is empty (e.g. daily aggregations not run), compute SoV from Evidence
    if not recent_by_id and not prior_by_id:
        recent_by_id = _sov_from_evidence(db, recent_start, today)
        prior_by_id = _sov_from_evidence(db, prior_start, recent_start)
    theme_ids = sorted(
        set(recent_by_id.keys()) | set(prior_by_id.keys()),
        key=lambda tid: (recent_by_id.get(tid, 0.0) - prior_by_id.get(tid, 0.0)),
        reverse=True,
    )[:limit]
    if not theme_ids:
        return []
    cutoff_new = today - dt.timedelta(days=7)
    rows = _themes_with_last_updated(db, theme_ids)
    id_to_row = {t.id: (t, last_updated) for t, last_updated in rows}
    out = []
    for tid in theme_ids:
        if tid not in id_to_row:
            continue
        t, last_updated = id_to_row[tid]
        is_new = t.created_at and t.created_at.date() >= cutoff_new
        out.append(_theme_out(t, last_updated, is_new))
    return out


def get_sentiment_rankings(
    db: Session,
    days: int = 30,
    limit: int = 30,
) -> dict:
    """Most positive and most negative themes by SoV-weighted sentiment (relative: no absolute counts). Score = sum_d(SoV_d * sentiment_d) / sum_d(SoV_d)."""
    since = dt.date.today() - dt.timedelta(days=days)
    doc_date = func.date(_doc_timestamp())
    # Per (theme_id, date): stance counts
    stance_rows = (
        db.query(
            Narrative.theme_id,
            doc_date.label("date"),
            Narrative.narrative_stance,
            func.count(Evidence.id).label("cnt"),
        )
        .select_from(Evidence)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(doc_date >= since)
        .group_by(Narrative.theme_id, doc_date, Narrative.narrative_stance)
        .all()
    )
    theme_doc_rows = (
        db.query(
            Narrative.theme_id,
            doc_date.label("date"),
            func.count(func.distinct(Document.id)).label("doc_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(doc_date >= since)
        .group_by(Narrative.theme_id, doc_date)
        .all()
    )
    total_doc_rows = (
        db.query(doc_date.label("date"), func.count(Document.id).label("total"))
        .select_from(Document)
        .filter(doc_date >= since)
        .group_by(doc_date)
        .all()
    )

    def _dk(v):
        if v is None:
            return None
        return (getattr(v, "isoformat", None) and v.isoformat() or str(v))[:10]

    total_by_date = {}
    for row in total_doc_rows:
        k = _dk(getattr(row.date, "date", None) or row.date)
        if k:
            total_by_date[k] = int(row.total or 0)
    theme_docs: dict[tuple[int, str], int] = {}
    for r in theme_doc_rows:
        k = _dk(getattr(r.date, "date", None) or r.date)
        if k:
            theme_docs[(r.theme_id, k)] = int(r.doc_count or 0)
    by_theme_date: dict[int, dict[str, dict[str, int]]] = {}
    for r in stance_rows:
        tid = r.theme_id
        k = _dk(getattr(r.date, "date", None) or r.date)
        if not k:
            continue
        st = (r.narrative_stance or "neutral").lower()
        if st not in ("bullish", "bearish", "mixed", "neutral"):
            st = "neutral"
        if tid not in by_theme_date:
            by_theme_date[tid] = {}
        if k not in by_theme_date[tid]:
            by_theme_date[tid][k] = {"bullish": 0, "bearish": 0, "mixed": 0, "neutral": 0}
        by_theme_date[tid][k][st] = by_theme_date[tid][k].get(st, 0) + int(r.cnt or 0)

    scores = []
    for tid, dates in by_theme_date.items():
        weighted_sum = 0.0
        sov_sum = 0.0
        for k, counts in dates.items():
            total_mentions = sum(counts.values())
            sentiment_d = (counts.get("bullish", 0) - counts.get("bearish", 0)) / total_mentions if total_mentions else 0.0
            theme_docs_d = theme_docs.get((tid, k), 0)
            total_d = total_by_date.get(k, 0)
            sov_d = theme_docs_d / total_d if total_d > 0 else 0.0
            weighted_sum += sov_d * sentiment_d
            sov_sum += sov_d
        if sov_sum > 0:
            scores.append((tid, weighted_sum / sov_sum))
    scores.sort(key=lambda x: -x[1])
    most_positive_ids = [tid for tid, _ in scores[:limit]]
    most_negative_ids = [tid for tid, _ in reversed(scores[-limit:])]
    cutoff_new = dt.date.today() - dt.timedelta(days=7)
    def build_list(ids):
        if not ids:
            return []
        rows = _themes_with_last_updated(db, ids)
        id_to_row = {t.id: (t, last_updated) for t, last_updated in rows}
        return [
            _theme_out(
                id_to_row[tid][0],
                id_to_row[tid][1],
                id_to_row[tid][0].created_at and id_to_row[tid][0].created_at.date() >= cutoff_new,
            )
            for tid in ids
            if tid in id_to_row
        ]
    return {
        "most_positive": build_list(most_positive_ids),
        "most_negative": build_list(most_negative_ids),
    }


def get_inflections(
    db: Session,
    recent_days: int = 14,
    prior_days: int = 30,
    limit: int = 30,
) -> dict:
    """Four lists: bullish->neutral/bearish, bearish->neutral/bullish, attention_peaking, most_crowded."""
    today = dt.date.today()
    recent_start = today - dt.timedelta(days=recent_days)
    prior_start = today - dt.timedelta(days=recent_days + prior_days)
    doc_date = func.date(_doc_timestamp())

    # Stance aggregates per theme per window
    def stance_aggregates(start: dt.date, end: dt.date):
        rows = (
            db.query(
                Narrative.theme_id,
                Narrative.narrative_stance,
                func.count(Evidence.id).label("mention_count"),
            )
            .select_from(Evidence)
            .join(Narrative, Narrative.id == Evidence.narrative_id)
            .join(Document, Document.id == Evidence.document_id)
            .filter(doc_date >= start, doc_date < end)
            .group_by(Narrative.theme_id, Narrative.narrative_stance)
            .all()
            )
        by_theme: dict[int, dict[str, int]] = {}
        for r in rows:
            tid = r.theme_id
            st = (r.narrative_stance or "neutral").lower()
            if st not in ("bullish", "bearish", "mixed", "neutral"):
                st = "neutral"
            if tid not in by_theme:
                by_theme[tid] = {"bullish": 0, "bearish": 0, "mixed": 0, "neutral": 0}
            by_theme[tid][st] = by_theme[tid].get(st, 0) + int(r.mention_count or 0)
        return by_theme

    recent_stance = stance_aggregates(recent_start, today)
    prior_stance = stance_aggregates(prior_start, recent_start)

    # SoV sums per theme per window (share_of_voice so adding data sources does not distort relative attention)
    recent_sov = (
        db.query(
            ThemeMentionsDaily.theme_id,
            func.coalesce(func.sum(ThemeMentionsDaily.share_of_voice), 0).label("total"),
        )
        .filter(ThemeMentionsDaily.date >= recent_start, ThemeMentionsDaily.date < today)
        .group_by(ThemeMentionsDaily.theme_id)
        .all()
    )
    prior_sov = (
        db.query(
            ThemeMentionsDaily.theme_id,
            func.coalesce(func.sum(ThemeMentionsDaily.share_of_voice), 0).label("total"),
        )
        .filter(ThemeMentionsDaily.date >= prior_start, ThemeMentionsDaily.date < recent_start)
        .group_by(ThemeMentionsDaily.theme_id)
        .all()
    )
    recent_sov_by_id = {r.theme_id: float(r.total or 0) for r in recent_sov}
    prior_sov_by_id = {r.theme_id: float(r.total or 0) for r in prior_sov}
    # Fallback: when ThemeMentionsDaily is empty, compute SoV from Evidence (relative: doc share per day)
    if not recent_sov_by_id and not prior_sov_by_id:
        recent_sov_by_id = _sov_from_evidence(db, recent_start, today)
        prior_sov_by_id = _sov_from_evidence(db, prior_start, recent_start)

    def dominant_stance(counts: dict) -> str:
        if not counts:
            return "neutral"
        total = sum(counts.values())
        if total == 0:
            return "neutral"
        bull = counts.get("bullish", 0)
        bear = counts.get("bearish", 0)
        if bull >= total * 0.5:
            return "bullish"
        if bear >= total * 0.5:
            return "bearish"
        return "mixed"

    def recent_bull_share(counts: dict) -> float:
        total = sum(counts.values())
        if total == 0:
            return 0.0
        return counts.get("bullish", 0) / total

    bullish_turning = []   # prior dominant bullish, recent not bullish
    bearish_turning = []  # prior dominant bearish, recent not bearish
    attention_peaking = []  # SoV recent < prior (attention declining)
    most_crowded = []      # high SoV recent + very bullish (e.g. >50% bullish)

    all_theme_ids = set(recent_stance.keys()) | set(prior_stance.keys()) | set(recent_sov_by_id.keys()) | set(prior_sov_by_id.keys())
    cutoff_new = today - dt.timedelta(days=7)

    for tid in all_theme_ids:
        pr_st = prior_stance.get(tid, {})
        re_st = recent_stance.get(tid, {})
        prior_dom = dominant_stance(pr_st)
        recent_dom = dominant_stance(re_st)
        re_sov = recent_sov_by_id.get(tid, 0)
        pr_sov = prior_sov_by_id.get(tid, 0)
        re_bull = recent_bull_share(re_st)

        if prior_dom == "bullish" and recent_dom != "bullish":
            bullish_turning.append((tid, re_sov))
        if prior_dom == "bearish" and recent_dom != "bearish":
            bearish_turning.append((tid, re_sov))
        if pr_sov > 0 and re_sov < pr_sov:
            attention_peaking.append((tid, re_sov))
        if re_sov > 0 and re_bull >= 0.5:
            most_crowded.append((tid, re_bull, re_sov))

    bullish_turning.sort(key=lambda x: -x[1])
    bearish_turning.sort(key=lambda x: -x[1])
    attention_peaking.sort(key=lambda x: -x[1])
    most_crowded.sort(key=lambda x: (-x[2], -x[1]))

    def to_theme_list(pairs, key_fn=lambda x: x[0], take=limit):
        ids = [key_fn(p) for p in pairs[:take]]
        if not ids:
            return []
        rows = _themes_with_last_updated(db, ids)
        id_to_row = {t.id: (t, last_updated) for t, last_updated in rows}
        return [
            _theme_out(
                id_to_row[tid][0],
                id_to_row[tid][1],
                id_to_row[tid][0].created_at and id_to_row[tid][0].created_at.date() >= cutoff_new,
            )
            for tid in ids
            if tid in id_to_row
        ]

    return {
        "bullish_turning_neutral_bearish": to_theme_list(bullish_turning),
        "bearish_turning_neutral_bullish": to_theme_list(bearish_turning),
        "attention_peaking": to_theme_list(attention_peaking),
        "most_crowded": to_theme_list([(tid, b, s) for tid, b, s in most_crowded], key_fn=lambda x: x[0]),
    }


def get_debated_themes(
    db: Session,
    days: int = 30,
    limit: int = 30,
    min_score: float = 0.3,
) -> list:
    """Themes with debate score (1 - top_share) above threshold."""
    since = dt.date.today() - dt.timedelta(days=days)
    theme_ids = [
        r.theme_id
        for r in db.query(Narrative.theme_id)
        .join(Evidence, Evidence.narrative_id == Narrative.id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(func.date(_doc_timestamp()) >= since)
        .distinct()
        .all()
    ]
    scored = []
    for tid in theme_ids:
        d = compute_debate(db, tid, lookback_days=days)
        if d and d.score >= min_score:
            scored.append((tid, d.score))
    scored.sort(key=lambda x: -x[1])
    ids = [tid for tid, _ in scored[:limit]]
    if not ids:
        return []
    cutoff_new = dt.date.today() - dt.timedelta(days=7)
    rows = _themes_with_last_updated(db, ids)
    id_to_row = {t.id: (t, last_updated) for t, last_updated in rows}
    return [
        _theme_out(
            id_to_row[tid][0],
            id_to_row[tid][1],
            id_to_row[tid][0].created_at and id_to_row[tid][0].created_at.date() >= cutoff_new,
        )
        for tid in ids
        if tid in id_to_row
    ]


def get_archived_themes(
    db: Session,
    inactive_days: int = 60,
) -> list:
    """Themes with no evidence in the last N days."""
    since_date = dt.date.today() - dt.timedelta(days=inactive_days)
    doc_date = func.date(_doc_timestamp())
    # Themes that have evidence in the window
    active_ids = set(
        r.theme_id
        for r in db.query(Narrative.theme_id)
        .join(Evidence, Evidence.narrative_id == Narrative.id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(doc_date >= since_date)
        .distinct()
        .all()
    )
    all_themes = db.query(Theme).all()
    archived = [t for t in all_themes if t.id not in active_ids]
    cutoff_new = dt.date.today() - dt.timedelta(days=7)
    rows = _themes_with_last_updated(db, [t.id for t in archived])
    id_to_last = {tid: last_updated for _t, last_updated in rows for tid in [_t.id]}
    return [
        _theme_out(
            t,
            id_to_last.get(t.id),
            t.created_at and t.created_at.date() >= cutoff_new,
        )
        for t in archived
    ]
