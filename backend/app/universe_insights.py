"""
Cross-universe market insights: consensus/non-consensus opportunities & risks,
plus forward-looking deductions from recent themes, narratives, and documents.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Document,
    Evidence,
    Narrative,
    Theme,
    ThemeInstrument,
    UniverseInsightsCache,
)
from app.settings import settings

logger = logging.getLogger("investing_agent.universe_insights")

PERIOD = "14d"


def _doc_date():
    return func.date(func.coalesce(Document.modified_at, Document.received_at))


def _lookback_days() -> int:
    return max(7, getattr(settings, "universe_insights_lookback_days", 14) or 14)


def _is_weekday(d: dt.date | None = None) -> bool:
    d = d or dt.date.today()
    return d.weekday() < 5


def _parse_llm_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0].rstrip()
    return json.loads(text.strip())


def _gather_context(db: Session, since: dt.date) -> dict[str, Any]:
    """Build structured context from the full recent universe (not basket-only)."""
    doc_date = _doc_date()

    doc_rows = (
        db.query(
            Document.id,
            Document.filename,
            Document.summary,
            doc_date.label("doc_date"),
        )
        .filter(doc_date >= since)
        .order_by(doc_date.desc())
        .limit(30)
        .all()
    )
    documents = [
        {
            "document_id": int(r.id),
            "title": (r.filename or "").strip(),
            "date": str(r.doc_date)[:10] if r.doc_date else None,
            "summary": (r.summary or "").strip()[:600] or None,
        }
        for r in doc_rows
    ]

    narrative_rows = (
        db.query(
            Narrative.id,
            Narrative.statement,
            Narrative.relation_to_prevailing,
            Narrative.narrative_stance,
            Narrative.sub_theme,
            Narrative.theme_id,
            Theme.canonical_label,
            func.count(Evidence.id).label("mention_count"),
        )
        .join(Theme, Theme.id == Narrative.theme_id)
        .join(Evidence, Evidence.narrative_id == Narrative.id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(doc_date >= since)
        .group_by(
            Narrative.id,
            Narrative.statement,
            Narrative.relation_to_prevailing,
            Narrative.narrative_stance,
            Narrative.sub_theme,
            Narrative.theme_id,
            Theme.canonical_label,
        )
        .order_by(func.count(Evidence.id).desc())
        .limit(60)
        .all()
    )
    narratives = [
        {
            "narrative_id": int(r.id),
            "theme_id": int(r.theme_id),
            "theme_label": r.canonical_label,
            "statement": (r.statement or "").strip()[:400],
            "relation": r.relation_to_prevailing or "unlabeled",
            "stance": r.narrative_stance,
            "sub_theme": r.sub_theme,
            "mention_count": int(r.mention_count or 0),
        }
        for r in narrative_rows
    ]

    evidence_catalog: list[dict[str, Any]] = []
    if narrative_rows:
        top_narrative_ids = [int(r.id) for r in narrative_rows[:40]]
        ev_rows = (
            db.query(
                Evidence.id,
                Evidence.narrative_id,
                Evidence.document_id,
                Evidence.quote,
                Document.filename,
                Narrative.theme_id,
                Theme.canonical_label,
            )
            .join(Narrative, Narrative.id == Evidence.narrative_id)
            .join(Theme, Theme.id == Narrative.theme_id)
            .join(Document, Document.id == Evidence.document_id)
            .filter(
                Evidence.narrative_id.in_(top_narrative_ids),
                doc_date >= since,
            )
            .order_by(Evidence.id.desc())
            .limit(80)
            .all()
        )
        for r in ev_rows:
            evidence_catalog.append(
                {
                    "evidence_id": int(r.id),
                    "narrative_id": int(r.narrative_id),
                    "document_id": int(r.document_id),
                    "theme_id": int(r.theme_id),
                    "theme_label": r.canonical_label,
                    "document_title": (r.filename or "").strip(),
                    "quote_snippet": (r.quote or "").strip()[:240],
                }
            )

    from app.analytics import (
        get_debated_themes,
        get_inflections,
        get_sentiment_rankings,
        get_trending_themes,
    )

    trending = get_trending_themes(db, recent_days=7, prior_days=21, limit=12)
    debated = get_debated_themes(db, days=21, limit=10, min_score=0.35)
    sentiment = get_sentiment_rankings(db, days=21, limit=8)
    inflections = get_inflections(db, recent_days=7, prior_days=21, limit=8)

    analytics = {
        "trending_themes": [t.canonical_label for t in trending],
        "debated_themes": [t.canonical_label for t in debated],
        "most_bullish": [t.canonical_label for t in sentiment.get("most_positive", [])[:6]],
        "most_bearish": [t.canonical_label for t in sentiment.get("most_negative", [])[:6]],
        "attention_peaking": [t.canonical_label for t in inflections.get("attention_peaking", [])[:6]],
        "bullish_turning_bearish": [
            t.canonical_label for t in inflections.get("bullish_turning_neutral_bearish", [])[:6]
        ],
    }

    external_news: list[dict[str, str]] = []
    try:
        from app.market_data import fetch_news_for_ticker

        seen_symbols: set[str] = set()
        for theme in trending[:5]:
            sym_row = (
                db.query(ThemeInstrument.symbol)
                .filter(ThemeInstrument.theme_id == theme.id)
                .order_by(ThemeInstrument.symbol)
                .first()
            )
            if not sym_row or not sym_row[0]:
                continue
            symbol = sym_row[0].upper()
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            news_res = fetch_news_for_ticker(symbol, limit=3)
            for item in news_res.get("items") or []:
                title = (item.get("title") or "").strip()
                if title:
                    external_news.append(
                        {
                            "symbol": symbol,
                            "theme": theme.canonical_label,
                            "title": title[:200],
                            "source": (item.get("source") or "")[:64],
                        }
                    )
    except Exception as e:
        logger.debug("External news fetch skipped: %s", e)

    consensus_narratives = [n for n in narratives if n["relation"] == "consensus"][:20]
    contrarian_narratives = [
        n for n in narratives if n["relation"] in ("contrarian", "new_angle")
    ][:20]

    return {
        "since": since.isoformat(),
        "documents": documents,
        "narratives": narratives,
        "evidence_catalog": evidence_catalog,
        "consensus_narratives": consensus_narratives,
        "contrarian_narratives": contrarian_narratives,
        "analytics": analytics,
        "external_news": external_news[:15],
    }


def _validate_evidence(
    raw_items: list[Any],
    db: Session,
    doc_ids: set[int],
    narr_ids: set[int],
    theme_ids: set[int],
) -> list[dict[str, Any]]:
    """Keep only evidence citations that reference real IDs; enrich with labels."""
    out: list[dict[str, Any]] = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        doc_id = item.get("document_id")
        narr_id = item.get("narrative_id")
        theme_id = item.get("theme_id")
        try:
            doc_id = int(doc_id) if doc_id is not None else None
        except (TypeError, ValueError):
            doc_id = None
        try:
            narr_id = int(narr_id) if narr_id is not None else None
        except (TypeError, ValueError):
            narr_id = None
        try:
            theme_id = int(theme_id) if theme_id is not None else None
        except (TypeError, ValueError):
            theme_id = None

        if doc_id is not None and doc_id not in doc_ids:
            doc_id = None
        if narr_id is not None and narr_id not in narr_ids:
            narr_id = None
        if theme_id is not None and theme_id not in theme_ids:
            theme_id = None
        if doc_id is None and narr_id is None and theme_id is None:
            continue

        entry: dict[str, Any] = {
            "document_id": doc_id,
            "narrative_id": narr_id,
            "theme_id": theme_id,
            "quote_snippet": (item.get("quote_snippet") or item.get("quote") or "").strip()[:240] or None,
        }
        if doc_id is not None:
            doc = db.query(Document.filename).filter(Document.id == doc_id).one_or_none()
            if doc:
                entry["document_title"] = doc.filename
        if theme_id is not None:
            theme = db.query(Theme.canonical_label).filter(Theme.id == theme_id).one_or_none()
            if theme:
                entry["theme_label"] = theme.canonical_label
        elif narr_id is not None:
            row = (
                db.query(Narrative.theme_id, Theme.canonical_label)
                .join(Theme, Theme.id == Narrative.theme_id)
                .filter(Narrative.id == narr_id)
                .one_or_none()
            )
            if row:
                entry["theme_id"] = row.theme_id
                entry["theme_label"] = row.canonical_label
        out.append(entry)
    return out[:6]


def _parse_insight_items(
    section: Any,
    db: Session,
    doc_ids: set[int],
    narr_ids: set[int],
    theme_ids: set[int],
    default_kind: str,
) -> list[dict[str, Any]]:
    if not isinstance(section, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in section[:3]:
        if not isinstance(raw, dict):
            continue
        title = (raw.get("title") or "").strip()
        hypothesis = (raw.get("hypothesis") or raw.get("summary") or "").strip()
        reasoning = (raw.get("reasoning") or raw.get("logic") or "").strip()
        if not title or not hypothesis:
            continue
        kind = (raw.get("kind") or raw.get("type") or default_kind).strip().lower()
        evidence = _validate_evidence(
            raw.get("evidence") or [],
            db,
            doc_ids,
            narr_ids,
            theme_ids,
        )
        items.append(
            {
                "title": title,
                "kind": kind,
                "hypothesis": hypothesis,
                "reasoning": reasoning,
                "evidence": evidence,
            }
        )
    return items


def generate_universe_insights(db: Session, *, force: bool = False) -> bool:
    """
    Generate cross-universe insights via LLM and store in UniverseInsightsCache.
    Returns True if generated, False if skipped.
    """
    if not settings.llm_api_key:
        logger.info("Skipping universe insights (no LLM_API_KEY)")
        return False

    lookback = _lookback_days()
    since = dt.date.today() - dt.timedelta(days=lookback)

    if not force and not _is_weekday():
        logger.info("Skipping universe insights (weekend)")
        return False

    existing = (
        db.query(UniverseInsightsCache)
        .filter(UniverseInsightsCache.period == PERIOD)
        .one_or_none()
    )
    if existing and not force:
        gen_date = existing.generated_at.date() if existing.generated_at else None
        if gen_date == dt.date.today():
            logger.info("Universe insights already fresh for today")
            return False

    context = _gather_context(db, since)
    if not context["narratives"] and not context["documents"]:
        logger.info("No recent narratives/documents for universe insights")
        return False

    doc_ids = {d["document_id"] for d in context["documents"]}
    narr_ids = {n["narrative_id"] for n in context["narratives"]}
    theme_ids = {n["theme_id"] for n in context["narratives"]}

    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    if len(context_json) > 120_000:
        context_json = context_json[:120_000] + "\n... [truncated]"

    user_prompt = (
        f"You are a senior investment strategist synthesizing the FULL recent research universe "
        f"(past {lookback} days). Your job is NOT to summarize — it is to REASON and DEDUCE.\n\n"
        "Use the structured context below (documents, narratives, evidence catalog, analytics, external news).\n"
        "Combine patterns across themes. Surface second-order implications. Flag what the crowd agrees on vs misses.\n\n"
        f"CONTEXT:\n{context_json}\n\n"
        "Return ONLY valid JSON (no markdown fence) with exactly these keys:\n"
        "{\n"
        '  "consensus": [ /* up to 3 items: widely-agreed opportunities OR risks */ ],\n'
        '  "non_consensus": [ /* up to 3 items: emerging, debated, or under-noticed angles */ ],\n'
        '  "forward_look": [ /* up to 3 items: logical deductions on rising sectors/themes/companies */ ]\n'
        "}\n\n"
        "Each item must have:\n"
        '- "title": short headline\n'
        '- "kind": one of opportunity | risk | sector | theme | company\n'
        '- "hypothesis": your deduced view (1-3 sentences, specific)\n'
        '- "reasoning": explain the logic chain — what facts/patterns led here (2-4 sentences). '
        "Show your work; cite themes and documents by name in the text.\n"
        '- "evidence": array of 1-4 citations using ONLY IDs from the context catalog:\n'
        '  {"document_id": int|null, "narrative_id": int|null, "theme_id": int|null, "quote_snippet": "..."}\n\n'
        "Rules:\n"
        "- consensus = multiple sources/themes align; relation=consensus narratives or repeated themes\n"
        "- non_consensus = contrarian/new_angle narratives, debated themes, low attention but meaningful signals\n"
        "- forward_look = extrapolate from today's trajectory (trending themes, inflections, catalysts) — "
        "state uncertainty but be specific about WHAT would rise and WHY\n"
        "- Every item needs at least one valid evidence citation with real IDs\n"
        "- Prefer actionable investment framing; avoid generic macro platitudes\n"
    )

    system = (
        "You are a rigorous investment analyst producing structured market insights. "
        "Reason deductively from evidence. Return valid JSON only."
    )

    try:
        from app.llm.provider import chat_completion

        model = getattr(settings, "llm_universe_insights_model", None) or getattr(
            settings, "llm_trading_digest_model", None
        ) or settings.llm_model
        raw = chat_completion(system=system, user=user_prompt, max_tokens=4096, model=model)
        data = _parse_llm_json(raw)
    except Exception as e:
        logger.warning("Universe insights LLM failed: %s", e)
        return False

    payload = {
        "consensus": _parse_insight_items(
            data.get("consensus"), db, doc_ids, narr_ids, theme_ids, "opportunity"
        ),
        "non_consensus": _parse_insight_items(
            data.get("non_consensus"), db, doc_ids, narr_ids, theme_ids, "risk"
        ),
        "forward_look": _parse_insight_items(
            data.get("forward_look"), db, doc_ids, narr_ids, theme_ids, "theme"
        ),
    }
    if not any(payload.values()):
        logger.warning("Universe insights LLM returned empty sections")
        return False

    now = dt.datetime.now(dt.timezone.utc)
    insights_json = json.dumps(payload, ensure_ascii=False)
    if existing:
        existing.insights_json = insights_json
        existing.lookback_days = lookback
        existing.generated_at = now
    else:
        db.add(
            UniverseInsightsCache(
                period=PERIOD,
                insights_json=insights_json,
                lookback_days=lookback,
                generated_at=now,
            )
        )
    db.commit()
    logger.info(
        "Generated universe insights: %d consensus, %d non-consensus, %d forward",
        len(payload["consensus"]),
        len(payload["non_consensus"]),
        len(payload["forward_look"]),
    )
    if getattr(settings, "llm_delay_after_request_seconds", 0) > 0:
        time.sleep(settings.llm_delay_after_request_seconds)
    return True


def get_universe_insights(db: Session) -> dict[str, Any]:
    """Load cached insights or return empty shell with stale flag."""
    lookback = _lookback_days()
    row = (
        db.query(UniverseInsightsCache)
        .filter(UniverseInsightsCache.period == PERIOD)
        .one_or_none()
    )
    empty = {
        "consensus": [],
        "non_consensus": [],
        "forward_look": [],
        "generated_at": None,
        "lookback_days": lookback,
        "stale": True,
    }
    if not row:
        return empty

    try:
        payload = json.loads(row.insights_json)
    except Exception:
        return empty

    gen_at = row.generated_at
    gen_date = gen_at.date() if gen_at else None
    today = dt.date.today()
    if gen_date is None:
        stale = True
    elif _is_weekday(today):
        stale = gen_date != today
    else:
        # Weekend: Friday's run is still fresh
        if today.weekday() == 5:
            last_weekday = today - dt.timedelta(days=1)
        else:
            last_weekday = today - dt.timedelta(days=2)
        stale = gen_date < last_weekday

    return {
        "consensus": payload.get("consensus") or [],
        "non_consensus": payload.get("non_consensus") or [],
        "forward_look": payload.get("forward_look") or [],
        "generated_at": gen_at.isoformat() if gen_at else None,
        "lookback_days": row.lookback_days or lookback,
        "stale": stale,
    }
