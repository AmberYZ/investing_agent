"""
Simple LLM API client for MVP: API-key–based providers (no Vertex required).
Supports: OpenAI, Gemini (Google AI), and any OpenAI-compatible endpoint (DeepSeek, Qwen, etc.).
"""
from __future__ import annotations

import logging
from concurrent import futures

from app.settings import settings

logger = logging.getLogger("investing_agent.llm.provider")


def _timeout_seconds() -> float:
    return float(max(10, getattr(settings, "llm_timeout_seconds", 180)))


def chat_completion(
    *,
    system: str,
    user: str,
    max_tokens: int = 2048,
    model: str | None = None,
) -> str:
    """
    Send system + user message to the configured LLM and return the assistant text.
    Uses LLM_API_KEY and LLM_PROVIDER / LLM_MODEL / LLM_BASE_URL from settings.
    Respects LLM_TIMEOUT_SECONDS (default 180) to avoid indefinite hangs.
    Pass model= to override the configured model for this call (e.g. for dry-run comparison).
    """
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY is not set")

    provider = (settings.llm_provider or "openai").lower().strip()
    model = (model or settings.llm_model or "gpt-4o-mini").strip()
    api_key = settings.llm_api_key
    base_url = (settings.llm_base_url or "").strip() or None
    timeout = _timeout_seconds()

    if provider == "gemini":
        return _gemini_chat(system=system, user=user, model=model, api_key=api_key, max_tokens=max_tokens, timeout=timeout)
    return _openai_compatible_chat(
        system=system,
        user=user,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def _openai_compatible_chat(
    *,
    system: str,
    user: str,
    model: str,
    api_key: str,
    base_url: str | None,
    max_tokens: int,
    timeout: float,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
    except Exception as e:
        err_msg = str(e).lower()
        if "503" in err_msg or "service unavailable" in err_msg:
            logger.error(
                "OpenAI-compatible API returned 503 (Service Unavailable). "
                "Often transient: retry later, or try without VPN / different VPN server. Full error: %s",
                e,
            )
        elif "timeout" in err_msg or "timed out" in err_msg:
            logger.error("OpenAI-compatible API timed out after %s seconds: %s", timeout, e)
        else:
            logger.error("OpenAI-compatible API error: %s", e, exc_info=True)
        raise
    choice = resp.choices[0] if resp.choices else None
    if not choice or not getattr(choice, "message", None):
        logger.error("OpenAI-compatible API returned empty/invalid response: choices=%s", getattr(resp, "choices", None))
        raise RuntimeError("Empty or invalid response from LLM")
    text = (choice.message.content or "").strip()
    logger.info("OpenAI-compatible response len=%d preview=%s", len(text), (text[:300] + "..." if len(text) > 300 else text))
    return text


def _gemini_chat(
    *,
    system: str,
    user: str,
    model: str,
    api_key: str,
    max_tokens: int,
    timeout: float,
) -> str:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    gm = genai.GenerativeModel(model)
    combined = f"{system}\n\n{user}" if system else user

    def _call():
        return gm.generate_content(
            combined,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=max_tokens,
            ),
        )

    try:
        with futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_call)
            resp = future.result(timeout=timeout)
    except futures.TimeoutError:
        logger.error("Gemini API timed out after %s seconds (increase LLM_TIMEOUT_SECONDS for long documents)", timeout)
        raise TimeoutError(
            f"Gemini request timed out after {timeout:.0f} seconds. "
            "Set LLM_TIMEOUT_SECONDS in .env to a higher value (e.g. 300) for long documents."
        ) from None
    except Exception as e:
        err_msg = str(e).lower()
        if "503" in err_msg or "service unavailable" in err_msg or "failed to connect" in err_msg:
            logger.error(
                "Gemini API 503 or connection failure (often transient or VPN-related). "
                "Suggestions: retry in a minute, try without QuickQ VPN or a different VPN server, "
                "or use LLM_PROVIDER=openai with an OpenAI key. Full error: %s",
                e,
                exc_info=True,
            )
        elif "timeout" in err_msg or "deadline" in err_msg or "timed out" in err_msg:
            logger.error("Gemini API timed out or deadline exceeded: %s", e)
        else:
            logger.error("Gemini API error: %s", e, exc_info=True)
        raise

    # Log full response details for debugging (Gemini often returns empty when blocked)
    def _gemini_resp_debug(r) -> str:
        parts = []
        if getattr(r, "prompt_feedback", None):
            pf = r.prompt_feedback
            parts.append(f"prompt_feedback={getattr(pf, 'block_reason', None)} {getattr(pf, 'block_reason_message', '') or ''}")
        if getattr(r, "candidates", None):
            for i, c in enumerate(r.candidates):
                finish = getattr(c, "finish_reason", None)
                content = getattr(c, "content", None)
                parts.append(f"candidate[{i}] finish_reason={finish} parts={len(getattr(content, 'parts', []) or [])}")
                if getattr(c, "safety_ratings", None):
                    parts.append(f" safety_ratings={c.safety_ratings}")
        if getattr(r, "text", None):
            parts.append(f"text_len={len(r.text)}")
        return " ".join(parts)

    logger.info("Gemini raw response: %s", _gemini_resp_debug(resp))

    if getattr(resp, "text", None) and resp.text.strip():
        text = resp.text.strip()
        logger.info("Gemini response len=%d preview=%s", len(text), (text[:300] + "..." if len(text) > 300 else text))
        return text

    # Empty or blocked: log everything we have so user can see why
    logger.error(
        "Gemini returned no text. Full debug: prompt_feedback=%s candidates=%s",
        getattr(resp, "prompt_feedback", None),
        getattr(resp, "candidates", None),
    )
    raise RuntimeError(
        "Empty or invalid response from Gemini. Check logs for prompt_feedback (block_reason) and candidates (finish_reason)."
    )
