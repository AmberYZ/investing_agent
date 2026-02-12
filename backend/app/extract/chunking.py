from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.extract.pdf_text import PageText


@dataclass(frozen=True)
class ChunkOut:
    chunk_index: int
    page_start: Optional[int]
    page_end: Optional[int]
    text: str


def chunk_pages(
    pages: list[PageText],
    *,
    max_chars: int = 1800,
    overlap_chars: int = 200,
) -> list[ChunkOut]:
    """
    Simple, robust chunker: concatenate page texts and split by char length.
    Keeps approximate page ranges by tracking boundaries.
    """
    chunks: list[ChunkOut] = []
    buf = ""
    buf_page_start: Optional[int] = None
    buf_page_end: Optional[int] = None
    idx = 0

    def flush():
        nonlocal buf, buf_page_start, buf_page_end, idx
        text = buf.strip()
        if not text:
            buf = ""
            buf_page_start = None
            buf_page_end = None
            return
        chunks.append(
            ChunkOut(
                chunk_index=idx,
                page_start=buf_page_start,
                page_end=buf_page_end,
                text=text,
            )
        )
        idx += 1
        # overlap
        buf = text[-overlap_chars:] if overlap_chars and len(text) > overlap_chars else ""
        buf_page_start = buf_page_end

    for p in pages:
        if buf_page_start is None:
            buf_page_start = p.page
        buf_page_end = p.page

        add = (p.text or "").strip()
        if not add:
            continue

        if len(buf) + len(add) + 2 > max_chars:
            flush()
        if buf:
            buf += "\n\n"
        buf += add

    flush()
    return chunks

