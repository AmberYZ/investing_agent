"""
Theme/narrative extraction using simple LLM API (API key), with user-editable prompt.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from app.llm.provider import chat_completion
from app.settings import settings

logger = logging.getLogger("investing_agent.llm.api_extract")
from app.llm.vertex import (
    ExtractedDoc,
    ExtractedEvidence,
    ExtractedNarrative,
    ExtractedTheme,
)

# Extraction schema: themes + narratives with sub_theme, narrative_stance, confidence_level per narrative.
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "A concise 2-4 sentence summary of the document's key investment takeaways. Focus on the most important findings, data points, or conclusions an investor should know. Never return null."},
        "conclusions": {"type": "array", "items": {"type": "string"}},
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Core entity or topic name ONLY (e.g. 'BYD', 'Miniso', 'Gold'). Never append qualifiers—those go in sub_theme."},
                    "narratives": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "statement": {"type": "string"},
                                "sub_theme": {"type": "string", "description": "2-5 word label: either a reusable analytical lens (e.g. Demand outlook, Valuation) OR a named catalyst/entity (e.g. GENIUS Act, CHIPS Act, GPT-5). Prefer specificity."},
                                "narrative_stance": {"type": "string", "enum": ["bullish", "bearish", "mixed", "neutral"]},
                                "confidence_level": {"type": "string", "enum": ["fact", "opinion"]},
                                "evidence": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "quote": {"type": "string"},
                                            "page": {"type": ["integer", "null"]},
                                        },
                                        "required": ["quote", "page"],
                                    },
                                },
                            },
                            "required": ["statement", "sub_theme", "narrative_stance", "confidence_level", "evidence"],
                        },
                    },
                },
                "required": ["label", "narratives"],
            },
        },
    },
    "required": ["summary", "conclusions", "themes"],
}

_DEFAULT_SYSTEM = (
    "You are an analyst extracting market narratives from research.\n"
    "Return ONLY valid JSON. Do not include markdown.\n"
    "CRITICAL: Theme labels must be ONLY the core entity or topic name (e.g. 'BYD', 'Miniso', 'Gold', 'HBM / AI memory'). "
    "NEVER append qualifiers, strategies, or dimensions to the theme label—those go in sub_theme. "
    "Bad: 'BYD International sales'. Good: theme 'BYD', sub_theme 'International sales'.\n"
    "Sub-themes can be either reusable analytical lenses (e.g. 'Demand outlook', 'Valuation', 'Margins') "
    "OR named catalysts/entities (e.g. 'GENIUS Act', 'CHIPS Act', 'GPT-5') when the specific entity is central to the narrative. "
    "Prefer specificity—'GENIUS Act' is better than 'Regulation' if the narrative is specifically about that act.\n"
    "For each narrative provide sub_theme, narrative_stance (bullish/bearish/mixed/neutral), and confidence_level (fact/opinion).\n"
    "Be concise, but include direct quotes as evidence with page numbers when possible.\n"
)

# Paths relative to backend/app (or repo); prompt file can be overridden by user
_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
_USER_PROMPT_FILE = _PROMPT_DIR / "extract_themes.txt"
_DEFAULT_PROMPT_FILE = _PROMPT_DIR / "extract_themes_default.txt"
_MAX_DOC_CHARS = 120_000


def get_extraction_prompt_template() -> str:
    """Return the current user prompt template (editable by user)."""
    if _USER_PROMPT_FILE.exists():
        return _USER_PROMPT_FILE.read_text(encoding="utf-8").strip()
    return _DEFAULT_PROMPT_FILE.read_text(encoding="utf-8").strip()


def set_extraction_prompt_template(content: str) -> None:
    """Overwrite the user-editable prompt template."""
    _PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    _USER_PROMPT_FILE.write_text(content.strip(), encoding="utf-8")


# Retry up to 5 times with longer backoff so transient 503 (e.g. behind VPN) can succeed
@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=60))
def extract_themes_and_narratives(*, text: str) -> ExtractedDoc:
    """Call configured LLM with editable prompt and return structured extraction."""
    logger.info("Calling LLM provider=%s model=%s input_len=%d", settings.llm_provider, settings.llm_model, min(len(text), _MAX_DOC_CHARS))
    template = get_extraction_prompt_template()
    user_prompt = (
        template.replace("{{schema}}", json.dumps(EXTRACTION_SCHEMA))
        .replace("{{text}}", text[: _MAX_DOC_CHARS])
    )
    raw = chat_completion(system=_DEFAULT_SYSTEM, user=user_prompt, max_tokens=4096)
    # Strip markdown code block if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0].rstrip()
    try:
        data: dict[str, Any] = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        snippet = (raw.strip() or "(empty)")[:500]
        logger.error("LLM returned invalid JSON: %s. Raw snippet: %s", e, snippet)
        raise

    def _norm_stance(s: str) -> str:
        v = (s or "").strip().lower()
        if v in ("bullish", "bearish", "mixed", "neutral"):
            return v
        return "neutral"

    def _norm_confidence(s: str) -> str:
        v = (s or "").strip().lower()
        if v in ("fact", "opinion"):
            return v
        return "opinion"

    themes: list[ExtractedTheme] = []
    for t in data.get("themes", []):
        narratives: list[ExtractedNarrative] = []
        for n in t.get("narratives", []):
            evs = [ExtractedEvidence(quote=e.get("quote", ""), page=e.get("page")) for e in n.get("evidence", [])]
            narratives.append(
                ExtractedNarrative(
                    statement=n.get("statement", "").strip(),
                    stance="neutral",
                    relation_to_prevailing="consensus",
                    sub_theme=(n.get("sub_theme") or "").strip() or None,
                    narrative_stance=_norm_stance(n.get("narrative_stance") or ""),
                    confidence_level=_norm_confidence(n.get("confidence_level") or ""),
                    evidence=[e for e in evs if e.quote.strip()],
                )
            )
        themes.append(ExtractedTheme(label=t.get("label", "").strip(), narratives=[n for n in narratives if n.statement]))

    # Use the LLM-provided summary; fall back to conclusions or first narrative if the LLM returned null/empty.
    summary_text = (data.get("summary") or "").strip() or None
    if not summary_text:
        conclusions = [c for c in (data.get("conclusions") or []) if isinstance(c, str) and c.strip()]
        if conclusions:
            summary_text = " ".join(conclusions[:3])
        elif themes:
            # Grab the first few narrative statements as a best-effort summary
            stmts = [n.statement for t in themes for n in t.narratives if n.statement][:3]
            if stmts:
                summary_text = " ".join(stmts)

    return ExtractedDoc(
        summary=summary_text,
        conclusions=[c for c in (data.get("conclusions") or []) if isinstance(c, str) and c.strip()],
        themes=[t for t in themes if t.label],
    )
