"""
Single embedding API used by theme resolution (worker) and theme merge.
Uses Vertex when enabled, otherwise OpenAI (no Vertex/GCP required).
"""
from __future__ import annotations

import logging
from typing import List

from app.settings import settings

logger = logging.getLogger("investing_agent.llm.embeddings")


def _use_vertex() -> bool:
    return (
        getattr(settings, "embedding_provider", "auto") == "vertex"
        or (
            getattr(settings, "embedding_provider", "auto") == "auto"
            and bool(settings.enable_vertex and settings.gcp_project)
        )
    )


def _use_openai() -> bool:
    if getattr(settings, "embedding_provider", "auto") == "none":
        return False
    if getattr(settings, "embedding_provider", "auto") == "openai":
        return bool(settings.llm_api_key)
    if getattr(settings, "embedding_provider", "auto") == "auto":
        # Use OpenAI embeddings only when Vertex is off and LLM is OpenAI (same key works).
        return bool(
            settings.llm_api_key
            and not (settings.enable_vertex and settings.gcp_project)
            and (settings.llm_provider or "openai").lower() == "openai"
        )
    return False


def is_embedding_available() -> bool:
    """True if any embedding backend is configured (Vertex or OpenAI)."""
    return _use_vertex() or _use_openai()


def embed_texts(*, texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts. Uses Vertex when embedding_provider is vertex (or auto with Vertex enabled),
    otherwise OpenAI when embedding_provider is openai (or auto with LLM_API_KEY and no Vertex).
    Returns list of embedding vectors; failed or unavailable backend returns empty vectors.
    """
    if not texts:
        return []
    if _use_vertex():
        try:
            from app.llm.vertex import embed_texts as vertex_embed
            return vertex_embed(texts=texts)
        except Exception as e:
            logger.warning("Vertex embedding failed: %s", e)
            return [[]] * len(texts)
    if _use_openai():
        try:
            return _openai_embed(texts)
        except Exception as e:
            logger.warning("OpenAI embedding failed: %s", e)
            return [[]] * len(texts)
    return [[]] * len(texts)


def _openai_embed(texts: list[str]) -> list[list[float]]:
    """OpenAI embeddings API (text-embedding-3-small). No Vertex required."""
    from openai import OpenAI

    model = getattr(settings, "embedding_model", "text-embedding-3-small") or "text-embedding-3-small"
    # Use official OpenAI API for embeddings (base_url=None); LLM_BASE_URL is for chat only.
    client = OpenAI(
        api_key=settings.llm_api_key,
        base_url=None,
        timeout=float(getattr(settings, "llm_timeout_seconds", 180)),
    )
    # OpenAI accepts batch of inputs; avoid oversized batches
    batch_size = 20
    out: List[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(input=batch, model=model)
        for item in resp.data:
            out.append(list(item.embedding))
    return out
