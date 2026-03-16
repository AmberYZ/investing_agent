"""
Track items agent using EODHD APIs only.
Classifies user track item → selects EODHD API(s) → fetches → processes and formats update.
Progress callback: (api_name, action) for UI (e.g. "EODHD News", "Fetching for AAPL").
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Callable, Optional

from app.market_data import (
    fetch_fundamentals_filtered,
    fetch_news_for_ticker,
    fetch_quarterly_income_statement,
    get_earnings,
    get_earnings_estimates,
    get_latest_close,
)

logger = logging.getLogger("investing_agent.track_items_eodhd")

# EODHD data types we can fetch
EODHD_NEWS = "news"
EODHD_EARNINGS = "earnings"
EODHD_ANALYST_RATINGS = "analyst_ratings"
EODHD_VALUATION = "valuation"
EODHD_INSIDER = "insider_transactions"
EODHD_DIVIDENDS = "dividends"
EODHD_TECHNICALS = "technicals"  # 52w high/low, etc.
EODHD_HIGHLIGHTS = "highlights"  # PE, PEG, growth, margins

# Strategy for answering a track item
STRATEGY_TREND = "trend"  # e.g. profit margin trend → quarterly data + trend description
STRATEGY_SPECIFIC_FACT = "specific_fact"  # e.g. % revenue from AI → news/description + LLM or "can't find"
STRATEGY_SNAPSHOT = "snapshot"  # default: current news, earnings, highlights, etc.


def _classify_strategy(item: str) -> str:
    """
    Classify track item into trend, specific_fact, or snapshot.
    - trend: "trend", "over time", "margin trend", "profit margin trend", "growth trend"
    - specific_fact: "%", "revenue from", "percent of", "regulatory", "how much", "what %", "share of"
    - else: snapshot
    """
    item_lower = (item or "").strip().lower()
    if not item_lower:
        return STRATEGY_SNAPSHOT
    trend_keywords = ("trend", "over time", "margin trend", "profit margin trend", "growth trend", "quarter over quarter", "qoq", "yoy", "year over year")
    if any(k in item_lower for k in trend_keywords):
        return STRATEGY_TREND
    fact_keywords = ("%", "percent of", "revenue from", "share of revenue", "how much", "what percent", "what %", "regulatory", "specific number", "breakdown")
    if any(k in item_lower for k in fact_keywords):
        return STRATEGY_SPECIFIC_FACT
    return STRATEGY_SNAPSHOT


def _classify_track_item(item: str) -> list[str]:
    """
    Map user track item (natural language) to EODHD data types.
    Returns list of EODHD_* constants. Uses keyword matching; defaults to news + earnings + highlights.
    """
    item_lower = (item or "").strip().lower()
    if not item_lower:
        return [EODHD_NEWS, EODHD_HIGHLIGHTS, EODHD_EARNINGS]
    types: list[str] = []
    if any(k in item_lower for k in ("news", "headline", "announcement", "update")):
        types.append(EODHD_NEWS)
    if any(k in item_lower for k in ("earnings", "eps", "revenue", "quarter", "results", "report")):
        types.append(EODHD_EARNINGS)
    if any(k in item_lower for k in ("analyst", "rating", "target price", "price target")):
        types.append(EODHD_ANALYST_RATINGS)
    if any(k in item_lower for k in ("valuation", "pe", "p/e", "peg", "ev", "ebitda")):
        types.append(EODHD_VALUATION)
    if any(k in item_lower for k in ("insider", "form 4", "buy", "sell", "transaction")):
        types.append(EODHD_INSIDER)
    if any(k in item_lower for k in ("dividend", "yield", "payout")):
        types.append(EODHD_DIVIDENDS)
    if any(k in item_lower for k in ("52 week", "52w", "high", "low", "technical")):
        types.append(EODHD_TECHNICALS)
    if any(k in item_lower for k in ("growth", "margin", "profit", "revenue")):
        types.append(EODHD_HIGHLIGHTS)
    if not types:
        types = [EODHD_NEWS, EODHD_HIGHLIGHTS, EODHD_EARNINGS]
    return types


def _sections_for_types(types: list[str]) -> list[str]:
    """EODHD fundamentals filter sections for given types."""
    section_map = {
        EODHD_EARNINGS: "Earnings",
        EODHD_ANALYST_RATINGS: "AnalystRatings",
        EODHD_VALUATION: "Valuation",
        EODHD_INSIDER: "InsiderTransactions",
        EODHD_DIVIDENDS: "SplitsDividends",
        EODHD_TECHNICALS: "Technicals",
        EODHD_HIGHLIGHTS: "Highlights",
    }
    return list(dict.fromkeys(section_map[t] for t in types if t in section_map))


def _format_news_summary(items: list[dict]) -> str:
    """Summarize news with headlines and computed sentiment aggregation (EODHD sentiment per article)."""
    if not items:
        return "No recent news from EODHD."
    valid = [i for i in items[:10] if isinstance(i, dict) and i.get("title")]
    if not valid:
        return "No recent news from EODHD."
    headlines = [(i.get("title", "").strip() or "")[:100] for i in valid[:5]]
    pos = sum(1 for i in valid if (i.get("sentiment") or "").lower() == "positive")
    neg = sum(1 for i in valid if (i.get("sentiment") or "").lower() == "negative")
    neu = len(valid) - pos - neg
    neu = max(0, neu)
    parts = []
    if len(headlines) == 1:
        parts.append(f"Latest: {headlines[0]}{'…' if len(headlines[0]) >= 100 else ''}")
    else:
        parts.append("Recent: " + "; ".join(h[:70] + ("…" if len(h) > 70 else "") for h in headlines[:3]))
    if pos or neg or neu:
        overall = "positive" if pos > neg and pos > neu else ("negative" if neg > pos and neg > neu else "mixed")
        parts.append(f"Sentiment: {pos} pos, {neg} neg, {neu} neutral (overall: {overall}).")
    return " ".join(parts)


def _format_earnings_from_fundamentals(earnings: dict) -> str:
    """Format Earnings with computed T12, prior T12 growth %, and EPS trend (EODHD History)."""
    history = earnings.get("History") if isinstance(earnings.get("History"), dict) else {}
    if not history:
        return "No earnings history in EODHD."
    rows = []
    for fiscal_date, q in sorted(history.items(), reverse=True):
        if not isinstance(q, dict):
            continue
        report_date = (q.get("reportDate") or fiscal_date or "")[:10]
        eps = q.get("epsActual")
        if eps in (None, "", "-"):
            continue
        try:
            rows.append({"reportedDate": report_date, "reportedEPS": float(eps)})
        except (TypeError, ValueError):
            continue
    if not rows:
        return "No earnings history in EODHD for this symbol."
    latest = rows[0]
    t12 = sum(r["reportedEPS"] for r in rows[:4]) if len(rows) >= 4 else None
    t12_prior = sum(r["reportedEPS"] for r in rows[4:8]) if len(rows) >= 8 else None
    parts = [f"Latest {latest['reportedDate']}: EPS ${latest['reportedEPS']:.2f}"]
    if t12 is not None:
        parts.append(f"Trailing 12M EPS ${t12:.2f}")
    if t12_prior is not None and t12_prior != 0:
        growth_pct = round((t12 - t12_prior) / abs(t12_prior) * 100, 1)
        parts.append(f"T12 vs prior 4Q: {growth_pct:+.1f}%")
    if len(rows) >= 4:
        first2 = sum(r["reportedEPS"] for r in rows[2:4])
        last2 = sum(r["reportedEPS"] for r in rows[:2])
        if first2 != 0:
            trend = "improving" if last2 > first2 else ("declining" if last2 < first2 else "stable")
            parts.append(f"EPS trend (recent 2Q vs prior 2Q): {trend}.")
    return " ".join(parts)


def _format_analyst_ratings(data: dict) -> str:
    """Format AnalystRatings with consensus summary (EODHD counts)."""
    ar = data.get("AnalystRatings") if isinstance(data.get("AnalystRatings"), dict) else {}
    if not ar:
        return "No analyst ratings in EODHD."
    target = ar.get("TargetPrice")
    sb = int(ar.get("StrongBuy") or 0)
    b = int(ar.get("Buy") or 0)
    h = int(ar.get("Hold") or 0)
    s = int(ar.get("Sell") or 0)
    ss = int(ar.get("StrongSell") or 0)
    total = sb + b + h + s + ss
    parts = []
    if target is not None:
        try:
            parts.append(f"Target price ${float(target):.1f}")
        except (TypeError, ValueError):
            pass
    if total > 0:
        parts.append(f"Ratings: StrongBuy {sb}, Buy {b}, Hold {h}, Sell {s}, StrongSell {ss}")
        buy_side = sb + b
        sell_side = s + ss
        if buy_side > sell_side and buy_side > h:
            consensus = "Strong Buy" if sb >= b else "Buy"
        elif sell_side > buy_side and sell_side > h:
            consensus = "Strong Sell" if ss >= s else "Sell"
        else:
            consensus = "Hold"
        parts.append(f"Consensus: {consensus}.")
    return " ".join(parts) if parts else "No analyst ratings in EODHD."


def _format_valuation(data: dict) -> str:
    """Format Valuation with PEG-based interpretation (EODHD Valuation/Highlights)."""
    val = data.get("Valuation") if isinstance(data.get("Valuation"), dict) else {}
    hl = data.get("Highlights") if isinstance(data.get("Highlights"), dict) else {}
    parts = []
    for key, label in [
        ("ForwardPE", "Fwd P/E"),
        ("TrailingPE", "Trailing P/E"),
        ("PriceSalesTTM", "P/S"),
        ("EnterpriseValueEbitda", "EV/EBITDA"),
    ]:
        v = val.get(key) or hl.get("PERatio" if key == "TrailingPE" else None)
        if v is not None:
            try:
                parts.append(f"{label} {float(v):.2f}")
            except (TypeError, ValueError):
                pass
    peg = hl.get("PEGRatio")
    if peg is not None:
        try:
            peg_f = float(peg)
            parts.append(f"PEG {peg_f:.2f}")
        except (TypeError, ValueError):
            pass
    if not parts:
        return "No valuation data in EODHD for this symbol."
    out = "Valuation: " + ", ".join(parts)
    if peg is not None:
        try:
            peg_f = float(peg)
            if peg_f > 0 and peg_f < 1:
                out += " (growth at reasonable price)."
            elif peg_f > 2:
                out += " (expensive vs growth)."
            else:
                out += " (in line with growth)."
        except (TypeError, ValueError):
            pass
    return out


def _format_insider(transactions: list) -> str:
    """Format insider transactions with net direction (buys vs sells)."""
    if not transactions:
        return "No recent insider transactions in EODHD."
    lines = []
    buys = sells = 0
    for t in transactions[:10]:
        if not isinstance(t, dict):
            continue
        code = t.get("transactionCode") or ""
        acq = (t.get("transactionAcquiredDisposed") or "").upper()
        amt = t.get("transactionAmount")
        try:
            amt_int = int(amt) if amt not in (None, "", "-") else 0
        except (TypeError, ValueError):
            amt_int = 0
        is_buy = acq == "A" or str(code).upper() in ("P", "A", "G", "C")
        if is_buy:
            buys += amt_int
        else:
            sells += amt_int
        name = t.get("ownerName") or "Unknown"
        date = (t.get("date") or t.get("transactionDate") or "")[:10]
        price = t.get("transactionPrice")
        action = "Acquired" if is_buy else "Disposed"
        line = f"{date} {name}: {action}"
        if amt_int != 0:
            line += f" {amt_int} shares"
        if price is not None:
            try:
                line += f" @ ${float(price):.2f}"
            except (TypeError, ValueError):
                pass
        lines.append(line)
    if not lines:
        return "No recent insider transactions in EODHD."
    out = "; ".join(lines[:3])
    if buys or sells:
        net = "net buying" if buys > sells else ("net selling" if sells > buys else "balanced")
        out += f" ({net}: {buys} bought, {sells} sold)."
    return "Insider: " + out


def _format_dividends(data: dict) -> str:
    """Format SplitsDividends."""
    sd = data.get("SplitsDividends") if isinstance(data.get("SplitsDividends"), dict) else {}
    rate = sd.get("ForwardAnnualDividendRate")
    yield_ = sd.get("ForwardAnnualDividendYield")
    ex = sd.get("ExDividendDate")
    div_date = sd.get("DividendDate")
    parts = []
    if rate is not None:
        try:
            parts.append(f"Forward annual dividend ${float(rate):.2f}")
        except (TypeError, ValueError):
            pass
    if yield_ is not None:
        try:
            parts.append(f"yield {float(yield_) * 100:.2f}%")
        except (TypeError, ValueError):
            pass
    if ex:
        parts.append(f"Ex-div {str(ex)[:10]}")
    if div_date:
        parts.append(f"Pay date {str(div_date)[:10]}")
    if not parts:
        return "No dividend data in EODHD for this symbol."
    return "Dividends (EODHD): " + ", ".join(parts)


def _format_technicals(data: dict, symbol: Optional[str] = None) -> str:
    """Format Technicals with 52w range and, if symbol given, latest close and % of 52w range."""
    tech = data.get("Technicals") if isinstance(data.get("Technicals"), dict) else {}
    high = tech.get("52WeekHigh")
    low = tech.get("52WeekLow")
    if high is None and low is None:
        return "No 52-week high/low in EODHD for this symbol."
    try:
        high_f = float(high) if high not in (None, "", "-") else None
        low_f = float(low) if low not in (None, "", "-") else None
    except (TypeError, ValueError):
        high_f = low_f = None
    parts = []
    if high_f is not None:
        parts.append(f"52w high ${high_f:.2f}")
    if low_f is not None:
        parts.append(f"52w low ${low_f:.2f}")
    if symbol and high_f is not None and low_f is not None and high_f > low_f:
        latest = get_latest_close(symbol)
        close = latest.get("close")
        if close is not None and close > 0:
            pct_range = round((close - low_f) / (high_f - low_f) * 100, 0)
            parts.append(f"last close ${close:.2f} ({int(pct_range)}% of 52w range)")
    return "Technicals: " + ", ".join(parts)


def _format_highlights(data: dict) -> str:
    """Format Highlights with margin expansion/pressure interpretation (EODHD growth + margins)."""
    hl = data.get("Highlights") if isinstance(data.get("Highlights"), dict) else {}
    parts = []
    qeg_raw = hl.get("QuarterlyEarningsGrowthYOY")
    qrg_raw = hl.get("QuarterlyRevenueGrowthYOY")
    qeg = None
    qrg = None
    if qeg_raw is not None:
        try:
            qeg = float(qeg_raw) * 100 if abs(float(qeg_raw)) <= 2 else float(qeg_raw)
            parts.append(f"Q earnings growth YoY {qeg:.1f}%")
        except (TypeError, ValueError):
            pass
    if qrg_raw is not None:
        try:
            qrg = float(qrg_raw) * 100 if abs(float(qrg_raw)) <= 2 else float(qrg_raw)
            parts.append(f"Q revenue growth YoY {qrg:.1f}%")
        except (TypeError, ValueError):
            pass
    if qeg is not None and qrg is not None:
        if qeg > qrg + 5:
            parts.append("(earnings outpacing revenue → margin expansion)")
        elif qrg > qeg + 5:
            parts.append("(revenue outpacing earnings → margin pressure)")
    for key, label in [("ProfitMargin", "Profit margin"), ("OperatingMarginTTM", "Operating margin")]:
        v = hl.get(key)
        if v is not None:
            try:
                pct = float(v) * 100 if abs(float(v)) <= 2 else float(v)
                parts.append(f"{label} {pct:.1f}%")
            except (TypeError, ValueError):
                pass
    if not parts:
        return "No highlights in EODHD for this symbol."
    return "Highlights: " + ", ".join(parts)


def _process_trend(
    track_item: str,
    symbol: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> str:
    """
    Fetch quarterly income statement, compute profit margin per quarter, describe trend.
    Returns formatted string (e.g. "Q1 2024: 18%; Q2 2024: 19%; ... Trend: improving.").
    """
    if progress_callback:
        progress_callback("EODHD Financials", f"Fetching quarterly income for {symbol}")
    res = fetch_quarterly_income_statement(symbol)
    if res.get("message"):
        return f"Quarterly financials: {res['message']}"
    quarters = res.get("quarters") or []
    margin_quarters = [(q["date"], q.get("profit_margin_pct")) for q in quarters if q.get("profit_margin_pct") is not None]
    if not margin_quarters:
        return "No quarterly profit margin data in EODHD for this symbol (revenue/net income missing)."
    # Format as Q YYYY: X%
    parts = []
    for date_str, pct in margin_quarters[:8]:
        ymd = date_str.split("-")
        q_label = f"Q{(int(ymd[1]) - 1) // 3 + 1} {ymd[0]}" if len(ymd) >= 2 else date_str
        parts.append(f"{q_label}: {pct}%")
    trend_word = "stable"
    if len(margin_quarters) >= 2:
        # margin_quarters is newest-first; so recent[0] > recent[1] means improving over time
        recent = [p for _, p in margin_quarters[:4]]
        if all(a is not None and b is not None and a > b for a, b in zip(recent[:-1], recent[1:])):
            trend_word = "improving"
        elif all(a is not None and b is not None and a < b for a, b in zip(recent[:-1], recent[1:])):
            trend_word = "declining"
    return "Profit margin (quarterly): " + "; ".join(parts) + f". Trend: {trend_word}."


def _process_specific_fact(
    track_item: str,
    symbol: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    theme_narratives: Optional[str] = None,
) -> str:
    """
    Gather EODHD text (news, company description) and optional theme narratives; ask LLM to answer
    or say "I couldn't find this in the available EODHD data."
    """
    # Gather context: news + General (description) + theme narratives
    if progress_callback:
        progress_callback("EODHD News", f"Fetching news for {symbol}")
    news_res = fetch_news_for_ticker(symbol, limit=15)
    news_items = (news_res.get("items") or []) if not news_res.get("message") else []
    headlines = []
    for i in news_items:
        t = (i.get("title") or "").strip()
        if t:
            headlines.append(t)
        content = (i.get("content") or i.get("summary") or "").strip()
        if content and len(content) < 2000:
            headlines.append(content[:1500])
    news_text = "\n".join(headlines[:20]) if headlines else "No recent news."

    if progress_callback:
        progress_callback("EODHD Fundamentals", f"Fetching company description for {symbol}")
    fund = fetch_fundamentals_filtered(symbol, ["General"])
    data = fund.get("data") if not fund.get("message") else None
    general_text = ""
    if data and isinstance(data.get("General"), dict):
        g = data["General"]
        general_text = (g.get("Description") or g.get("description") or "").strip() or ""
    context_parts = []
    if (theme_narratives or "").strip():
        context_parts.append(f"Theme narratives (from ingested documents):\n{theme_narratives.strip()[:6000]}")
    context_parts.append(f"Company description (EODHD):\n{general_text[:8000]}\n\nRecent news / excerpts (EODHD):\n{news_text[:12000]}")
    context = "\n\n".join(context_parts)

    try:
        from app.llm.provider import chat_completion
        from app.settings import settings
    except ImportError:
        return "Answering specific questions (e.g. % of revenue from X) requires an LLM; not configured."
    if not getattr(settings, "llm_api_key", None):
        return "Answering specific questions requires LLM_API_KEY to be set."
    if progress_callback:
        progress_callback("LLM", "Searching for answer in EODHD data")
    system = (
        "You are a financial research assistant. You have (1) theme narratives from ingested documents and (2) EODHD-sourced text (company description and news). "
        "Answer the user's tracking question ONLY if you can find a direct answer or a close proxy in that text. "
        "If you cannot find any relevant information, reply with exactly: I couldn't find this in the available data. "
        "Keep your answer brief (1-3 sentences). Do not make up numbers or cite sources outside the given text."
    )
    user = f"Tracking question: {track_item}\n\n{context}"
    try:
        answer = chat_completion(system=system, user=user, max_tokens=400)
    except Exception as e:
        logger.warning("LLM specific_fact failed: %s", e)
        return f"Could not run LLM: {e}. EODHD text had company description and {len(headlines)} news items."
    answer = (answer or "").strip()
    if not answer:
        return "I couldn't find this in the available data."
    return answer[:1200]


def _llm_answer_track_question(
    track_item: str,
    symbol: str,
    eodhd_context: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    theme_narratives: Optional[str] = None,
) -> str:
    """
    Call LLM to answer the user's track question given EODHD context and optional theme narratives.
    Returns a short answer string, or empty string if LLM unavailable or on error.
    """
    try:
        from app.llm.provider import chat_completion
        from app.settings import settings
    except ImportError:
        return ""
    full_context = (eodhd_context or "").strip()
    if (theme_narratives or "").strip():
        full_context = f"Theme narratives (from ingested documents):\n{theme_narratives.strip()[:5000]}\n\nEODHD / market data:\n{full_context}"
    if not getattr(settings, "llm_api_key", None) or not full_context:
        return ""
    if progress_callback:
        progress_callback("LLM", "Answering tracked question")
    system = (
        "You are a concise financial research assistant. The user is tracking a question about a stock/symbol. "
        "Below is context: theme narratives (from ingested documents) and/or market data (EODHD: news, fundamentals, earnings). "
        "Answer the user's question in 1-3 short sentences based on this context. "
        "If the context does not contain enough to answer, say so briefly. Do not make up numbers or facts."
    )
    user = f"Symbol: {symbol}\n\nTracked question: {track_item}\n\nContext:\n{full_context[:10000]}"
    try:
        answer = chat_completion(system=system, user=user, max_tokens=350)
    except Exception as e:
        logger.warning("LLM track answer failed: %s", e)
        return ""
    answer = (answer or "").strip()
    return answer[:800] if answer else ""


def update_track_item_eodhd(
    track_item: str,
    symbol: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    theme_narratives: Optional[str] = None,
) -> str:
    """
    For one track item and one symbol: classify strategy → trend / specific_fact / snapshot.
    If theme_narratives is provided (narrative statements from this theme), LLM steps can use them to answer.
    """
    if not (symbol or "").strip():
        return "No symbol available for this theme (add a ticker to the theme)."
    symbol = (symbol or "").strip().upper()
    strategy = _classify_strategy(track_item)
    if strategy == STRATEGY_TREND:
        update = _process_trend(track_item, symbol, progress_callback)
        llm_answer = _llm_answer_track_question(track_item, symbol, update, progress_callback, theme_narratives=theme_narratives)
        return f"{update}\n\n{llm_answer}" if llm_answer else update
    if strategy == STRATEGY_SPECIFIC_FACT:
        return _process_specific_fact(track_item, symbol, progress_callback, theme_narratives=theme_narratives)
    # Snapshot: existing EODHD-only flow
    types = _classify_track_item(track_item)
    sections = _sections_for_types(types)
    parts: list[str] = []
    data: Optional[dict] = None

    # 1) News
    if EODHD_NEWS in types:
        if progress_callback:
            progress_callback("EODHD News", f"Fetching news for {symbol}")
        news_res = fetch_news_for_ticker(symbol, limit=8)
        if not news_res.get("message"):
            items = news_res.get("items") or []
            parts.append(_format_news_summary(items))
        else:
            parts.append(f"News: {news_res.get('message', 'Unavailable')}")

    # 2) Fundamentals (single request with filter for all sections we need)
    if sections:
        if progress_callback:
            progress_callback("EODHD Fundamentals", f"Fetching {', '.join(sections)} for {symbol}")
        fund = fetch_fundamentals_filtered(symbol, sections)
        raw = fund.get("data") if not fund.get("message") else None
        data = raw if isinstance(raw, dict) else None
        if fund.get("message") and not data:
            parts.append(f"Fundamentals: {fund.get('message', 'Unavailable')}")
        elif data:
            if EODHD_ANALYST_RATINGS in types:
                parts.append(_format_analyst_ratings(data))
            if EODHD_VALUATION in types:
                parts.append(_format_valuation(data))
            if EODHD_HIGHLIGHTS in types:
                parts.append(_format_highlights(data))
            if EODHD_INSIDER in types:
                ins = data.get("InsiderTransactions")
                tx_list = ins if isinstance(ins, list) else list(ins.values()) if isinstance(ins, dict) else []
                parts.append(_format_insider(tx_list))
            if EODHD_DIVIDENDS in types:
                parts.append(_format_dividends(data))
            if EODHD_TECHNICALS in types:
                parts.append(_format_technicals(data, symbol))

    # 3) Earnings: from fundamentals if we fetched Earnings section, else get_earnings
    if EODHD_EARNINGS in types:
        earnings_data = data.get("Earnings") if data and isinstance(data.get("Earnings"), dict) else None
        if earnings_data:
            parts.append(_format_earnings_from_fundamentals(earnings_data))
        else:
            if progress_callback:
                progress_callback("EODHD Earnings", f"Fetching earnings for {symbol}")
            earn = get_earnings(symbol)
            if not earn.get("message"):
                quarters = earn.get("quarterly_earnings") or []
                if quarters and isinstance(quarters[0], dict):
                    latest = quarters[0]
                    t12 = earn.get("trailing_12m_eps")
                    parts.append(
                        f"Latest reported {latest.get('reportedDate', '')}: EPS ${latest.get('reportedEPS', 0):.2f}"
                        + (f". Trailing 12M EPS ${t12:.2f}" if t12 is not None else "")
                    )
                else:
                    est = get_earnings_estimates(symbol)
                    next_fy = est.get("next_fy_eps_estimate")
                    if next_fy is not None:
                        parts.append(f"Next FY EPS estimate: ${next_fy:.2f} (EODHD).")
                    else:
                        parts.append("No earnings history in EODHD for this symbol.")
            else:
                parts.append(earn.get("message") or "Earnings unavailable.")

    if not parts:
        return "EODHD data could not be retrieved for this symbol. Check API key and symbol."
    eodhd_update = " ".join(parts)[:1500]
    llm_answer = _llm_answer_track_question(track_item, symbol, eodhd_update, progress_callback, theme_narratives=theme_narratives)
    return f"{eodhd_update}\n\n{llm_answer}" if llm_answer else eodhd_update


def update_theme_track_items_eodhd(
    theme_label: str,
    track_items: list[str],
    primary_symbol: Optional[str],
    progress_callback: Optional[Callable[[str, str, Optional[str]], None]] = None,
    theme_narratives: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Update all track items for a theme using EODHD only.
    progress_callback(api_name, action, theme_label) for UI.
    Returns list of {"item": str, "update": str, "last_checked": str}.
    """
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    results: list[dict[str, Any]] = []
    symbol = (primary_symbol or "").strip().upper() or None
    if not symbol:
        for item in track_items:
            results.append({
                "item": item,
                "update": "No ticker for this theme. Add an instrument (e.g. AAPL) to the theme to get EODHD updates.",
                "last_checked": now_iso,
            })
        return results

    def cb(api_name: str, action: str) -> None:
        if progress_callback:
            progress_callback(api_name, action, theme_label)

    for item in track_items:
        item = (item or "").strip()
        if not item:
            continue
        try:
            update = update_track_item_eodhd(item, symbol, progress_callback=cb, theme_narratives=theme_narratives)
        except Exception as e:
            logger.warning("EODHD track update failed for %r: %s", item, e)
            update = f"Update failed: {e}"
        results.append({"item": item, "update": update, "last_checked": now_iso})
    return results
