from __future__ import annotations

import logging
from dataclasses import dataclass

import fitz  # PyMuPDF

logger = logging.getLogger("investing_agent.extract.pdf_text")


class PDFStructureError(Exception):
    """Raised when the PDF has invalid structure (e.g. corrupted or malformed page tree)."""


@dataclass(frozen=True)
class PageText:
    page: int
    text: str


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[list[PageText], int]:
    """
    Extract text from each page. Raises PDFStructureError on malformed PDFs
    (e.g. "non-page object in page tree") so the ingest job fails with a clear message.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        msg = str(e).strip()
        logger.error("PyMuPDF failed to open PDF: %s", msg, exc_info=True)
        if "page tree" in msg.lower() or "format error" in msg.lower() or "non-page" in msg.lower():
            raise PDFStructureError(
                f"PDF structure error: {msg}. The file may be corrupted or malformed (e.g. from a buggy export)."
            ) from e
        raise

    pages: list[PageText] = []
    try:
        for i in range(doc.page_count):
            try:
                page = doc.load_page(i)
                text = page.get_text("text") or ""
                pages.append(PageText(page=i + 1, text=text))
            except Exception as e:
                msg = str(e).strip()
                logger.error("PyMuPDF failed on page %s: %s", i + 1, msg, exc_info=True)
                if "page tree" in msg.lower() or "format error" in msg.lower() or "non-page" in msg.lower():
                    raise PDFStructureError(
                        f"PDF structure error on page {i + 1}: {msg}. The file may be corrupted or malformed."
                    ) from e
                raise
        return pages, doc.page_count
    finally:
        doc.close()

