from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from prometheus_client import Counter, Histogram

from app.db import SessionLocal, engine, init_db
from app.extract.chunking import chunk_pages
from app.extract.disclosure_trim import trim_disclosure_sections
from app.extract.pdf_text import extract_text_from_pdf
from app.llm.api_extract import extract_themes_and_narratives as extract_via_llm_api
from app.llm.heuristic import heuristic_extract
from app.llm.embeddings import embed_texts, is_embedding_available
from app.llm.vertex import extract_themes_and_narratives as extract_via_vertex
from app.logging_config import setup_logging
from app.models import (
    Base,
    Chunk,
    Document,
    Evidence,
    IngestJob,
    Narrative,
    Theme,
    ThemeAlias,
    ThemeMergeReinforcement,
)
from app.storage.gcs import get_storage
from app.settings import settings


logger = logging.getLogger("investing_agent.worker")

# ---------------------------------------------------------------------------
# LLM concurrency limiter: a semaphore that caps how many threads can call the
# LLM API simultaneously, preventing rate-limit errors (429 / 503).
# Initialised lazily on first use so that settings are fully loaded.
# ---------------------------------------------------------------------------
_llm_semaphore: threading.Semaphore | None = None


def _get_llm_semaphore() -> threading.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = threading.Semaphore(max(1, settings.llm_max_concurrent_requests))
    return _llm_semaphore

JOB_PROCESSED = Counter(
    "invest_agent_ingest_jobs_processed_total",
    "Ingest jobs processed",
    ["status"],
)
JOB_DURATION = Histogram(
    "invest_agent_ingest_job_duration_seconds",
    "Ingest job duration in seconds",
)


def canonicalize_label(label: str) -> str:
    return " ".join(label.strip().lower().split())


def _apply_llm_delay_after_request() -> None:
    """Optional delay after each LLM/Vertex extraction to avoid rate limits (e.g. OpenAI RPM)."""
    delay = getattr(settings, "llm_delay_after_request_seconds", 0.0) or 0.0
    if delay <= 0:
        return
    logger.info("Rate-limit delay: sleeping %.1fs (LLM_DELAY_AFTER_REQUEST_SECONDS)", delay)
    time.sleep(delay)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# Tokenize into words (lowercase, letters/digits only) for text similarity when Vertex is not used.
_TOKENIZE_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _token_set(label: str) -> frozenset[str]:
    """Return set of word tokens from label, lowercased."""
    return frozenset(_TOKENIZE_RE.findall(label.lower()))


def _dice_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Dice coefficient: 2 * |A ∩ B| / (|A| + |B|). Returns 0 if both empty."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return 2.0 * inter / (len(a) + len(b))


def _find_similar_theme_by_text(
    db: Session, label: str, threshold: float | None = None
) -> Theme | None:
    """Pure-Python text similarity (token Dice): find an existing theme with similar label. No Vertex required."""
    if not settings.theme_similarity_use_text:
        return None
    thr = threshold if threshold is not None else settings.theme_similarity_text_threshold
    query_tokens = _token_set(label)
    if not query_tokens:
        return None
    themes = db.query(Theme).all()
    if not themes:
        return None
    best_theme: Theme | None = None
    best_sim = thr
    for t in themes:
        other_tokens = _token_set(t.canonical_label)
        if not other_tokens:
            continue
        sim = _dice_similarity(query_tokens, other_tokens)
        if sim > best_sim:
            best_sim = sim
            best_theme = t
    return best_theme


def ensure_alias(db: Session, theme_id: int, label: str, created_by: str = "system", confidence: float | None = 1.0) -> None:
    """Add theme alias if not already present (alias stored in canonical form for lookup)."""
    canon = canonicalize_label(label)
    existing = (
        db.query(ThemeAlias)
        .filter(ThemeAlias.theme_id == theme_id, ThemeAlias.alias == canon)
        .one_or_none()
    )
    if existing is None:
        db.add(
            ThemeAlias(theme_id=theme_id, alias=canon, created_by=created_by, confidence=confidence)
        )
        db.flush()


def _find_theme_by_alias(db: Session, canon: str) -> Theme | None:
    """Return theme that has this canonical string as an alias, or None."""
    row = (
        db.query(ThemeAlias.theme_id)
        .filter(ThemeAlias.alias == canon)
        .first()
    )
    if row is None:
        return None
    return db.query(Theme).filter(Theme.id == row.theme_id).one()


def _find_theme_by_merge_reinforcement(db: Session, label: str) -> Theme | None:
    """
    Use prior user-approved merges to resolve a new label:
    - Exact match on stored source_label (canonicalised)
    - Otherwise, embedding similarity against stored source_embedding (if available)
    """
    if not getattr(settings, "theme_merge_reinforcement_enabled", False):
        return None

    canon = canonicalize_label(label)

    # 1) Exact match on source_label
    row = (
        db.query(ThemeMergeReinforcement.target_theme_id)
        .filter(ThemeMergeReinforcement.source_label == canon)
        .order_by(ThemeMergeReinforcement.created_at.desc())
        .first()
    )
    if row is not None:
        theme = db.query(Theme).filter(Theme.id == row[0]).one_or_none()
        if theme is not None:
            return theme

    # 2) Embedding-based match against stored source_embedding (optional)
    if not is_embedding_available():
        return None
    reinfs = (
        db.query(ThemeMergeReinforcement)
        .filter(ThemeMergeReinforcement.source_embedding.isnot(None))
        .all()
    )
    if not reinfs:
        return None

    try:
        embs = embed_texts(texts=[label])
    except Exception as e:  # noqa: BLE001
        logger.warning("Theme reinforcement embedding failed for label %s: %s", label, e)
        return None
    if not embs or not embs[0]:
        return None

    query_emb = embs[0]
    thr = getattr(settings, "theme_merge_reinforcement_threshold", 0.8)
    best_theme_id: int | None = None
    best_sim = thr
    for r in reinfs:
        sim = _cosine_similarity(query_emb, r.source_embedding or [])
        if sim > best_sim:
            best_sim = sim
            best_theme_id = r.target_theme_id

    if best_theme_id is None:
        return None
    return db.query(Theme).filter(Theme.id == best_theme_id).one_or_none()


def _find_similar_theme_by_embedding(
    db: Session, label: str, threshold: float | None = None
) -> Theme | None:
    """If embeddings are enabled (Vertex or OpenAI) and use_embedding is on, embed label and return an existing theme with high similarity, else None."""
    if not settings.theme_similarity_use_embedding:
        return None
    if not is_embedding_available():
        return None
    themes_with_emb = db.query(Theme).filter(Theme.embedding.isnot(None)).all()
    if not themes_with_emb:
        return None
    try:
        embs = embed_texts(texts=[label])
    except Exception as e:
        logger.warning("Theme embedding for similarity check failed: %s", e)
        return None
    if not embs or not embs[0]:
        return None
    thr = threshold if threshold is not None else settings.theme_similarity_embedding_threshold
    query_emb = embs[0]
    best_theme: Theme | None = None
    best_sim = thr
    for t in themes_with_emb:
        if not t.embedding:
            continue
        sim = _cosine_similarity(query_emb, t.embedding)
        if sim > best_sim:
            best_sim = sim
            best_theme = t
    return best_theme


def _find_similar_theme(db: Session, label: str) -> Theme | None:
    """Try embedding similarity (if enabled and Vertex available), then text (token Dice) similarity if enabled. Returns best match or None."""
    t = _find_similar_theme_by_embedding(db, label)
    if t is not None:
        return t
    return _find_similar_theme_by_text(db, label)


def resolve_theme(db: Session, label: str) -> Theme:
    """
    Resolve a theme label to an existing theme or create a new one.
    - Match by canonical_label first, then by ThemeAlias.
    - If embedding is enabled, try semantic similarity; if above threshold, use that theme and add alias.
    - Otherwise create new theme, optionally store embedding, and add alias if label differs from canon.
    """
    canon = canonicalize_label(label)
    # 1) By canonical label
    t = db.query(Theme).filter(Theme.canonical_label == canon).one_or_none()
    if t is not None:
        return t
    # 2) By alias
    t = _find_theme_by_alias(db, canon)
    if t is not None:
        ensure_alias(db, t.id, label, created_by="system", confidence=1.0)
        return t
    # 3) By merge reinforcement: honour prior user-approved merges
    t = _find_theme_by_merge_reinforcement(db, label)
    if t is not None:
        # High confidence: user explicitly indicated these labels refer to the same theme.
        ensure_alias(db, t.id, label, created_by="system", confidence=0.98)
        return t
    # 4) By similarity: embedding (if available) then token-based text similarity (always)
    t = _find_similar_theme(db, label)
    if t is not None:
        ensure_alias(db, t.id, label, created_by="system", confidence=0.95)
        return t
    # 4.5) Substring: if any theme's label is substring of canon or vice versa, use the shorter (broader) theme
    all_themes = db.query(Theme).all()
    substring_matches = [
        ot for ot in all_themes
        if (ot.canonical_label in canon or canon in ot.canonical_label)
        and ot.canonical_label != canon
    ]
    if substring_matches:
        broader = min(substring_matches, key=lambda x: len(x.canonical_label))
        ensure_alias(db, broader.id, label, created_by="system", confidence=0.9)
        return broader
    # 4) Create new theme
    t = Theme(canonical_label=canon)
    db.add(t)
    db.flush()
    # Store embedding for future similarity checks (Vertex or OpenAI)
    if is_embedding_available():
        try:
            embs = embed_texts(texts=[canon])
            if embs and embs[0]:
                t.embedding = embs[0]
                db.flush()
        except Exception as e:
            logger.warning("Failed to store theme embedding for new theme %s: %s", canon, e)
    return t


def upsert_narrative(
    db: Session,
    *,
    theme_id: int,
    statement: str,
    stance: str = "unlabeled",
    relation_to_prevailing: str = "unlabeled",
    sub_theme: str | None = None,
    narrative_stance: str | None = None,
    confidence_level: str | None = None,
) -> Narrative:
    """Create or update narrative. Persists sub_theme, narrative_stance, confidence_level from LLM when provided."""
    stmt = statement.strip()
    n = db.query(Narrative).filter(Narrative.theme_id == theme_id, Narrative.statement == stmt).one_or_none()
    now = dt.datetime.now(dt.timezone.utc)
    if n is None:
        n = Narrative(
            theme_id=theme_id,
            statement=stmt,
            relation_to_prevailing="unlabeled",
            created_at=now,
            first_seen=now,
            last_seen=now,
            sub_theme=sub_theme[:128] if sub_theme else None,
            narrative_stance=narrative_stance[:16] if narrative_stance else None,
            confidence_level=confidence_level[:16] if confidence_level else None,
        )
        db.add(n)
        db.flush()
    else:
        n.last_seen = now
        if sub_theme is not None:
            n.sub_theme = sub_theme[:128] if sub_theme else None
        if narrative_stance is not None:
            n.narrative_stance = narrative_stance[:16]
        if confidence_level is not None:
            n.confidence_level = confidence_level[:16]
    return n


def process_job(db: Session, job: IngestJob) -> None:
    storage = get_storage()
    doc = db.query(Document).filter(Document.id == job.document_id).one()

    job.status = "processing"
    job.started_at = dt.datetime.now(dt.timezone.utc)
    job.error_message = None
    db.commit()
    logger.info("Starting ingest job %s for document %s", job.id, doc.id)

    try:
        with JOB_DURATION.time():
            _process_job_inner(db, job, doc, storage)
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error_message = str(e)
        job.finished_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
        JOB_PROCESSED.labels(status="error").inc()
        logger.exception("Failed ingest job %s for document %s: %s", job.id, doc.id, e)
        # Do not re-raise: record the failure and let the worker continue to the next job.
    else:
        JOB_PROCESSED.labels(status="success").inc()
        logger.info("Completed ingest job %s for document %s", job.id, doc.id)


def _process_job_inner(db: Session, job: IngestJob, doc: Document, storage) -> None:
    logger.info("job_id=%s doc_id=%s filename=%s: downloading PDF", job.id, doc.id, doc.filename)
    pdf_bytes = storage.download_bytes(uri=doc.gcs_raw_uri)
    pages, num_pages = extract_text_from_pdf(pdf_bytes)
    doc.num_pages = num_pages
    logger.info("job_id=%s doc_id=%s: extracted text from %s pages", job.id, doc.id, num_pages)

    # Persist extracted full text artifact (for debugging + future reprocessing)
    full_text = "\n\n".join([f"[Page {p.page}]\n{p.text}".strip() for p in pages if p.text.strip()])
    len_full = len(full_text)
    # Strip disclosure/legal sections before LLM to save tokens
    text_for_llm = trim_disclosure_sections(full_text)
    len_llm = len(text_for_llm)
    if len_llm < len_full:
        logger.info("job_id=%s doc_id=%s: disclosure trim %d -> %d chars", job.id, doc.id, len_full, len_llm)
    text_obj = storage.upload_bytes(
        key=f"text/{doc.id}.txt",
        data=full_text.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )
    doc.gcs_text_uri = text_obj.uri

    chunks = chunk_pages(pages)
    db.query(Chunk).filter(Chunk.document_id == doc.id).delete()
    db.commit()

    chunk_rows: list[Chunk] = []
    for c in chunks:
        chunk_rows.append(
            Chunk(
                document_id=doc.id,
                chunk_index=c.chunk_index,
                page_start=c.page_start,
                page_end=c.page_end,
                text=c.text,
            )
        )
    db.add_all(chunk_rows)
    db.commit()

    # Embeddings (optional: Vertex or OpenAI; skip if no embedding provider)
    if is_embedding_available() and full_text.strip():
        embs = embed_texts(texts=[c.text for c in chunks])
        for row, emb in zip(chunk_rows, embs):
            row.embedding = emb
        db.commit()

    if settings.use_heuristic_extraction:
        logger.info("job_id=%s doc_id=%s: extraction=heuristic (USE_HEURISTIC_EXTRACTION=true)", job.id, doc.id)
        extracted = heuristic_extract(text=full_text)
    elif settings.llm_api_key:
        logger.info(
            "job_id=%s doc_id=%s: extraction=llm_api provider=%s model=%s (waiting for semaphore…)",
            job.id, doc.id, settings.llm_provider, settings.llm_model,
        )
        with _get_llm_semaphore():
            logger.info("job_id=%s doc_id=%s: semaphore acquired, calling LLM", job.id, doc.id)
            extracted = extract_via_llm_api(text=text_for_llm)
            _apply_llm_delay_after_request()
    elif settings.enable_vertex and settings.gcp_project:
        logger.info("job_id=%s doc_id=%s: extraction=vertex model=%s (waiting for semaphore…)", job.id, doc.id, settings.vertex_gemini_model)
        with _get_llm_semaphore():
            logger.info("job_id=%s doc_id=%s: semaphore acquired, calling Vertex", job.id, doc.id)
            extracted = extract_via_vertex(text=text_for_llm)
            _apply_llm_delay_after_request()
    else:
        logger.info("job_id=%s doc_id=%s: extraction=heuristic (no LLM_API_KEY, Vertex disabled)", job.id, doc.id)
        extracted = heuristic_extract(text=full_text)

    num_themes = len(extracted.themes)
    num_narratives = sum(len(t.narratives) for t in extracted.themes)
    logger.info("job_id=%s doc_id=%s: extracted themes=%s narratives=%s", job.id, doc.id, num_themes, num_narratives)
    doc.summary = extracted.summary
    if not (doc.summary or "").strip() and full_text.strip():
        doc.summary = full_text.replace("\n", " ").strip()[:400]
        logger.info("job_id=%s doc_id=%s: summary was empty, using first 400 chars of text", job.id, doc.id)
    elif not (doc.summary or "").strip():
        logger.warning("job_id=%s doc_id=%s: no summary (extraction returned none and document text is empty)", job.id, doc.id)
    db.commit()

    # Resolve themes (alias + optional embedding similarity); dedupe by canonical label within doc
    seen_theme_by_canon: dict[str, Theme] = {}
    for t in extracted.themes:
        canon = canonicalize_label(t.label)
        if canon not in seen_theme_by_canon:
            seen_theme_by_canon[canon] = resolve_theme(db, t.label)
        theme = seen_theme_by_canon[canon]
        for n in t.narratives:
            narrative = upsert_narrative(
                db,
                theme_id=theme.id,
                statement=n.statement,
                sub_theme=getattr(n, "sub_theme", None),
                narrative_stance=getattr(n, "narrative_stance", None) or None,
                confidence_level=getattr(n, "confidence_level", None) or None,
            )
            for ev in n.evidence[:3]:
                quote = (ev.quote or "").strip()
                if not quote:
                    continue
                db.add(
                    Evidence(
                        narrative_id=narrative.id,
                        document_id=doc.id,
                        quote=quote,
                        page=ev.page,
                    )
                )
    db.commit()

    job.status = "done"
    job.finished_at = dt.datetime.now(dt.timezone.utc)
    db.commit()


def _process_job_standalone(job_id: int) -> None:
    """Process a single ingest job in its own DB session (thread-safe for concurrent execution)."""
    db = SessionLocal()
    try:
        job = db.query(IngestJob).filter(IngestJob.id == job_id).one_or_none()
        if job is None:
            logger.warning("Job %s not found, skipping", job_id)
            return
        if job.status not in ("queued", "processing"):
            logger.warning("Job %s has status %s (expected queued/processing), skipping", job_id, job.status)
            return
        try:
            process_job(db, job)
        except Exception as e:  # noqa: BLE001
            logger.exception("Unexpected error processing job %s: %s", job_id, e)
    finally:
        db.close()


def run_loop(poll_seconds: int = 2) -> None:
    setup_logging(settings.log_file)
    # Retry init/create_all when SQLite is locked (e.g. API holding the DB at startup)
    for attempt in range(5):
        try:
            init_db()
            Base.metadata.create_all(bind=engine)
            break
        except OperationalError as e:
            if "locked" in str(e).lower() and attempt < 4:
                logger.warning("Database locked (attempt %s/5), retrying in 3s...", attempt + 1)
                time.sleep(3)
            else:
                raise

    # Log extraction config so user can verify Gemini/LLM is used
    if settings.use_heuristic_extraction:
        logger.info("Startup: extraction=heuristic only (USE_HEURISTIC_EXTRACTION=true)")
    elif settings.llm_api_key:
        logger.info(
            "Startup: extraction=LLM API provider=%s model=%s (set USE_HEURISTIC_EXTRACTION=true to force heuristic)",
            settings.llm_provider, settings.llm_model,
        )
    elif settings.enable_vertex and settings.gcp_project:
        logger.info("Startup: extraction=Vertex model=%s", settings.vertex_gemini_model)
    else:
        logger.info(
            "Startup: extraction=heuristic (no LLM_API_KEY; set LLM_API_KEY and LLM_PROVIDER=gemini for Gemini)",
        )

    max_workers = max(1, settings.llm_max_concurrent_requests)
    logger.info(
        "Ingest worker started, polling every %ds, max %d concurrent job(s) "
        "(LLM_MAX_CONCURRENT_REQUESTS=%d, LLM_DELAY_AFTER_REQUEST_SECONDS=%.1f)",
        poll_seconds, max_workers, settings.llm_max_concurrent_requests,
        settings.llm_delay_after_request_seconds,
    )

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ingest") as executor:
        running: dict[Future, int] = {}  # future -> job_id

        while True:
            # ---- Reap completed futures ----
            done_futures = [f for f in running if f.done()]
            for f in done_futures:
                job_id = running.pop(f)
                try:
                    f.result()  # surfaces exceptions for logging
                except Exception as e:  # noqa: BLE001
                    logger.exception("Concurrent job %s raised: %s", job_id, e)

            # ---- Calculate available capacity ----
            capacity = max_workers - len(running)
            if capacity <= 0:
                time.sleep(0.5)
                continue

            # ---- Pick up queued jobs (up to capacity) ----
            db = SessionLocal()
            try:
                jobs = (
                    db.query(IngestJob)
                    .filter(IngestJob.status == "queued")
                    .order_by(IngestJob.created_at.asc())
                    .limit(capacity)
                    .all()
                )
                if not jobs:
                    if not running:
                        time.sleep(poll_seconds)
                    else:
                        # Jobs still in flight — check back sooner
                        time.sleep(0.5)
                    continue

                # Mark as processing atomically to prevent double-pickup
                now = dt.datetime.now(dt.timezone.utc)
                job_ids: list[int] = []
                for job in jobs:
                    job.status = "processing"
                    job.started_at = now
                    job.error_message = None
                    job_ids.append(job.id)
                db.commit()
            finally:
                db.close()

            # ---- Submit to thread pool ----
            for jid in job_ids:
                future = executor.submit(_process_job_standalone, jid)
                running[future] = jid
                logger.info(
                    "Submitted job %s for concurrent processing (%d/%d slots used)",
                    jid, len(running), max_workers,
                )


if __name__ == "__main__":
    run_loop()

