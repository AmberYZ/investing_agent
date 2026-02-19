from __future__ import annotations

import json
from concurrent import futures
from dataclasses import dataclass, field
from typing import Any, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.settings import settings


def _vertex_timeout_seconds() -> float:
    return float(max(30, getattr(settings, "llm_timeout_seconds", 180)))


@dataclass(frozen=True)
class ExtractedEvidence:
    quote: str
    page: Optional[int]


@dataclass(frozen=True)
class ExtractedNarrative:
    statement: str
    stance: str
    relation_to_prevailing: str  # consensus|contrarian|refinement|new_angle
    sub_theme: Optional[str] = None
    narrative_stance: str = "neutral"  # bullish|bearish|mixed|neutral
    confidence_level: str = "opinion"  # fact|opinion
    evidence: list[ExtractedEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractedTheme:
    label: str
    narratives: list[ExtractedNarrative]


@dataclass(frozen=True)
class ExtractedDoc:
    summary: Optional[str]
    conclusions: list[str]
    themes: list[ExtractedTheme]


def _vertex_init():
    import vertexai

    vertexai.init(project=settings.gcp_project, location=settings.gcp_location)


def _extract_themes_vertex_impl(text: str) -> ExtractedDoc:
    _vertex_init()
    from vertexai.generative_models import GenerativeModel

    model = GenerativeModel(settings.vertex_gemini_model)

    system = (
        "You are an analyst extracting market narratives from research.\n"
        "Return ONLY valid JSON. Do not include markdown.\n"
        "CRITICAL: Theme labels must be ONLY the core entity or topic name (e.g. 'BYD', 'Miniso', 'Gold', 'HBM / AI memory'). "
        "NEVER append qualifiers, strategies, or dimensions to the theme label—those go in sub_theme. "
        "Bad: 'BYD International sales'. Good: theme 'BYD', sub_theme 'International sales'.\n"
        "Sub-themes can be either reusable analytical lenses (e.g. 'Demand outlook', 'Valuation', 'Margins') "
        "OR named catalysts/entities (e.g. 'GENIUS Act', 'CHIPS Act', 'GPT-5') when the specific entity is central to the narrative. "
        "Prefer specificity—'GENIUS Act' is better than 'Regulation' if the narrative is specifically about that act.\n"
        "Include direct quotes per narrative as evidence when the document supports it; use the evidence array fully.\n"
    )

    schema = {
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
                                        "description": "Multiple direct quotes or key sentences from the document that support this narrative. Include 2-5 items when the document provides enough support; minimum 1.",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "quote": {"type": "string", "description": "Exact quote or key sentence from the document."},
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

    prompt = (
        "Extract themes, sub-themes, and narratives from the following document text.\n"
        "Theme: the core entity or topic name ONLY—short and canonical (e.g. 'BYD', 'Miniso', 'Gold', 'HBM / AI memory'). "
        "NEVER append qualifiers or dimensions to the theme label; put those in sub_theme.\n"
        "Sub-theme: 2-5 word label — either a reusable analytical lens (e.g. International sales, Growth strategy, Demand outlook, Valuation) OR a named catalyst/entity (e.g. GENIUS Act, CHIPS Act, GPT-5) when the specific entity is central to the narrative. Prefer specificity. "
        "Narrative: the claim or change through that lens. For each narrative provide sub_theme, narrative_stance (bullish/bearish/mixed/neutral), confidence_level (fact/opinion), and evidence (quotes with page).\n"
        "Output JSON following this JSON Schema:\n"
        f"{json.dumps(schema)}\n"
        "\n"
        "DOCUMENT TEXT:\n"
        f"{text[:getattr(settings, 'llm_extraction_max_chars', 120_000)]}\n"
    )

    max_out = settings.llm_extraction_max_tokens
    resp = model.generate_content(
        [system, prompt],
        generation_config={"temperature": 0.2, "max_output_tokens": max_out},
    )
    raw = (resp.text or "").strip()

    data: dict[str, Any] = json.loads(raw)

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
            stmts = [n.statement for t in themes for n in t.narratives if n.statement][:3]
            if stmts:
                summary_text = " ".join(stmts)

    return ExtractedDoc(
        summary=summary_text,
        conclusions=[c for c in (data.get("conclusions") or []) if isinstance(c, str) and c.strip()],
        themes=[t for t in themes if t.label],
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def extract_themes_and_narratives(*, text: str) -> ExtractedDoc:
    """
    Calls Gemini on Vertex AI and returns a structured extraction.
    Wrapped in a timeout so we fail after LLM_TIMEOUT_SECONDS instead of the client's 600s retry.
    """
    timeout = _vertex_timeout_seconds()
    with futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_extract_themes_vertex_impl, text)
        try:
            return future.result(timeout=timeout)
        except futures.TimeoutError:
            raise TimeoutError(
                f"Vertex AI request timed out after {timeout:.0f}s. "
                "Check network/firewall or set LLM_TIMEOUT_SECONDS. "
                "If you see 503/failed to connect, try Gemini API key (REST) instead of Vertex."
            ) from None


def _embed_texts_impl(texts: list[str]) -> list[list[float]]:
    _vertex_init()
    from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

    model = TextEmbeddingModel.from_pretrained(settings.vertex_embed_model)
    out: list[list[float]] = []
    for t in texts:
        inp = TextEmbeddingInput(t, "RETRIEVAL_DOCUMENT")
        emb = model.get_embeddings([inp])[0].values
        out.append(list(emb))
    return out


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def embed_texts(*, texts: list[str]) -> list[list[float]]:
    """Vertex embeddings; wrapped in timeout to avoid 600s gRPC retry on connection failure."""
    timeout = _vertex_timeout_seconds()
    with futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_embed_texts_impl, texts)
        try:
            return future.result(timeout=timeout)
        except futures.TimeoutError:
            raise TimeoutError(
                f"Vertex embeddings timed out after {timeout:.0f}s. "
                "Check network/firewall. If 503 persists, disable embeddings or use a different network."
            ) from None

