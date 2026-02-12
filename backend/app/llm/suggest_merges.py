"""
LLM-based suggestion of theme merge groups: which theme labels refer to the same investment theme.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from app.llm.provider import chat_completion
from app.settings import settings

logger = logging.getLogger("investing_agent.llm.suggest_merges")

_SYSTEM = (
    "You are an analyst. Given a list of investment theme labels, identify which labels refer to the same investment thesis or topic. "
    "Group labels that are: the same theme (event- or period-specific vs enduring, e.g. 'Novo 2q25 results' and 'Novo nordisk obesity drug pipeline'); "
    "a development or angle of a core theme (e.g. 'China economic slowdown' and 'china economy'); synonyms or rephrasing (e.g. 'RMB appreciation' and 'yuan strength'); "
    "or the same entity (e.g. 'Novo Nordisk' and 'Novo'). "
    "Do NOT group labels that are distinct investment theses (e.g. 'China internet' and 'China economy' must stay in separate groups). "
    "Return ONLY valid JSON. Do not include markdown.\n"
    "Output format: {\"groups\": [[\"label1\", \"label2\"], [\"label3\"], ...]} "
    "Each inner array is a set of labels that describe the same theme. "
    "Put each label in at most one group. Single-label groups are allowed for themes with no duplicates."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    },
    "required": ["groups"],
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def suggest_theme_merge_groups(labels: list[str]) -> list[list[str]]:
    """
    Ask the LLM to group theme labels that refer to the same theme.
    Returns list of groups; each group is a list of label strings.
    """
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY is not set; cannot run suggest-merges")
    if not labels:
        return []
    # Limit token usage
    max_labels = 200
    if len(labels) > max_labels:
        labels = labels[:max_labels]
    user = (
        "Here are investment theme labels extracted from research. "
        "Which refer to the same theme? Return JSON with \"groups\": array of arrays of labels.\n\n"
        "Labels:\n"
        + "\n".join(f"- {lb}" for lb in labels)
    )
    raw = chat_completion(system=_SYSTEM, user=user, max_tokens=4096)
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0].rstrip()
    try:
        data: dict[str, Any] = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        logger.error("LLM suggest-merges returned invalid JSON: %s", e)
        raise
    groups = data.get("groups") or []
    if not isinstance(groups, list):
        return []
    out: list[list[str]] = []
    for g in groups:
        if isinstance(g, list) and g:
            out.append([str(x).strip() for x in g if str(x).strip()])
    return out
