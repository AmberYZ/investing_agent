from __future__ import annotations

import datetime as dt
from collections import defaultdict
from statistics import mean, pstdev
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

def _doc_date():
    """Document date for grouping: use file date (modified_at) when set, else received_at."""
    return func.date(func.coalesce(Document.modified_at, Document.received_at))

from app.db import SessionLocal, engine, init_db
from app.models import (
    Base,
    Document,
    Evidence,
    Narrative,
    NarrativeMentionsDaily,
    Theme,
    ThemeMentionsDaily,
    ThemeNarrativeSummaryCache,
    ThemeRelationDaily,
    ThemeSubThemeMentionsDaily,
    ThemeSubThemeMetrics,
)


def _get_or_create_theme_daily(db: Session, theme_id: int, date: dt.date) -> ThemeMentionsDaily:
    row = (
        db.query(ThemeMentionsDaily)
        .filter(ThemeMentionsDaily.theme_id == theme_id, ThemeMentionsDaily.date == date)
        .one_or_none()
    )
    if row is None:
        row = ThemeMentionsDaily(theme_id=theme_id, date=date, doc_count=0, mention_count=0)
        db.add(row)
    return row


def _get_or_create_theme_relation_daily(db: Session, theme_id: int, date: dt.date) -> ThemeRelationDaily:
    row = (
        db.query(ThemeRelationDaily)
        .filter(ThemeRelationDaily.theme_id == theme_id, ThemeRelationDaily.date == date)
        .one_or_none()
    )
    if row is None:
        row = ThemeRelationDaily(
            theme_id=theme_id,
            date=date,
            consensus_count=0,
            contrarian_count=0,
            refinement_count=0,
            new_angle_count=0,
        )
        db.add(row)
    return row


def _get_or_create_theme_sub_theme_daily(
    db: Session, theme_id: int, sub_theme: str, date: dt.date
) -> ThemeSubThemeMentionsDaily:
    row = (
        db.query(ThemeSubThemeMentionsDaily)
        .filter(
            ThemeSubThemeMentionsDaily.theme_id == theme_id,
            ThemeSubThemeMentionsDaily.sub_theme == sub_theme,
            ThemeSubThemeMentionsDaily.date == date,
        )
        .one_or_none()
    )
    if row is None:
        row = ThemeSubThemeMentionsDaily(
            theme_id=theme_id,
            sub_theme=sub_theme,
            date=date,
            doc_count=0,
            mention_count=0,
        )
        db.add(row)
    return row


def _get_or_create_narrative_daily(db: Session, narrative_id: int, date: dt.date) -> NarrativeMentionsDaily:
    row = (
        db.query(NarrativeMentionsDaily)
        .filter(NarrativeMentionsDaily.narrative_id == narrative_id, NarrativeMentionsDaily.date == date)
        .one_or_none()
    )
    if row is None:
        row = NarrativeMentionsDaily(
            narrative_id=narrative_id,
            date=date,
            doc_count=0,
            mention_count=0,
        )
        db.add(row)
    return row


def _compute_burst_and_accel(
    history: list[tuple[dt.date, int]],
    target_date: dt.date,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute simple burst (z-score vs trailing 30d) and acceleration (3d MA - 7d MA)
    for a narrative on a given date.
    """
    if not history:
        return None, None

    history = sorted(history, key=lambda x: x[0])
    today_mentions = next((v for d, v in history if d == target_date), 0)

    prev_values = [v for d, v in history if d < target_date][-30:]
    burst: Optional[float] = None
    if prev_values:
        mu = mean(prev_values)
        sigma = pstdev(prev_values) or 0.0
        if sigma > 0:
            burst = (today_mentions - mu) / sigma

    def _moving_avg(days: int) -> Optional[float]:
        window = [v for d, v in history if d <= target_date][-days:]
        if not window:
            return None
        return float(sum(window)) / len(window)

    ma3 = _moving_avg(3)
    ma7 = _moving_avg(7)
    accel: Optional[float] = None
    if ma3 is not None and ma7 is not None:
        accel = ma3 - ma7

    return burst, accel


def _compute_novelty(first_seen: dt.datetime, target_date: dt.date) -> float:
    days = (target_date - first_seen.date()).days
    if days <= 1:
        return 1.0
    if days <= 7:
        return 0.5
    return 0.0


def run_daily_aggregations(target_date: Optional[dt.date] = None) -> None:
    """
    Compute daily mention stats and narrative status for a given date.

    This is intended to be invoked once per day by Cloud Scheduler,
    but can also be run manually.
    """
    if target_date is None:
        target_date = dt.date.today()

    init_db()
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 1) Aggregate mentions per narrative/theme for the target date (include relation_to_prevailing)
        rows = (
            db.query(
                Narrative.id.label("narrative_id"),
                Narrative.relation_to_prevailing.label("relation_to_prevailing"),
                Theme.id.label("theme_id"),
                func.count(Evidence.id).label("mention_count"),
                func.count(func.distinct(Document.id)).label("doc_count"),
            )
            .join(Evidence, Evidence.narrative_id == Narrative.id)
            .join(Document, Document.id == Evidence.document_id)
            .join(Theme, Theme.id == Narrative.theme_id)
            .filter(_doc_date() == target_date)
            .group_by(Narrative.id, Narrative.relation_to_prevailing, Theme.id)
            .all()
        )

        theme_totals: dict[int, int] = defaultdict(int)

        for r in rows:
            n_id = int(r.narrative_id)
            t_id = int(r.theme_id)
            doc_count = int(r.doc_count or 0)
            mention_count = int(r.mention_count or 0)
            rel = (r.relation_to_prevailing or "consensus").lower()
            if rel not in ("consensus", "contrarian", "refinement", "new_angle"):
                rel = "consensus"

            n_daily = _get_or_create_narrative_daily(db, n_id, target_date)
            n_daily.doc_count = doc_count
            n_daily.mention_count = mention_count

            t_daily = _get_or_create_theme_daily(db, t_id, target_date)
            t_daily.doc_count += doc_count
            t_daily.mention_count += mention_count

            theme_totals[t_id] += mention_count

            # Theme relation daily breakdown
            rel_daily = _get_or_create_theme_relation_daily(db, t_id, target_date)
            if rel == "consensus":
                rel_daily.consensus_count += mention_count
            elif rel == "contrarian":
                rel_daily.contrarian_count += mention_count
            elif rel == "refinement":
                rel_daily.refinement_count += mention_count
            else:
                rel_daily.new_angle_count += mention_count

        # 1b) Aggregate by (theme_id, sub_theme) for ThemeSubThemeMentionsDaily (narratives with sub_theme set)
        sub_theme_rows = (
            db.query(
                Narrative.theme_id,
                Narrative.sub_theme,
                func.count(Evidence.id).label("mention_count"),
                func.count(func.distinct(Document.id)).label("doc_count"),
            )
            .join(Evidence, Evidence.narrative_id == Narrative.id)
            .join(Document, Document.id == Evidence.document_id)
            .filter(
                _doc_date() == target_date,
                Narrative.sub_theme.isnot(None),
                Narrative.sub_theme != "",
            )
            .group_by(Narrative.theme_id, Narrative.sub_theme)
            .all()
        )
        for r in sub_theme_rows:
            st = (r.sub_theme or "").strip()[:128]
            if not st:
                continue
            row = _get_or_create_theme_sub_theme_daily(db, int(r.theme_id), st, target_date)
            row.doc_count = int(r.doc_count or 0)
            row.mention_count = int(r.mention_count or 0)

        # 2) Compute share_of_voice per theme: doc_count / total_docs (share of that day's documents that mention this theme)
        # Denominator = all documents received that day (e.g. 5 docs, theme in 2 → 2/5 = 40%).
        total_docs = (
            db.query(func.count(Document.id))
            .filter(_doc_date() == target_date)
            .scalar()
            or 0
        )
        if total_docs > 0:
            for theme_id in theme_totals:
                row = _get_or_create_theme_daily(db, theme_id, target_date)
                row.share_of_voice = float(row.doc_count) / total_docs

        db.commit()

        # 3) Compute burst / accel / novelty per narrative
        for r in rows:
            n_id = int(r.narrative_id)
            narrative = db.query(Narrative).filter(Narrative.id == n_id).one()

            history_rows = (
                db.query(NarrativeMentionsDaily)
                .filter(
                    NarrativeMentionsDaily.narrative_id == n_id,
                    NarrativeMentionsDaily.date <= target_date,
                    NarrativeMentionsDaily.date >= target_date - dt.timedelta(days=30),
                )
                .all()
            )
            history = [(h.date, int(h.mention_count or 0)) for h in history_rows]

            burst, accel = _compute_burst_and_accel(history, target_date)
            novelty = _compute_novelty(narrative.first_seen, target_date)

            today_row = _get_or_create_narrative_daily(db, n_id, target_date)
            today_row.burst_score = burst
            today_row.accel_score = accel
            today_row.novelty_score = novelty

        db.commit()

        # 4) Generate LLM narrative summaries for all themes (cached, not on page load)
        try:
            summary_count = generate_theme_narrative_summaries(db)
            if summary_count > 0:
                import logging
                logging.getLogger("investing_agent.aggregations").info(
                    "Generated %d theme narrative summaries", summary_count
                )
        except Exception as e:
            import logging
            logging.getLogger("investing_agent.aggregations").warning(
                "LLM narrative summary generation failed: %s", e
            )
    finally:
        db.close()


def compute_theme_sub_theme_metrics(db: Session, theme_id: Optional[int] = None) -> None:
    """
    Compute novelty_type and narrative_stage per (theme_id, sub_theme) from narrative statistics.
    No LLM; purely lookback heuristics. Call after run_daily_aggregations or on a schedule.
    """
    from app.models import ThemeSubThemeMetrics

    # All (theme_id, sub_theme) that have at least one narrative with sub_theme set
    q = (
        db.query(Narrative.theme_id, Narrative.sub_theme)
        .filter(
            Narrative.sub_theme.isnot(None),
            Narrative.sub_theme != "",
        )
        .distinct()
    )
    if theme_id is not None:
        q = q.filter(Narrative.theme_id == theme_id)
    pairs = [(int(r.theme_id), (r.sub_theme or "").strip()[:128]) for r in q.all() if (r.sub_theme or "").strip()]

    now = dt.datetime.now(dt.timezone.utc)
    for tid, sub_theme in pairs:
        if not sub_theme:
            continue
        # Heuristics: use mention history from ThemeSubThemeMentionsDaily if available
        daily_rows = (
            db.query(ThemeSubThemeMentionsDaily)
            .filter(
                ThemeSubThemeMentionsDaily.theme_id == tid,
                ThemeSubThemeMentionsDaily.sub_theme == sub_theme,
                ThemeSubThemeMentionsDaily.date >= dt.date.today() - dt.timedelta(days=90),
            )
            .order_by(ThemeSubThemeMentionsDaily.date.asc())
            .all()
        )
        mention_history = [(r.date, int(r.mention_count or 0)) for r in daily_rows]

        # narrative_stage: early (growing), mainstream (stable), late (declining), contested (mixed stances)
        narrative_stage: Optional[str] = "mainstream"
        if len(mention_history) >= 7:
            recent = [v for _, v in mention_history[-7:]]
            older = [v for _, v in mention_history[: max(0, len(mention_history) - 7)]]
            if older:
                recent_avg = sum(recent) / len(recent)
                older_avg = sum(older) / len(older)
                if older_avg == 0 and recent_avg > 0:
                    narrative_stage = "early"
                elif older_avg > 0 and recent_avg > older_avg * 1.2:
                    narrative_stage = "early"
                elif older_avg > 0 and recent_avg < older_avg * 0.6:
                    narrative_stage = "late"
        elif mention_history:
            narrative_stage = "early"

        # novelty_type: new (first activity recent), evolving (growth), reversal (stance mix changed - skip for now)
        novelty_type: Optional[str] = "evolving"
        if mention_history:
            first_date = mention_history[0][0]
            if (dt.date.today() - first_date).days <= 14:
                novelty_type = "new"
            elif narrative_stage == "early":
                novelty_type = "evolving"

        existing = (
            db.query(ThemeSubThemeMetrics)
            .filter(
                ThemeSubThemeMetrics.theme_id == tid,
                ThemeSubThemeMetrics.sub_theme == sub_theme,
            )
            .one_or_none()
        )
        if existing:
            existing.novelty_type = novelty_type
            existing.narrative_stage = narrative_stage
            existing.computed_at = now
        else:
            db.add(
                ThemeSubThemeMetrics(
                    theme_id=tid,
                    sub_theme=sub_theme,
                    novelty_type=novelty_type,
                    narrative_stage=narrative_stage,
                    computed_at=now,
                )
            )
    db.commit()


def generate_theme_narrative_summaries(db: Session, theme_id: Optional[int] = None) -> int:
    """
    Generate LLM-powered narrative summaries for themes (past 30 days).
    Stores results in ThemeNarrativeSummaryCache.
    Returns count of summaries generated.
    """
    import json
    import logging
    from app.models import ThemeNarrativeSummaryCache
    from app.settings import settings

    logger = logging.getLogger("investing_agent.aggregations")

    if not settings.llm_api_key:
        logger.info("Skipping LLM narrative summaries (no LLM_API_KEY)")
        return 0

    q = db.query(Theme)
    if theme_id is not None:
        q = q.filter(Theme.id == theme_id)
    themes = q.all()

    since = dt.date.today() - dt.timedelta(days=30)
    doc_date = func.date(func.coalesce(Document.modified_at, Document.received_at))
    count = 0

    for theme in themes:
        # Gather narratives with recent evidence
        
        recent_narratives = (
            db.query(Narrative)
            .join(Evidence, Evidence.narrative_id == Narrative.id)
            .join(Document, Document.id == Evidence.document_id)
            .filter(Narrative.theme_id == theme.id, doc_date >= since)
            .distinct()
            .all()
        )
        
        if not recent_narratives:
            continue

        # Build a compact input for the LLM
        narrative_lines = []
        for n in recent_narratives:  # cap at 30 narratives
            stance = n.narrative_stance or "unknown"
            conf = n.confidence_level or "unknown"
            sub = n.sub_theme or "general"
            narrative_lines.append(
                f"- [{stance}, {conf}, sub-theme: {sub}] {n.statement}"
            )

        user_prompt = (
            f"Theme: {theme.canonical_label}\n"
            f"Description: {theme.description or 'N/A'}\n\n"
            f"Narratives from the past 30 days:\n"
            + "\n".join(narrative_lines)
            + "\n\n"
            "Write a SHORT, punchy analyst briefing (max 8-10 bullet points total, not paragraphs). "
            "Use **bold** on key figures, company names, and important shifts so a reader can scan quickly.\n\n"
            "Structure:\n"
            "**Consensus view**: 2-3 bullets on the prevailing facts and opinions.\n"
            "**What changed this month**: 2-3 bullets on new developments or tone shifts.\n"
            "**Key debates**: 1-2 bullets on bull vs bear disagreements.\n"
            "**Watch list**: 1-2 bullets on upcoming catalysts or risks.\n\n"
            "Be specific — cite actual claims. Keep each bullet to 1-2 sentences max. Professional analyst tone.\n"
            "Return ONLY a JSON object: {\"summary\": \"...\", \"trending_sub_themes\": [\"...\"], \"inflection_alert\": \"...\" or null}\n"
        )
        
        system = (
            "You are a senior investment analyst summarizing the latest narrative landscape for an investment theme. "
            "Be concise, insightful, and actionable. Return valid JSON only."
        )

        try:
            from app.llm.provider import chat_completion

            raw = chat_completion(system=system, user=user_prompt, max_tokens=2048)
            

            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0].rstrip()

            data = json.loads(raw.strip())

            # Be robust to the model returning either:
            # - {"summary": "plain string", ...}
            # - {"summary": { "Consensus view": [...], "What changed": [...] }, ...}
            summary_val = data.get("summary", "")
            if isinstance(summary_val, dict):
                # Flatten structured summary sections into a single markdown string.
                parts: list[str] = []
                for section, content in summary_val.items():
                    if isinstance(content, list):
                        text = "; ".join(str(item).strip() for item in content if str(item).strip())
                    else:
                        text = str(content).strip()
                    if text:
                        parts.append(f"**{section}**: {text}")
                summary_text = "\n".join(parts).strip()
            else:
                summary_text = str(summary_val).strip()

            trending = data.get("trending_sub_themes", [])
            # Normalise trending_sub_themes to a simple list of strings.
            if isinstance(trending, dict):
                trending = [str(v).strip() for v in trending.values() if str(v).strip()]
            elif isinstance(trending, list):
                trending = [str(v).strip() for v in trending if str(v).strip()]
            else:
                trending = [str(trending).strip()] if str(trending).strip() else []

            inflection = data.get("inflection_alert")
            if isinstance(inflection, dict):
                # Store a concise string representation if the model returns a structured alert.
                inflection = str(inflection)

            if not summary_text:
                continue
        except Exception as e:
            logger.warning("Failed to generate summary for theme %s: %s", theme.id, e)
            continue

        # Upsert cache
        existing = (
            db.query(ThemeNarrativeSummaryCache)
            .filter(ThemeNarrativeSummaryCache.theme_id == theme.id, ThemeNarrativeSummaryCache.period == "30d")
            .one_or_none()
        )
        now = dt.datetime.now(dt.timezone.utc)
        
        
        if existing:
            existing.summary = summary_text
            existing.trending_sub_themes = json.dumps(trending) if trending else None
            existing.inflection_alert = inflection
            existing.generated_at = now
        else:
            db.add(ThemeNarrativeSummaryCache(
                theme_id=theme.id,
                period="30d",
                summary=summary_text,
                trending_sub_themes=json.dumps(trending) if trending else None,
                inflection_alert=inflection,
                generated_at=now,
            ))
        db.flush()
        count += 1
        logger.info("Generated narrative summary for theme %s (%s)", theme.id, theme.canonical_label)

        # Respect rate limit
        import time
        if settings.llm_delay_after_request_seconds > 0:
            time.sleep(settings.llm_delay_after_request_seconds)

    db.commit()
    return count


if __name__ == "__main__":
    run_daily_aggregations()

