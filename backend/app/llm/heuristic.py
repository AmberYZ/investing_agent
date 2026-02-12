from __future__ import annotations

import re
from collections import Counter

from app.llm.vertex import ExtractedDoc, ExtractedEvidence, ExtractedNarrative, ExtractedTheme


_STOP = {
    "the",
    "and",
    "to",
    "of",
    "in",
    "a",
    "for",
    "is",
    "on",
    "that",
    "with",
    "as",
    "are",
    "be",
    "by",
    "we",
    "it",
    "this",
    "from",
    "or",
    "an",
    "at",
    "can",
    "will",
    "may",
    "not",
    "more",
    "than",
    "our",
    "their",
    "these",
    "those",
}


def heuristic_extract(*, text: str, max_themes: int = 8) -> ExtractedDoc:
    """
    Offline fallback when Vertex AI isn't configured.
    Produces reasonable placeholders so the pipeline works end-to-end.
    """
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_\\-]{2,}", text)]
    words = [w for w in words if w not in _STOP]
    top = [w for w, _ in Counter(words).most_common(max_themes)]

    # Crude sentence split (requires .!? followed by space). If none, use whole text for summary.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences and text.strip():
        sentences = [text.strip()]

    themes: list[ExtractedTheme] = []
    for w in top:
        ev_sent = next((s for s in sentences if w in s.lower()), None)
        narrative = ExtractedNarrative(
            statement=f"Document discusses {w}.",
            stance="neutral",
            relation_to_prevailing="consensus",
            evidence=[ExtractedEvidence(quote=ev_sent or "", page=None)] if ev_sent else [],
        )
        themes.append(ExtractedTheme(label=w, narratives=[narrative]))

    summary = sentences[0][:400].strip() if sentences else None
    return ExtractedDoc(summary=summary, conclusions=[], themes=themes)

