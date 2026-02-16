"""Extract plain text from HTML (e.g. Substack email body)."""

from __future__ import annotations

from bs4 import BeautifulSoup


def html_to_plain_text(html_bytes: bytes) -> str:
    """
    Decode HTML bytes as UTF-8 and extract plain text using BeautifulSoup.
    Suitable for email/Substack HTML bodies.
    """
    text = html_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator="\n", strip=True)
