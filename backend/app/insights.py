"""
Narrative evolution insights: trajectory, consensus over time, emerging angles, debate intensity.

Designed to answer:
1. How does the theme change over time (e.g. US consumer confidence — better/worse)?
2. What are new emerging topics/angles (e.g. AI skilling)?
3. How does consensus change (e.g. Hyperscaler capex: positive → ROI worries)?
4. Which themes are heavily debated with no quick conclusion?
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import TYPE_CHECKING, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Document, Evidence, Narrative, Theme

if TYPE_CHECKING:
    from app.schemas import (
        ConsensusPeriodOut,
        EmergingNarrativeOut,
        ThemeDebateOut,
        ThemeInsightsOut,
        TrajectoryPointOut,
    )


def _doc_date():
    return func.date(func.coalesce(Document.modified_at, Document.received_at))


def _doc_timestamp():
    return func.coalesce(Document.modified_at, Document.received_at)


def compute_trajectory(
    db: Session,
    theme_id: int,
    since: dt.date,
    window_days: int = 7,
) -> list["TrajectoryPointOut"]:
    """
    Derive theme direction over time from mention volume and share of voice.
    Each point = one week; direction = improving | worsening | mixed | unchanged.
    """
    from app.schemas import TrajectoryPointOut

    # Get daily metrics (from Evidence if no ThemeMentionsDaily)
    doc_date = _doc_date()
    daily = (
        db.query(
            doc_date.label("date"),
            func.count(Evidence.id).label("mention_count"),
            func.count(func.distinct(Document.id)).label("doc_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Evidence.narrative_id == Narrative.id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(Narrative.theme_id == theme_id, doc_date >= since)
        .group_by(doc_date)
        .order_by(doc_date.asc())
        .all()
    )
    if not daily:
        return []

    # Total docs per day for share
    all_dates = {getattr(r.date, "isoformat", lambda: str(r.date)[:10])() for r in daily}
    total_docs_q = (
        db.query(doc_date.label("date"), func.count(Document.id).label("total"))
        .select_from(Document)
        .filter(doc_date >= since)
        .group_by(doc_date)
        .all()
    )
    total_by_date = {}
    for row in total_docs_q:
        d = row.date
        if hasattr(d, "isoformat"):
            total_by_date[d.isoformat()[:10]] = int(row.total or 0)
        else:
            total_by_date[str(d)[:10]] = int(row.total or 0)

    # Build date -> (mention_count, share)
    by_date: dict[str, tuple[int, float]] = {}
    for r in daily:
        d = r.date
        date_str = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
        mentions = int(r.mention_count or 0)
        total = total_by_date.get(date_str, 0)
        share = mentions / total if total > 0 else 0.0
        by_date[date_str] = (mentions, share)

    sorted_dates = sorted(by_date.keys())
    if len(sorted_dates) < 2:
        return []

    out: list[TrajectoryPointOut] = []
    for i in range(window_days, len(sorted_dates) + 1):
        window = sorted_dates[i - window_days : i]
        current_date = window[-1]
        prev_date = window[0]
        m_now, s_now = by_date[current_date]
        m_prev, s_prev = by_date.get(prev_date, (0, 0.0))

        mention_trend = (m_now - m_prev) / m_prev if m_prev else (m_now - m_prev)
        share_trend = (s_now - s_prev) if s_prev else (s_now - s_prev)

        # Classify direction
        if mention_trend > 0.15 and share_trend > 0:
            direction = "improving"
        elif mention_trend < -0.15 or share_trend < -0.01:
            direction = "worsening"
        elif abs(mention_trend) <= 0.15 and abs(share_trend) <= 0.01:
            direction = "unchanged"
        else:
            direction = "mixed"

        note = None
        if direction == "improving":
            note = "Rising attention and share of voice"
        elif direction == "worsening":
            note = "Declining attention or share"
        elif direction == "mixed":
            note = "Mixed or volatile signals"

        out.append(
            TrajectoryPointOut(
                date=current_date,
                direction=direction,
                note=note,
                mention_trend=round(mention_trend, 3),
                share_trend=round(share_trend, 4),
            )
        )
    return out[-24:]  # last ~24 weeks if weekly; for daily window keep last 24 points


def compute_consensus_evolution(
    db: Session,
    theme_id: int,
    since: dt.date,
    period_days: int = 7,
) -> list["ConsensusPeriodOut"]:
    """
    For each time period (e.g. week), identify the prevailing narrative (most evidence).
    Shows how the dominant view shifts over time.
    """
    from app.schemas import ConsensusPeriodOut

    doc_date = _doc_date()
    # Evidence count per (date, narrative_id) for this theme
    rows = (
        db.query(
            doc_date.label("date"),
            Narrative.id.label("narrative_id"),
            Narrative.statement,
            func.count(Evidence.id).label("mention_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Evidence.narrative_id == Narrative.id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(Narrative.theme_id == theme_id, doc_date >= since)
        .group_by(doc_date, Narrative.id, Narrative.statement)
        .all()
    )
    if not rows:
        return []

    # Group by period (e.g. week)
    period_counts: dict[str, dict[int, tuple[str, int]]] = defaultdict(lambda: defaultdict(lambda: ("", 0)))
    for r in rows:
        d = r.date
        date_str = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
        try:
            from datetime import datetime
            dt_val = datetime.strptime(date_str, "%Y-%m-%d").date()
            # Week key: start of week
            days_since_monday = dt_val.weekday()
            week_start = dt_val - dt.timedelta(days=days_since_monday)
            period_key = week_start.isoformat()
        except Exception:
            period_key = date_str[:7]  # fallback: year-month
        existing_stmt, existing_count = period_counts[period_key][r.narrative_id]
        new_count = int(r.mention_count or 0) + (existing_count or 0)
        period_counts[period_key][r.narrative_id] = (r.statement or existing_stmt, new_count)

    # Per period: total mentions and top narrative
    evolution: list[ConsensusPeriodOut] = []
    for period_start in sorted(period_counts.keys()):
        narrs = period_counts[period_start]
        total = sum(c for _, c in narrs.values())
        if total == 0:
            continue
        top_nid = max(narrs.keys(), key=lambda nid: narrs[nid][1])
        stmt, count = narrs[top_nid]
        share = count / total
        # Period end = period_start + period_days
        try:
            end = dt.datetime.strptime(period_start, "%Y-%m-%d").date() + dt.timedelta(days=period_days)
            period_end = end.isoformat()
        except Exception:
            period_end = period_start
        evolution.append(
            ConsensusPeriodOut(
                period_start=period_start,
                period_end=period_end,
                narrative_id=top_nid,
                statement=(stmt[:200] + "…") if len(stmt) > 200 else stmt,
                share=round(share, 3),
                mention_count=count,
            )
        )
    # Dedupe consecutive periods with same narrative (merge)
    merged: list[ConsensusPeriodOut] = []
    for p in evolution:
        if merged and merged[-1].narrative_id == p.narrative_id and merged[-1].statement == p.statement:
            last = merged[-1]
            merged[-1] = ConsensusPeriodOut(
                period_start=last.period_start,
                period_end=p.period_end,
                narrative_id=last.narrative_id,
                statement=last.statement,
                share=last.share,
                mention_count=last.mention_count + p.mention_count,
            )
            continue
        merged.append(p)
    return merged[-16:]  # last 16 periods


def compute_emerging(
    db: Session,
    theme_id: int,
    lookback_days: int = 60,
) -> list["EmergingNarrativeOut"]:
    """
    Narratives that appeared recently (first_seen in lookback) or have high novelty.
    Surfaces new angles and topics.
    """
    from app.schemas import EmergingNarrativeOut

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)
    narratives = (
        db.query(Narrative)
        .filter(
            Narrative.theme_id == theme_id,
            Narrative.first_seen >= cutoff,
        )
        .order_by(Narrative.first_seen.desc())
        .limit(20)
        .all()
    )
    out: list[EmergingNarrativeOut] = []
    for n in narratives:
        mention_count = (
            db.query(func.count(Evidence.id))
            .filter(Evidence.narrative_id == n.id)
            .scalar()
            or 0
        )
        # Optional: get latest novelty from NarrativeMentionsDaily
        novelty_score = None
        try:
            from app.models import NarrativeMentionsDaily
            nd = (
                db.query(NarrativeMentionsDaily)
                .filter(
                    NarrativeMentionsDaily.narrative_id == n.id,
                )
                .order_by(NarrativeMentionsDaily.date.desc())
                .first()
            )
            if nd and nd.novelty_score is not None:
                novelty_score = round(nd.novelty_score, 2)
        except Exception:
            pass
        out.append(
            EmergingNarrativeOut(
                narrative_id=n.id,
                statement=n.statement,
                first_seen=n.first_seen.isoformat()[:10] if n.first_seen else "",
                mention_count=int(mention_count),
                novelty_score=novelty_score,
                relation_to_prevailing=(n.relation_to_prevailing or "unlabeled"),
            )
        )
    return out


def compute_debate(
    db: Session,
    theme_id: int,
    lookback_days: int = 90,
) -> Optional["ThemeDebateOut"]:
    """
    Debate intensity: multiple competing narratives with no single dominant view.
    score = 1 - top_share (or entropy-based). High score = heavily debated.
    """
    from app.schemas import ThemeDebateOut

    since = dt.date.today() - dt.timedelta(days=lookback_days)
    doc_date = _doc_date()
    rows = (
        db.query(
            Narrative.id.label("narrative_id"),
            func.count(Evidence.id).label("mention_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Evidence.narrative_id == Narrative.id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(Narrative.theme_id == theme_id, doc_date >= since)
        .group_by(Narrative.id)
        .all()
    )
    if not rows:
        return None
    total = sum(int(r.mention_count or 0) for r in rows)
    if total == 0:
        return None
    shares = [int(r.mention_count or 0) / total for r in rows]
    top_share = max(shares)
    narrative_count = len(rows)
    # Debate score: 1 - top_share (so if one narrative has 90%, score=0.1; if even, score high)
    score = round(1.0 - top_share, 3)
    if narrative_count >= 4 and top_share < 0.4:
        label = "Heavily debated"
    elif narrative_count >= 2 and top_share < 0.6:
        label = "Moderate debate"
    elif top_share >= 0.7:
        label = "Clear consensus"
    else:
        label = "Some debate"
    return ThemeDebateOut(
        score=score,
        label=label,
        narrative_count=narrative_count,
        top_narrative_share=round(top_share, 3),
    )


def get_theme_insights(
    db: Session,
    theme_id: int,
    months: int = 6,
) -> "ThemeInsightsOut":
    """Build full insights payload for a theme."""
    from app.schemas import ThemeInsightsOut

    since = dt.date.today() - dt.timedelta(days=months * 31)
    trajectory = compute_trajectory(db, theme_id, since)
    consensus_evolution = compute_consensus_evolution(db, theme_id, since)
    emerging = compute_emerging(db, theme_id, lookback_days=min(90, months * 31))
    debate = compute_debate(db, theme_id, lookback_days=min(90, months * 31))
    return ThemeInsightsOut(
        trajectory=trajectory,
        consensus_evolution=consensus_evolution,
        emerging=emerging,
        debate=debate,
    )
