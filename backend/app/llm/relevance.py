from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.llm.provider import chat_completion
from app.settings import settings

logger = logging.getLogger("investing_agent.llm.relevance")


@dataclass(frozen=True)
class RelevanceDecision:
    is_investment_related: bool
    confidence: float
    reason: str
    source: str  # llm | heuristic


_POSITIVE_TERMS = (
    "equity", "stock", "stocks", "market", "markets", "valuation", "earnings", "guidance",
    "macro", "inflation", "interest rate", "bond", "credit", "forex", "fx", "commodity",
    "portfolio", "investment", "investor", "alpha", "semiconductor", "technology outlook",
    "research report", "price target", "pt", "buy rating", "sell rating", "revenue", "ebitda",
)
_NEGATIVE_TERMS = (
    "invitation", "renewal agreement", "employment", "job offer", "resume", "cv", "curriculum vitae",
    "lease", "rental", "wedding", "birthday", "invoice", "receipt", "tuition", "course",
    "homework", "assignment", "survey invitation", "nda", "service agreement", "travel itinerary",
)


def _clip_text(text: str, max_chars: int = 6000) -> str:
    return (text or "")[:max_chars]


def _term_hits(text: str, terms: tuple[str, ...]) -> int:
    low = text.lower()
    return sum(1 for t in terms if t in low)


def _heuristic_decision(filename: str, source_name: str, source_uri: str | None, text: str) -> RelevanceDecision:
    sample = " ".join(
        x for x in [
            filename or "",
            source_name or "",
            source_uri or "",
            _clip_text(text),
        ] if x
    )
    pos = _term_hits(sample, _POSITIVE_TERMS)
    neg = _term_hits(sample, _NEGATIVE_TERMS)

    # Conservative scoring: require a stronger negative signal to auto-exclude.
    raw = 0.5 + 0.12 * pos - 0.18 * neg
    conf = max(0.0, min(1.0, abs(raw - 0.5) * 2.0))
    is_inv = raw >= 0.45
    reason = f"heuristic score={raw:.2f}, positive_hits={pos}, negative_hits={neg}"
    return RelevanceDecision(is_investment_related=is_inv, confidence=conf, reason=reason, source="heuristic")


def _llm_decision(filename: str, source_name: str, source_uri: str | None, text: str) -> RelevanceDecision | None:
    if not settings.llm_api_key:
        return None
    system = (
        "You classify whether a document is related to investing/financial markets.\n"
        "Return ONLY JSON with keys: is_investment_related (bool), confidence (0..1), reason (string).\n"
        "Investment-related includes equity/credit/macro/industry/company research and market strategy.\n"
        "Not investment-related includes legal/admin/personal/event invitations/contracts unrelated to markets."
    )
    payload = {
        "filename": filename or "",
        "source_name": source_name or "",
        "source_uri": source_uri or "",
        "text_excerpt": _clip_text(text, max_chars=5000),
    }
    user = "Classify this document:\n" + json.dumps(payload, ensure_ascii=True)
    try:
        raw = chat_completion(system=system, user=user, max_tokens=180)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0].rstrip()
        data = json.loads(raw.strip())
        is_inv = bool(data.get("is_investment_related", True))
        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        reason = str(data.get("reason", "")).strip()[:240]
        if not reason:
            reason = "No reason returned by classifier."
        return RelevanceDecision(
            is_investment_related=is_inv,
            confidence=confidence,
            reason=reason,
            source="llm",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM relevance classification failed, falling back to heuristic: %s", e)
        return None


def classify_document_relevance(
    *,
    filename: str,
    source_name: str,
    source_uri: str | None,
    text: str,
) -> RelevanceDecision:
    if settings.auto_investment_relevance_filter_use_llm:
        llm = _llm_decision(
            filename=filename,
            source_name=source_name,
            source_uri=source_uri,
            text=text,
        )
        if llm is not None:
            return llm
    return _heuristic_decision(
        filename=filename,
        source_name=source_name,
        source_uri=source_uri,
        text=text,
    )


def should_skip_as_non_investment(decision: RelevanceDecision) -> bool:
    if decision.is_investment_related:
        return False
    # Conservative gate: only auto-skip high-confidence non-investment classifications.
    return decision.confidence >= settings.auto_investment_relevance_filter_min_confidence

