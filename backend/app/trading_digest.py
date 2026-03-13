"""
Generate trading-oriented digest for themes (prevailing, what changed, worries, trade ideas).
Consumes recent narratives + primary ticker metrics; stores in ThemeTradingDigestCache.
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
    ThemeMarketSnapshot,
    ThemeTradingDigestCache,
    InstrumentMarketSnapshot,
)
from app.settings import settings

logger = logging.getLogger("investing_agent.trading_digest")


def _doc_date():
    return func.date(func.coalesce(Document.modified_at, Document.received_at))


def _theme_primary_symbol(db: Session, theme_id: int) -> str | None:
    row = (
        db.query(ThemeInstrument.symbol)
        .filter(ThemeInstrument.theme_id == theme_id)
        .order_by(ThemeInstrument.symbol)
        .first()
    )
    return row[0] if row else None


def _theme_instruments_all(db: Session, theme_id: int) -> list[str]:
    """All instrument symbols for this theme (for per-symbol trade ideas)."""
    rows = (
        db.query(ThemeInstrument.symbol)
        .filter(ThemeInstrument.theme_id == theme_id)
        .order_by(ThemeInstrument.symbol)
        .all()
    )
    return [r[0] for r in rows if r[0]]


def _get_cached_metrics_for_theme(db: Session, theme_id: int) -> dict[str, Any] | None:
    """Read metrics from daily cache (theme_market_snapshot). Returns None if not cached."""
    today = dt.date.today()
    row = (
        db.query(ThemeMarketSnapshot)
        .filter(
            ThemeMarketSnapshot.theme_id == theme_id,
            ThemeMarketSnapshot.snapshot_date == today,
        )
        .one_or_none()
    )
    if not row or not row.metrics_json:
        return None
    try:
        return json.loads(row.metrics_json)
    except Exception:
        return None


def _basket_metrics_for_symbol(primary_symbol: str) -> dict[str, Any]:
    """Fetch basket-style metrics for one symbol (for LLM context)."""
    from app.market_data import compute_period_returns, get_prices_and_valuation

    out: dict[str, Any] = {
        "forward_pe": None,
        "peg_ratio": None,
        "latest_rsi": None,
        "pct_1m": None,
        "pct_3m": None,
        "pct_ytd": None,
        "pct_6m": None,
        "quarterly_earnings_growth_yoy": None,
        "quarterly_revenue_growth_yoy": None,
        "analyst_target_price": None,
        "analyst_strong_buy": None,
        "analyst_buy": None,
        "analyst_hold": None,
        "analyst_sell": None,
        "analyst_strong_sell": None,
        "eps_growth_0y_pct": None,
        "eps_growth_1y_pct": None,
        "price_sales_ttm": None,
        "price_book_mrq": None,
        "enterprise_value_ebitda": None,
        "week_52_high": None,
        "week_52_low": None,
        "return_on_equity_ttm": None,
        "operating_margin_ttm": None,
        "profit_margin": None,
        "trailing_12m_eps": None,
    }
    try:
        data = get_prices_and_valuation(primary_symbol, months=6)
        prices = data.get("prices") or []
        if prices:
            returns = compute_period_returns(prices)
            out["pct_1m"] = returns.get("pct_1m")
            out["pct_3m"] = returns.get("pct_3m")
            out["pct_ytd"] = returns.get("pct_ytd")
            out["pct_6m"] = returns.get("pct_6m")
            last_bar = prices[-1]
            if isinstance(last_bar.get("rsi_14"), (int, float)):
                out["latest_rsi"] = round(float(last_bar["rsi_14"]), 2)
        out["forward_pe"] = data.get("forward_pe")
        out["peg_ratio"] = data.get("peg_ratio")
        out["quarterly_earnings_growth_yoy"] = data.get("quarterly_earnings_growth_yoy")
        out["quarterly_revenue_growth_yoy"] = data.get("quarterly_revenue_growth_yoy")
        out["analyst_target_price"] = data.get("analyst_target_price")
        out["analyst_strong_buy"] = data.get("analyst_strong_buy")
        out["analyst_buy"] = data.get("analyst_buy")
        out["analyst_hold"] = data.get("analyst_hold")
        out["analyst_sell"] = data.get("analyst_sell")
        out["analyst_strong_sell"] = data.get("analyst_strong_sell")
        out["eps_growth_0y_pct"] = data.get("eps_growth_0y_pct")
        out["eps_growth_1y_pct"] = data.get("eps_growth_1y_pct")
        out["price_sales_ttm"] = data.get("price_sales_ttm")
        out["price_book_mrq"] = data.get("price_book_mrq")
        out["enterprise_value_ebitda"] = data.get("enterprise_value_ebitda")
        out["week_52_high"] = data.get("week_52_high")
        out["week_52_low"] = data.get("week_52_low")
        out["return_on_equity_ttm"] = data.get("return_on_equity_ttm")
        out["operating_margin_ttm"] = data.get("operating_margin_ttm")
        out["profit_margin"] = data.get("profit_margin")
        out["trailing_12m_eps"] = data.get("trailing_12m_eps")
    except Exception as e:
        logger.debug("Metrics fetch for %s failed: %s", primary_symbol, e)
    return out


def populate_daily_market_cache(db: Session, theme_ids: list[int]) -> int:
    """
    Fetch market metrics for each theme's primary symbol and store in ThemeMarketSnapshot for today.
    Call from daily job so trading digest generation uses cache only (no live API on refresh).
    Returns count of themes updated.
    """
    today = dt.date.today()
    count = 0
    for theme_id in theme_ids:
        primary_symbol = _theme_primary_symbol(db, theme_id)
        if not primary_symbol:
            continue
        metrics = _basket_metrics_for_symbol(primary_symbol)
        metrics_json = json.dumps(metrics)
        existing = (
            db.query(ThemeMarketSnapshot)
            .filter(
                ThemeMarketSnapshot.theme_id == theme_id,
                ThemeMarketSnapshot.snapshot_date == today,
            )
            .one_or_none()
        )
        if existing:
            existing.metrics_json = metrics_json
        else:
            db.add(
                ThemeMarketSnapshot(
                    theme_id=theme_id,
                    snapshot_date=today,
                    metrics_json=metrics_json,
                )
            )
        count += 1
        if getattr(settings, "llm_delay_after_request_seconds", 0) > 0:
            time.sleep(0.5)  # light throttle between AV calls
    db.commit()
    return count


def _instrument_metrics_for_symbol(symbol: str) -> dict[str, Any]:
    """Fetch full instrument-row metrics for one symbol (last_close, pct_*, forward_pe, etc.) for DB cache."""
    from app.market_data import compute_period_returns, get_prices_and_valuation

    out: dict[str, Any] = {
        "last_close": None,
        "forward_pe": None,
        "peg_ratio": None,
        "latest_rsi": None,
        "pct_1m": None,
        "pct_3m": None,
        "pct_ytd": None,
        "quarterly_earnings_growth_yoy": None,
        "quarterly_revenue_growth_yoy": None,
        "analyst_target_price": None,
        "analyst_strong_buy": None,
        "analyst_buy": None,
        "analyst_hold": None,
        "analyst_sell": None,
        "analyst_strong_sell": None,
        "eps_growth_0y_pct": None,
        "eps_growth_1y_pct": None,
        "price_sales_ttm": None,
        "price_book_mrq": None,
        "enterprise_value_ebitda": None,
        "week_52_high": None,
        "week_52_low": None,
        "return_on_equity_ttm": None,
        "operating_margin_ttm": None,
        "profit_margin": None,
        "trailing_12m_eps": None,
    }
    try:
        data = get_prices_and_valuation(symbol, months=6)
        prices = data.get("prices") or []
        if prices:
            returns = compute_period_returns(prices)
            out["pct_1m"] = returns.get("pct_1m")
            out["pct_3m"] = returns.get("pct_3m")
            out["pct_ytd"] = returns.get("pct_ytd")
            last_bar = prices[-1]
            if last_bar.get("close") is not None:
                out["last_close"] = round(float(last_bar["close"]), 4)
            if isinstance(last_bar.get("rsi_14"), (int, float)):
                out["latest_rsi"] = round(float(last_bar["rsi_14"]), 2)
        out["forward_pe"] = data.get("forward_pe")
        out["peg_ratio"] = data.get("peg_ratio")
        out["quarterly_earnings_growth_yoy"] = data.get("quarterly_earnings_growth_yoy")
        out["quarterly_revenue_growth_yoy"] = data.get("quarterly_revenue_growth_yoy")
        out["analyst_target_price"] = data.get("analyst_target_price")
        out["analyst_strong_buy"] = data.get("analyst_strong_buy")
        out["analyst_buy"] = data.get("analyst_buy")
        out["analyst_hold"] = data.get("analyst_hold")
        out["analyst_sell"] = data.get("analyst_sell")
        out["analyst_strong_sell"] = data.get("analyst_strong_sell")
        out["eps_growth_0y_pct"] = data.get("eps_growth_0y_pct")
        out["eps_growth_1y_pct"] = data.get("eps_growth_1y_pct")
        out["price_sales_ttm"] = data.get("price_sales_ttm")
        out["price_book_mrq"] = data.get("price_book_mrq")
        out["enterprise_value_ebitda"] = data.get("enterprise_value_ebitda")
        out["week_52_high"] = data.get("week_52_high")
        out["week_52_low"] = data.get("week_52_low")
        out["return_on_equity_ttm"] = data.get("return_on_equity_ttm")
        out["operating_margin_ttm"] = data.get("operating_margin_ttm")
        out["profit_margin"] = data.get("profit_margin")
        out["trailing_12m_eps"] = data.get("trailing_12m_eps")
    except Exception as e:
        logger.debug("Instrument metrics fetch for %s failed: %s", symbol, e)
    return out


def populate_instrument_market_cache(db: Session, symbols: list[str]) -> int:
    """
    Fetch market metrics for each symbol and store in InstrumentMarketSnapshot for today.
    Call from daily job so basket ticker rows use DB cache only (no live API, survives restart).
    Returns count of symbols updated.
    """
    today = dt.date.today()
    count = 0
    for symbol in symbols:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            continue
        metrics = _instrument_metrics_for_symbol(symbol)
        metrics_json = json.dumps(metrics)
        existing = (
            db.query(InstrumentMarketSnapshot)
            .filter(
                InstrumentMarketSnapshot.symbol == symbol,
                InstrumentMarketSnapshot.snapshot_date == today,
            )
            .one_or_none()
        )
        if existing:
            existing.metrics_json = metrics_json
            existing.updated_at = dt.datetime.now(dt.timezone.utc)
        else:
            db.add(
                InstrumentMarketSnapshot(
                    symbol=symbol,
                    snapshot_date=today,
                    metrics_json=metrics_json,
                )
            )
        count += 1
        if getattr(settings, "llm_delay_after_request_seconds", 0) > 0:
            time.sleep(0.5)
    db.commit()
    return count


def generate_theme_trading_digests(
    db: Session,
    theme_id: Optional[int] = None,
    theme_ids: Optional[list[int]] = None,
) -> int:
    """
    Generate LLM trading digest for themes (prevailing, what_changed, what_market_waiting, worries, trade_ideas).
    Uses recent narratives (30d) and optional primary ticker metrics. Writes to ThemeTradingDigestCache.
    Returns count of digests generated.
    When theme_id is set, process only that theme. When theme_ids is set, process only those themes. Otherwise all themes.
    """
    if not settings.llm_api_key:
        logger.info("Skipping trading digest (no LLM_API_KEY)")
        return 0

    q = db.query(Theme)
    if theme_id is not None:
        q = q.filter(Theme.id == theme_id)
    elif theme_ids:
        q = q.filter(Theme.id.in_(theme_ids))
    themes = q.all()

    since = dt.date.today() - dt.timedelta(days=30)
    doc_date = _doc_date()
    count = 0

    for theme in themes:
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

        narrative_lines = []
        for n in recent_narratives[:30]:
            stance = n.narrative_stance or "unknown"
            conf = n.confidence_level or "unknown"
            sub = n.sub_theme or "general"
            narrative_lines.append(
                f"- [{stance}, {conf}, sub-theme: {sub}] {n.statement}"
            )

        primary_symbol = _theme_primary_symbol(db, theme.id)
        instruments = _theme_instruments_all(db, theme.id)
        metrics = _get_cached_metrics_for_theme(db, theme.id)
        metrics_str = "No cached metrics (run daily job to populate)."
        if metrics:
            parts = [f"Primary ticker: {primary_symbol or 'N/A'}"]
            if metrics.get("forward_pe") is not None:
                parts.append(f"Forward P/E: {metrics['forward_pe']}")
            if metrics.get("peg_ratio") is not None:
                parts.append(f"PEG: {metrics['peg_ratio']}")
            if metrics.get("pct_1m") is not None:
                parts.append(f"1M return: {metrics['pct_1m']}%")
            if metrics.get("pct_3m") is not None:
                parts.append(f"3M return: {metrics['pct_3m']}%")
            if metrics.get("latest_rsi") is not None:
                parts.append(f"RSI: {metrics['latest_rsi']}")
            if metrics.get("eps_growth_0y_pct") is not None:
                parts.append(f"EPS growth 0y %: {metrics['eps_growth_0y_pct']}")
            if metrics.get("eps_growth_1y_pct") is not None:
                parts.append(f"EPS growth +1y %: {metrics['eps_growth_1y_pct']}")
            metrics_str = "; ".join(parts)
        if instruments:
            metrics_str += f"\nInstruments in the user's list for this theme (give ideas per symbol when multiple): {', '.join(instruments)}"

        user_prompt = (
            f"Theme: {theme.canonical_label}\n"
            f"Description: {theme.description or 'N/A'}\n\n"
            f"Market context: {metrics_str}\n\n"
            f"Narratives from the past 30 days:\n"
            + "\n".join(narrative_lines)
            + "\n\n"
            "You are producing a trading-oriented digest. Return ONLY a valid JSON object (no markdown, no code fence) with these keys:\n"
            "- prevailing (string): What are the main themes or topics talked about under this basket? 2-4 sentences.\n"
            "- what_changed (string): What has changed recently? New developments, tone shifts. 2-3 sentences.\n"
            "- what_market_waiting (string): What is the market waiting to see? Catalysts, results, risks, or conditions that would make it more bearish or bullish. 2-3 sentences.\n"
            "- worries (string or null): What are people worrying about, if anything? One or two sentences, or null if not relevant.\n"
            "- trade_ideas (array): 0 to 5 actionable trade ideas when they exist. Each item: {\"symbol\": \"TICKER or null if theme-level\", \"label\": \"short tag\", \"rationale\": \"precise actionable description\"}. "
            "If the best course of action is not to trade (e.g. wait, no edge, too much uncertainty), return an empty array; do not force ideas. "
            "When the theme has multiple instruments in the user's list, prefer at least one idea per relevant symbol where it makes sense; do not give vague basket-level ideas when symbols are listed. "
            "You may suggest companies or tickers that are NOT in the user's list if your reasoning identifies a clear opportunity (e.g. related names, sector peers, substitutes, better risk/reward elsewhere); include them with their symbol. "
            "Ideas can include: buy/sell shares, buy dips, sell puts or calls, cash-secured puts, covered calls, spreads, momentum plays, mean reversion, take profits, wait for catalyst. "
            "Be precise so an execution agent could act: e.g. \"BUY 100 shares AAPL if price < 165\", \"SELL cash-secured put AAPL 160 strike 30 DTE\", \"Take profits on 50% above 180\". "
            "Return valid JSON only."
        )

        system = (
            "You are a senior investment analyst producing a trading digest. Return valid JSON only, no commentary."
        )

        try:
            from app.llm.provider import chat_completion

            model = getattr(settings, "llm_trading_digest_model", None) or settings.llm_model
            raw = chat_completion(system=system, user=user_prompt, max_tokens=2048, model=model)
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0].rstrip()
            data = json.loads(raw.strip())

            prevailing = (data.get("prevailing") or "").strip() or None
            what_changed = (data.get("what_changed") or "").strip() or None
            what_market_waiting = (data.get("what_market_waiting") or "").strip() or None
            worries = data.get("worries")
            worries = (worries or "").strip() or None if isinstance(worries, str) else None

            trade_ideas_raw = data.get("trade_ideas")
            if isinstance(trade_ideas_raw, list):
                ideas = []
                for item in trade_ideas_raw:
                    if isinstance(item, dict) and item.get("rationale"):
                        ideas.append({
                            "symbol": (item.get("symbol") or "").strip() or None,
                            "label": (item.get("label") or "").strip() or None,
                            "rationale": str(item.get("rationale", "")).strip(),
                        })
                    elif isinstance(item, str) and item.strip():
                        ideas.append({"symbol": None, "label": None, "rationale": item.strip()})
                trade_ideas_json = json.dumps(ideas) if ideas else None
            else:
                trade_ideas_json = None

            if not any([prevailing, what_changed, what_market_waiting, worries, trade_ideas_json]):
                continue
        except Exception as e:
            logger.warning("Trading digest LLM failed for theme %s: %s", theme.id, e)
            continue

        now = dt.datetime.now(dt.timezone.utc)
        existing = (
            db.query(ThemeTradingDigestCache)
            .filter(
                ThemeTradingDigestCache.theme_id == theme.id,
                ThemeTradingDigestCache.period == "30d",
            )
            .one_or_none()
        )
        if existing:
            existing.prevailing = prevailing
            existing.what_changed = what_changed
            existing.what_market_waiting = what_market_waiting
            existing.worries = worries
            existing.trade_ideas = trade_ideas_json
            existing.generated_at = now
        else:
            db.add(
                ThemeTradingDigestCache(
                    theme_id=theme.id,
                    period="30d",
                    prevailing=prevailing,
                    what_changed=what_changed,
                    what_market_waiting=what_market_waiting,
                    worries=worries,
                    trade_ideas=trade_ideas_json,
                    generated_at=now,
                )
            )
        db.flush()
        count += 1
        logger.info("Generated trading digest for theme %s (%s)", theme.id, theme.canonical_label)

        if getattr(settings, "llm_delay_after_request_seconds", 0) > 0:
            time.sleep(settings.llm_delay_after_request_seconds)

    db.commit()
    return count
