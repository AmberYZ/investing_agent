"""
Theme instruments: extract tickers from documents, LLM suggest.
"""
from __future__ import annotations

import json
import re
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Document, Evidence, Narrative, Theme, ThemeInstrument

logger = logging.getLogger("investing_agent.instruments")

# Simple ticker pattern: 2-5 uppercase letters, optionally prefixed with $
TICKER_PATTERN = re.compile(r"\$?([A-Z]{2,5})\b")


def extract_ticker_candidates_from_text(text: str) -> set[str]:
    """Return set of uppercase symbol candidates from text (no validation)."""
    if not text:
        return set()
    return set(m.group(1).upper() for m in TICKER_PATTERN.finditer(text))


def extract_instruments_from_theme_documents(db: Session, theme_id: int) -> list[ThemeInstrument]:
    """
    Scan evidence quotes for this theme for ticker-like symbols; add as from_documents.
    Returns list of newly created ThemeInstrument (already in db).
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
    found: set[str] = set()
    for (quote,) in rows:
        found |= extract_ticker_candidates_from_text(quote or "")
    to_add = [s for s in found if s and s not in existing]
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
        "You are a financial analyst. Given an investment theme, suggest 3-8 relevant US stock tickers or ETF symbols. "
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
