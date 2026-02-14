"""
Theme instruments: extract tickers from documents, LLM suggest.
"""
from __future__ import annotations

import json
import re
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Evidence, Narrative, Theme, ThemeInstrument

logger = logging.getLogger("investing_agent.instruments")

# Ticker-like: 2-5 uppercase letters, optionally prefixed with $ (e.g. $AAPL, NVDA)
TICKER_PATTERN = re.compile(r"\$?([A-Z]{2,5})\b")

# Common acronyms that match ticker pattern but are not stock tickers (economics, orgs, terms).
# Avoid 2-letter that are valid tickers (GE, BP, etc.). Include clear non-tickers only.
KNOWN_NON_TICKERS = frozenset({
    "AI", "EU", "UK", "US", "USA", "CEO", "CFO", "IPO", "SEC", "FDA", "ETF", "ETFs",
    "GDP", "CPI", "PPI", "PCE", "FOMC", "YOY", "QOQ", "EPS", "EBITDA", "ROE", "ROI",
    "NAV", "AUM", "NYSE", "NASDAQ", "ESG", "API", "USB", "FAQ", "PDF", "URL", "HTML",
    "HTTP", "SSL", "TLS", "VPN", "CRM", "ERP", "SaaS", "B2B", "B2C", "OTC", "REIT",
    "SPAC", "YTD", "MTD", "QTD", "FY", "TTM", "LTM", "NTM", "PCF", "DCF", "NPV",
    "IRR", "ROIC", "WACC", "CAPM", "ETN", "FOMC", "IR", "HR", "PR", "VP", "R&D",
})


def _normalize_candidate(s: str) -> str:
    return (s or "").strip().upper()


def extract_ticker_candidates_from_text(text: str) -> set[str]:
    """Return set of uppercase symbol candidates from text, excluding known non-tickers."""
    if not text:
        return set()
    candidates = set()
    for m in TICKER_PATTERN.finditer(text):
        sym = _normalize_candidate(m.group(1))
        if not sym or len(sym) < 2:
            continue
        if sym in KNOWN_NON_TICKERS:
            continue
        candidates.add(sym)
    return candidates


def _extract_tickers_from_quotes_llm(quotes_text: str, theme_label: str) -> list[dict]:
    """
    Use LLM to extract stock/ETF tickers and company names from evidence quotes.
    Resolves company names to ticker symbols. Returns list of {symbol, display_name?, type}.
    """
    if not (quotes_text or "").strip():
        return []
    try:
        from app.llm.provider import chat_completion
        from app.settings import settings
    except Exception as e:
        logger.warning("LLM not available for quote extraction: %s", e)
        return []
    if not getattr(settings, "llm_api_key", None):
        return []
    system = (
        "You are a financial analyst. Given excerpts from documents about an investment theme, "
        "list every stock ticker or ETF symbol mentioned. If only a company name is mentioned (e.g. Apple, NVIDIA), "
        "provide the correct ticker symbol (AAPL, NVDA). Ignore economic indicators (GDP, CPI), organizations (SEC, FDA), "
        "and generic acronyms (CEO, IPO, ESG). Return ONLY a JSON array of objects with: symbol (required), display_name (optional), type (stock or etf). "
        "Example: [{\"symbol\": \"AAPL\", \"display_name\": \"Apple\", \"type\": \"stock\"}, {\"symbol\": \"SOXX\", \"type\": \"etf\"}]"
    )
    user = f"Theme: {theme_label}\n\nExcerpts:\n{quotes_text[:12000]}\n\nReturn only the JSON array of tickers/symbols mentioned."
    try:
        raw = chat_completion(system=system, user=user, max_tokens=1024)
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        arr = json.loads(text)
        if not isinstance(arr, list):
            return []
        out = []
        seen = set()
        for item in arr:
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            sym = _normalize_candidate(str(item["symbol"]))[:32]
            if not sym or sym in KNOWN_NON_TICKERS or sym in seen:
                continue
            seen.add(sym)
            out.append({
                "symbol": sym,
                "display_name": str(item["display_name"]).strip()[:256] if item.get("display_name") else None,
                "type": "etf" if (item.get("type") or "").lower() == "etf" else "stock",
            })
        return out[:30]
    except Exception as e:
        logger.warning("LLM quote ticker extraction failed: %s", e)
        return []


def suggest_instruments_from_documents(db: Session, theme_id: int) -> list[dict]:
    """
    Scan theme evidence for ticker/company mentions and return suggested instruments (no DB write).
    Uses regex + blocklist and optional LLM to resolve company names to tickers.
    Returns list of {symbol, display_name?, type} excluding instruments already on the theme.
    """
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        return []
    existing = {r.symbol.upper() for r in db.query(ThemeInstrument.symbol).filter(ThemeInstrument.theme_id == theme_id).all()}
    rows = (
        db.query(Evidence.quote)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .filter(Narrative.theme_id == theme_id)
        .distinct()
        .all()
    )
    quotes = [q for (q,) in rows if q]
    found_symbols: set[str] = set()
    for quote in quotes:
        found_symbols |= extract_ticker_candidates_from_text(quote or "")
    suggestions_by_symbol: dict[str, dict] = {}
    for s in sorted(found_symbols):
        if s in existing:
            continue
        suggestions_by_symbol[s] = {"symbol": s, "display_name": None, "type": "stock"}
    if quotes:
        combined = "\n---\n".join(q for q in quotes if q)[:15000]
        llm_items = _extract_tickers_from_quotes_llm(combined, theme.canonical_label or "")
        for item in llm_items:
            sym = item["symbol"]
            if sym in existing:
                continue
            suggestions_by_symbol[sym] = {
                "symbol": sym,
                "display_name": item.get("display_name"),
                "type": item.get("type") or "stock",
            }
    return list(suggestions_by_symbol.values())[:30]


def add_instruments_from_documents(db: Session, theme_id: int, symbols: list[str]) -> list[ThemeInstrument]:
    """
    Add specific symbols as theme instruments with source=from_documents.
    Only adds symbols not already on the theme. Returns newly created ThemeInstrument rows.
    """
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        return []
    existing = {r.symbol.upper() for r in db.query(ThemeInstrument.symbol).filter(ThemeInstrument.theme_id == theme_id).all()}
    to_add = [s for s in (s.strip().upper() for s in symbols if s) if s not in existing and s not in KNOWN_NON_TICKERS]
    created = []
    for symbol in to_add:
        inst = ThemeInstrument(
            theme_id=theme_id,
            symbol=symbol,
            display_name=None,
            type="stock",
            source="from_documents",
        )
        db.add(inst)
        db.flush()
        created.append(inst)
    db.commit()
    for inst in created:
        db.refresh(inst)
    return created


def extract_instruments_from_theme_documents(db: Session, theme_id: int) -> list[ThemeInstrument]:
    """
    Scan evidence quotes for this theme for ticker-like symbols; add as from_documents.
    Prefer suggest_instruments_from_documents + add_instruments_from_documents so users can choose.
    """
    suggested = suggest_instruments_from_documents(db, theme_id)
    symbols = [s["symbol"] for s in suggested]
    return add_instruments_from_documents(db, theme_id, symbols)


def suggest_instruments_llm(theme_label: str, theme_description: Optional[str] = None) -> list[dict]:
    """
    Use LLM to suggest relevant tickers/ETFs for a theme. Returns list of {symbol, display_name?, type}.
    """
    try:
        from app.llm.provider import chat_completion
        from app.settings import settings
    except Exception as e:
        logger.warning("LLM not available for instrument suggestion: %s", e)
        return []
    if not getattr(settings, "llm_api_key", None):
        return []
    system = (
        "You are a financial analyst. Given an investment theme, suggest relevant stock tickers or ETF symbols. "
        "Return ONLY a JSON array of objects, each with keys: symbol (string, required), display_name (string, optional), type (string: stock or etf). "
        "Example: [{\"symbol\": \"NVDA\", \"display_name\": \"NVIDIA\", \"type\": \"stock\"}, {\"symbol\": \"SOXX\", \"display_name\": \"iShares Semiconductor ETF\", \"type\": \"etf\"}]"
    )
    user = f"Theme: {theme_label}"
    if theme_description:
        user += f"\nDescription: {theme_description}"
    user += "\nReturn only the JSON array, no other text."
    try:
        raw = chat_completion(system=system, user=user, max_tokens=512)
        # Strip markdown code block if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        arr = json.loads(text)
        if not isinstance(arr, list):
            return []
        out = []
        for item in arr:
            if isinstance(item, dict) and item.get("symbol"):
                out.append({
                    "symbol": str(item["symbol"]).strip().upper()[:32],
                    "display_name": str(item["display_name"]).strip()[:256] if item.get("display_name") else None,
                    "type": "etf" if (item.get("type") or "").lower() == "etf" else "stock",
                })
        return out[:15]
    except Exception as e:
        logger.warning("LLM instrument suggestion failed: %s", e)
        return []
