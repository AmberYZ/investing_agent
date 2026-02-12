"""
Strip disclosure, disclaimer, and legal boilerplate from document text before sending to LLM.
Saves tokens and reduces noise. Looks for common section headers and trims from there;
optionally trims a fraction of the end if no header is found.
"""
from __future__ import annotations

import re

# Headings that typically start disclosure/legal/irrelevant sections (case-insensitive).
# We trim from the first occurrence of such a section (on a line by itself or after newline).
_DISCLOSURE_HEADINGS = [
    r"\bdisclosure\s*(?:s?\s*$|:)",
    r"\bdisclaimer\s*(?:s?\s*$|:)",
    r"\bimportant\s+disclosure",
    r"\bimportant\s+disclaimer",
    r"\blegal\s+disclaimer",
    r"\brisk\s+factors\b",
    r"\bforward[- ]?looking\s+statements?\b",
    r"\bregulatory\s+disclosure",
    r"\bconfidential\s+and\s+proprietary",
    r"\bgeneral\s+disclaimer",
    r"\bno\s+representation\s+or\s+warranty",
    r"\bthis\s+document\s+is\s+for\s+informational\s+purposes\s+only",
    r"\bnot\s+investment\s+advice",
    r"\bsee\s+full\s+disclosure",
    r"\bdisclosures?\s*$",
    r"\bdisclaimers?\s*$",
    r"\bend\s+of\s+(?:report|document)\b",
    r"^\s*-{3,}\s*$",  # line of dashes often before legal
    # Irrelevant / boilerplate sections
    r"\bconflict\s+of\s+interest\s*(?:s?\s*$|:)",
    r"\bconflicts?\s+of\s+interest\b",
    r"\babout\s+the\s+(?:author|analyst|firm)\b",
    r"\bcompany\s+disclosure\b",
    r"\bdistribution\s+disclosure\b",
    r"\bcertification\s+(?:of\s+)?(?:disclosure|independence)\b",
    r"\bregulatory\s+certification\b",
]
_PATTERN = re.compile(
    "|".join(f"(?:{p})" for p in _DISCLOSURE_HEADINGS),
    re.IGNORECASE | re.MULTILINE,
)

# Max fraction of document to keep if we trim from the end (when no heading found)
_MAX_END_FRACTION = 0.85


def trim_disclosure_sections(full_text: str, *, trim_tail_fraction: float | None = _MAX_END_FRACTION) -> str:
    """
    Remove disclosure/disclaimer sections from the end of document text.
    - Tries to find a disclosure-style heading and truncates at that point.
    - If no such heading is found, optionally truncates the last (1 - trim_tail_fraction)
      of the text, since many PDFs put boilerplate in the last 10–20% of pages.
    """
    if not full_text or not full_text.strip():
        return full_text

    text = full_text
    # Search for disclosure heading (prefer earlier match = keep more content if multiple)
    match = _PATTERN.search(text)
    if match:
        start = match.start()
        # Only trim if the disclosure heading is in the latter half of the doc (avoid cutting main content)
        if start >= len(text) * 0.5:
            cut = text.rfind("\n\n", 0, start)
            if cut > len(text) * 0.3:
                text = text[:cut].rstrip()
            else:
                text = text[:start].rstrip()
        return text if text else full_text

    # No heading found: optionally trim last portion (disclosures often at end)
    if trim_tail_fraction is not None and trim_tail_fraction < 1.0:
        keep_len = int(len(text) * trim_tail_fraction)
        if keep_len < len(text) and keep_len > 1000:
            # Cut at paragraph boundary
            cut = text.rfind("\n\n", 0, keep_len + 500)
            if cut > len(text) * 0.5:
                text = text[:cut].rstrip()
    return text
