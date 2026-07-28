"""
Cross-universe market insights: consensus/non-consensus opportunities & risks
(with independent valuation judgment via EODHD), plus a forward look that is
deliberately detached from source documents.
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


def _gather_valuations(db: Session, themes: list[Any], limit: int = 12) -> list[dict[str, Any]]:
    """Pull compact EODHD valuation snapshots for theme-linked tickers."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        from app.market_data import get_prices_and_valuation
    except Exception as e:
        logger.debug("Valuation import skipped: %s", e)
        return out

    for theme in themes[:limit]:
        sym_row = (
            db.query(ThemeInstrument.symbol)
            .filter(ThemeInstrument.theme_id == theme.id)
            .order_by(ThemeInstrument.symbol)
            .first()
        )
        if not sym_row or not sym_row[0]:
            continue
        symbol = str(sym_row[0]).upper().strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        try:
            data = get_prices_and_valuation(symbol, months=6)
        except Exception as e:
            logger.debug("Valuation fetch failed for %s: %s", symbol, e)
            continue
        if not isinstance(data, dict):
            continue
        entry = {
            "symbol": symbol,
            "theme": theme.canonical_label,
            "trailing_pe": data.get("trailing_pe"),
            "forward_pe": data.get("forward_pe"),
            "peg_ratio": data.get("peg_ratio"),
            "ev_to_ebitda": data.get("ev_to_ebitda"),
            "last_close": None,
            "pct_1m": data.get("pct_1m") or data.get("return_1m"),
            "message": data.get("message"),
        }
        prices = data.get("prices") or []
        if prices:
            last = prices[-1] if isinstance(prices[-1], dict) else None
            if last:
                entry["last_close"] = last.get("close") or last.get("adjusted_close")
        # Skip empty shells
        if any(entry.get(k) is not None for k in ("trailing_pe", "forward_pe", "peg_ratio", "ev_to_ebitda", "last_close")):
            out.append(entry)
    return out


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

    market_valuations = _gather_valuations(db, list(trending) + list(debated), limit=12)

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
        "market_valuations": market_valuations,
        "external_news": external_news[:15],
    }


def _validate_evidence(
    raw_items: list[Any],
    db: Session,
    doc_ids: set[int],
    narr_ids: set[int],
    theme_ids: set[int],
    *,
    allow_empty: bool = False,
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
    if allow_empty and not out:
        return []
    return out[:6]


def _parse_insight_items(
    section: Any,
    db: Session,
    doc_ids: set[int],
    narr_ids: set[int],
    theme_ids: set[int],
    default_kind: str,
    *,
    require_evidence: bool = True,
    max_items: int = 3,
    require_tickers: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(section, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in section[: max(1, max_items)]:
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
            allow_empty=not require_evidence,
        )
        if require_evidence and not evidence:
            # Soft-fail: keep item if reasoning is substantive (analyst judgment may outrun citations)
            if len(reasoning) < 40:
                continue

        tickers_raw = raw.get("tickers") or raw.get("instruments") or raw.get("symbols") or []
        tickers: list[str] = []
        if isinstance(tickers_raw, str):
            tickers_raw = [t.strip() for t in tickers_raw.replace(";", ",").split(",")]
        if isinstance(tickers_raw, list):
            for t in tickers_raw:
                sym = str(t or "").strip().upper()
                if not sym:
                    continue
                # Keep short ticker-like tokens (incl. ETF symbols); drop sentences
                if len(sym) > 12 or " " in sym:
                    continue
                if sym not in tickers:
                    tickers.append(sym)
        if require_tickers and not tickers:
            continue

        items.append(
            {
                "title": title,
                "kind": kind,
                "hypothesis": hypothesis,
                "reasoning": reasoning,
                "evidence": evidence,
                "tickers": tickers,
            }
        )
    return items


def _call_llm(system: str, user_prompt: str, max_tokens: int = 4096) -> dict[str, Any]:
    from app.llm.provider import chat_completion

    model = getattr(settings, "llm_universe_insights_model", None) or getattr(
        settings, "llm_trading_digest_model", None
    ) or settings.llm_model
    raw = chat_completion(system=system, user=user_prompt, max_tokens=max_tokens, model=model)
    return _parse_llm_json(raw)


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

    # Slim context for consensus / non-consensus (still needs docs + valuations)
    consensus_context = {
        "since": context["since"],
        "documents": context["documents"],
        "narratives": context["narratives"][:40],
        "evidence_catalog": context["evidence_catalog"][:50],
        "consensus_narratives": context["consensus_narratives"],
        "contrarian_narratives": context["contrarian_narratives"],
        "analytics": context["analytics"],
        "market_valuations": context["market_valuations"],
        "external_news": context["external_news"],
    }
    context_json = json.dumps(consensus_context, ensure_ascii=False, indent=2)
    if len(context_json) > 100_000:
        context_json = context_json[:100_000] + "\n... [truncated]"

    consensus_prompt = (
        f"You are a senior investment strategist with independent judgment. "
        f"Lookback: past {lookback} days.\n\n"
        "Your job is NOT to pick the latest articles or parrot what documents call "
        "'opportunities' or 'risks'. REASON for yourself.\n\n"
        "For every opportunity or risk you propose:\n"
        "1) Start from patterns across themes/narratives (not a single doc).\n"
        "2) Stress-test with market_valuations (trailing/forward PE, PEG, EV/EBITDA, price).\n"
        "   - A document calling something an 'opportunity' is NOT enough if valuation already "
        "prices in the good news, or if risk looks overstated relative to multiples.\n"
        "   - Explicitly mention valuation in reasoning when a ticker is in market_valuations.\n"
        "3) Prefer second-order implications over restating headlines.\n\n"
        f"CONTEXT:\n{context_json}\n\n"
        "Return ONLY valid JSON (no markdown fence):\n"
        "{\n"
        '  "consensus": [ /* up to 3: widely-agreed setups you judge as real opportunities OR risks '
        "AFTER valuation/logic check */ ],\n"
        '  "non_consensus": [ /* up to 3: emerging/debated/under-noticed angles you independently '
        "find investable */ ]\n"
        "}\n\n"
        "Each item:\n"
        '- "title": short headline\n'
        '- "kind": opportunity | risk\n'
        '- "hypothesis": your view (1-3 sentences, specific, investable)\n'
        '- "reasoning": logic chain including valuation judgment where relevant (3-5 sentences). '
        "Show your work; cite themes/companies by name.\n"
        '- "evidence": 1-4 citations using ONLY IDs from the context catalog '
        '(document_id / narrative_id / theme_id + quote_snippet)\n\n'
        "Rules:\n"
        "- Do NOT invent opportunities just because a file says so.\n"
        "- Reject or downgrade crowded narratives that look fully priced.\n"
        "- Prefer actionable framing over generic macro platitudes.\n"
    )

    system = (
        "You are a rigorous investment analyst. Apply independent judgment; "
        "documents are inputs, not conclusions. Return valid JSON only."
    )

    try:
        data = _call_llm(system, consensus_prompt, max_tokens=4096)
    except Exception as e:
        logger.warning("Universe insights (consensus) LLM failed: %s", e)
        return False

    # Forward look: deliberately detached from file evidence
    forward_seed = {
        "as_of": dt.date.today().isoformat(),
        "analytics_signals": context["analytics"],
        "theme_labels_in_play": sorted(
            {n["theme_label"] for n in context["narratives"] if n.get("theme_label")}
        )[:25],
        "market_valuations": context["market_valuations"],
        "note": (
            "These labels are ONLY orientation. Do NOT cite documents, quotes, or "
            "restate research notes. Invent your own forward-looking logic."
        ),
    }
    forward_json = json.dumps(forward_seed, ensure_ascii=False, indent=2)
    forward_prompt = (
        "You are a forward-looking investment strategist writing speculative but LOGICAL "
        "trade ideas for the next 6–18 months.\n\n"
        "HOW TO THINK (multi-step, ahead of the crowd):\n"
        "- Start from what is already loud / crowded / early in a cycle TODAY.\n"
        "- Push the chain FORWARD: what becomes scarce, bottlenecked, over-owned, "
        "or mean-reverting AFTER the current phase — the next and next-next link "
        "in the value chain, capital cycle, or adoption curve — not the theme "
        "already on every slide deck.\n"
        "- Ask where the P&L and multiples actually migrate next (suppliers, enablers, "
        "substitutes, hedges, cleanup trades, late-cycle beneficiaries, post-peak fades).\n"
        "- Uncertainty is fine; the logic chain must be explicit. Do not chase being 'correct'.\n\n"
        "LANDING RULE (mandatory):\n"
        "- Every item MUST end on investable instruments: specific single-name tickers "
        "and/or liquid ETFs (US or major ADRs preferred). Theme-only ideas without tickers "
        "are invalid.\n"
        "- Prefer 1–4 concrete symbols per idea. Say WHY those names (not peers) capture "
        "the next phase.\n\n"
        "CRITICAL RULES:\n"
        "- Completely DETACH from research files. Do NOT quote, cite, or summarize documents.\n"
        "- evidence must be an empty array [].\n"
        "- No fixed count: output as many distinct ideas as you can defend logically "
        "(typically several; skip weak filler). Quality over padding — but do not "
        "artificially stop at 3.\n"
        "- Avoid vague sector platitudes. If the thesis is generic, drop it or sharpen "
        "to names.\n\n"
        f"ORIENTATION (not sources to cite):\n{forward_json}\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "forward_look": [ /* N items — as many as are logical */ ]\n'
        "}\n"
        "Each item must have:\n"
        '- "title": short headline that already hints at the investable angle\n'
        '- "kind": company | etf | theme  (prefer company/etf when landed on names)\n'
        '- "hypothesis": 1-3 sentences — the forward bet, naming the tickers\n'
        '- "reasoning": 4-7 sentences — the multi-step chain from today\'s setup → '
        "next phase → why THESE tickers/ETFs\n"
        '- "tickers": ["SYM1", "SYM2", ...]  // required, non-empty, real tradable symbols\n'
        '- "evidence": []\n'
    )

    forward_system = (
        "You invent coherent, multi-step forward investment hypotheses that land on "
        "specific tickers or ETFs. No document citations. Return valid JSON only."
    )

    forward_data: dict[str, Any] = {}
    try:
        forward_data = _call_llm(forward_system, forward_prompt, max_tokens=6144)
        if getattr(settings, "llm_delay_after_request_seconds", 0) > 0:
            time.sleep(settings.llm_delay_after_request_seconds)
    except Exception as e:
        logger.warning("Universe insights (forward look) LLM failed: %s", e)
        # Continue with consensus-only if forward fails

    payload = {
        "consensus": _parse_insight_items(
            data.get("consensus"), db, doc_ids, narr_ids, theme_ids, "opportunity",
            require_evidence=True,
            max_items=3,
        ),
        "non_consensus": _parse_insight_items(
            data.get("non_consensus"), db, doc_ids, narr_ids, theme_ids, "risk",
            require_evidence=True,
            max_items=3,
        ),
        "forward_look": _parse_insight_items(
            forward_data.get("forward_look") if forward_data else data.get("forward_look"),
            db,
            doc_ids,
            narr_ids,
            theme_ids,
            "company",
            require_evidence=False,
            max_items=15,
            require_tickers=True,
        ),
    }
    # Strip any accidental evidence from forward look
    for item in payload["forward_look"]:
        item["evidence"] = []

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
