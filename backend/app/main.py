from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Union

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import distinct, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

# Document timestamp for grouping/filtering: use file date (modified_at) when set, else received_at
def _doc_timestamp():
    return func.coalesce(Document.modified_at, Document.received_at)

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.aggregations import generate_theme_narrative_summaries, run_daily_aggregations
from app.db import engine, get_db, init_db
from app.models import (
    Base,
    Document,
    Evidence,
    IngestJob,
    Narrative,
    NarrativeMentionsDaily,
    Theme,
    ThemeAlias,
    ThemeInstrument,
    ThemeMergeReinforcement,
    ThemeMentionsDaily,
    ThemeNarrativeSummaryCache,
    ThemeRelationDaily,
    ThemeSubThemeMetrics,
    ThemeSubThemeMentionsDaily,
)
from app.schemas import (
    AdminThemeOut,
    BasketItemOut,
    ExtractionDryRunRequest,
    BasketSummaryItemOut,
    CancelIngestJobsOut,
    RequeueIngestJobsOut,
    DocumentExcerptsOut,
    DocumentExcerptOut,
    DocumentOut,
    EvidenceOut,
    ExtractionPromptOut,
    ExtractionPromptUpdate,
    IngestJobOut,
    IngestRequest,
    IngestResponse,
    IngestTextRequest,
    NarrativeDailyMetricOut,
    NarrativeOut,
    NarrativeShiftOut,
    NarrativeSummaryOut,
    NarrativeSummaryExtendedOut,
    BatchNarrativeSummaryItemOut,
    ThemeMetricsByConfidenceOut,
    ThemeMetricsByStanceOut,
    ThemeSubThemeDailyOut,
    CreateThemeRequest,
    PatchThemeRequest,
    ReassignNarrativesOut,
    ReassignNarrativesRequest,
    SuggestMergeGroupOut,
    SuggestMergesOut,
    ThemeDocumentNarrativeOut,
    ThemeDocumentOut,
    ThemeInsightsOut,
    ThemeMergeOut,
    ThemeMergeRequest,
    ThemeNetworkEdgeOut,
    ThemeNetworkNodeOut,
    ThemeNetworkOut,
    ThemeNetworkSnapshotOut,
    ThemeNetworkSnapshotsOut,
    ThemeDailyMetricOut,
    ThemeIdLabelOut,
    ThemeNotesOut,
    ThemeNotesUpdate,
    ThemeOut,
    ThemeWithNarrativesOut,
    SentimentRankingsOut,
    InflectionsOut,
    ThemeInstrumentOut,
    ThemeInstrumentCreate,
    InstrumentSummaryOut,
    SuggestInstrumentsOut,
    SuggestedInstrumentItem,
    InstrumentSearchOut,
    InstrumentSearchItem,
    ThemeBasketMetricsOut,
)
from app.analytics import (
    get_trending_themes,
    get_sentiment_rankings,
    get_inflections,
    get_debated_themes,
    get_archived_themes,
)
from app.insights import get_theme_insights
from app.llm.api_extract import (
    get_extraction_prompt_template,
    set_extraction_prompt_template,
    extract_themes_and_narratives as extract_themes_api,
)
from app.settings import settings
from app.theme_merge import MergeOptions, compute_merge_candidates, execute_theme_merge
from app.worker import canonicalize_label, ensure_alias
from app.storage.gcs import GcsStorage, get_storage
from app.followed_themes import get_followed_theme_ids, follow_theme, unfollow_theme, is_followed


# Basic logging
logger = logging.getLogger("investing_agent.api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Investing Narrative Agent API")

# MVP/dev convenience: allow dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
REQUEST_COUNT = Counter(
    "invest_agent_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "invest_agent_http_request_duration_seconds",
    "HTTP request latency",
    ["path"],
)
INGEST_REQUESTS = Counter(
    "invest_agent_ingest_requests_total",
    "Ingest requests",
    ["endpoint"],
)


@app.middleware("http")
async def _metrics_middleware(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    status = response.status_code
    REQUEST_COUNT.labels(method=request.method, path=path, status=status).inc()
    REQUEST_LATENCY.labels(path=path).observe(elapsed)
    logger.info("%s %s -> %s in %.3fs", request.method, path, status, elapsed)
    return response


def _gmail_daily_sync_loop() -> None:
    """Run scripts/gmail_to_ingest.py on an interval (e.g. daily). Runs in a daemon thread."""
    delay = getattr(settings, "gmail_daily_sync_initial_delay_seconds", 60) or 60
    interval = getattr(settings, "gmail_daily_sync_interval_seconds", 86400) or 86400
    script_timeout = getattr(settings, "gmail_daily_sync_script_timeout_seconds", 1800) or 1800
    logger.info(
        "Gmail daily sync loop started; first run in %ss, then every %ss (script timeout %ss)",
        delay,
        interval,
        script_timeout,
    )
    if delay > 0:
        time.sleep(delay)
    repo_root = Path(__file__).resolve().parent.parent.parent
    script = repo_root / "scripts" / "gmail_to_ingest.py"
    if not script.exists():
        logger.warning("Gmail daily sync enabled but script not found at %s; skipping.", script)
        return

    def _gmail_script_python() -> str:
        """Python executable for the Gmail script. Default python3 so script works with proxy (venv often hangs)."""
        explicit = getattr(settings, "gmail_sync_python", "python3") or "python3"
        exe = str(explicit).strip()
        if not exe:
            exe = "python3"
        if os.path.sep in exe or (os.path.altsep and (os.path.altsep in exe)):
            return exe if os.path.isfile(exe) else (shutil.which(exe) or exe)
        resolved = shutil.which(exe)
        return resolved or exe

    # Build subprocess env: ensure repo .env is applied so proxy/API_BASE_URL/etc. are set
    # (backend may have been started without inheriting shell env, so copy from .env explicitly).
    def _gmail_sync_env() -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["GMAIL_SYNC_HEADLESS"] = "1"
        try:
            from dotenv import dotenv_values
            env_file = repo_root / ".env"
            if env_file.exists():
                for k, v in dotenv_values(env_file).items():
                    if k and v is not None and str(v).strip() != "":
                        env[k] = str(v).strip()
        except Exception as e:
            logger.warning("Gmail daily sync: could not load .env for subprocess: %s", e)
        return env

    while True:
        try:
            logger.info("Gmail daily sync: running script now (after delay)")
            env = _gmail_sync_env()
            python_exe = _gmail_script_python()
            proc = subprocess.Popen(
                [python_exe, str(script)],
                cwd=str(repo_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            def log_stdout():
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        logger.info("Gmail sync: %s", line)
            reader = threading.Thread(target=log_stdout, daemon=True)
            reader.start()
            try:
                proc.wait(timeout=script_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                logger.warning("Gmail daily sync timed out after %ss", script_timeout)
            reader.join(timeout=2.0)
            logger.info(
                "Gmail daily sync run finished: returncode=%s",
                proc.returncode,
            )
            if proc.returncode != 0:
                logger.warning("Gmail daily sync script exited with code %s", proc.returncode)
        except Exception as e:
            logger.exception("Gmail daily sync failed: %s", e)
        time.sleep(interval)


@app.on_event("startup")
def _startup():
    from app.logging_config import setup_logging
    setup_logging(settings.log_file)
    init_db()
    Base.metadata.create_all(bind=engine)  # MVP: simple create_all
    enable_sync = getattr(settings, "enable_gmail_daily_sync", False)
    logger.info("Gmail daily sync: enable_gmail_daily_sync=%s", enable_sync)
    if enable_sync:
        t = threading.Thread(target=_gmail_daily_sync_loop, daemon=True, name="gmail_daily_sync")
        t.start()
        logger.info(
            "Gmail daily sync thread started (interval=%ss, first run in %ss)",
            getattr(settings, "gmail_daily_sync_interval_seconds", 86400),
            getattr(settings, "gmail_daily_sync_initial_delay_seconds", 60),
        )


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _pending_ingest_count(db: Session) -> int:
    return db.query(func.count(IngestJob.id)).filter(
        IngestJob.status.in_(["queued", "processing"])
    ).scalar() or 0


def _check_ingest_queue_cap(db: Session) -> None:
    if settings.max_queued_ingest_jobs <= 0:
        return
    if _pending_ingest_count(db) >= settings.max_queued_ingest_jobs:
        raise HTTPException(
            status_code=503,
            detail="Ingest queue full. Cancel pending jobs or increase MAX_QUEUED_INGEST_JOBS.",
        )


def _check_ingest_paused() -> None:
    if settings.pause_ingest:
        raise HTTPException(
            status_code=503,
            detail="Ingest is paused. Set PAUSE_INGEST=false in .env to allow new files.",
        )


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, db: Session = Depends(get_db)):
    INGEST_REQUESTS.labels(endpoint="ingest").inc()
    _check_ingest_paused()
    _check_ingest_queue_cap(db)
    existing = db.query(Document).filter(Document.sha256 == req.sha256).one_or_none()
    if existing is not None:
        # Optionally backfill document date when client sends modified_at (e.g. re-run ingest with file dates)
        if req.modified_at is not None:
            existing.modified_at = req.modified_at
            db.commit()
        job = (
            db.query(IngestJob)
            .filter(IngestJob.document_id == existing.id)
            .order_by(IngestJob.id.desc())
            .first()
        )
        if job is None:
            job = IngestJob(document_id=existing.id, status="queued")
            db.add(job)
            db.commit()
            db.refresh(job)
        return IngestResponse(document_id=existing.id, job_id=job.id, status=job.status)

    doc = Document(
        sha256=req.sha256,
        filename=req.filename,
        gcs_raw_uri=req.gcs_raw_uri,
        received_at=req.received_at or dt.datetime.now(dt.timezone.utc),
        modified_at=req.modified_at,
        source_type=req.source_type,
        source_name=req.source_name,
        source_uri=req.source_uri,
        content_type=req.content_type,
    )
    db.add(doc)
    try:
        db.commit()
        db.refresh(doc)
    except IntegrityError as e:
        db.rollback()
        if e.orig and "documents.sha256" in str(e.orig):
            existing = db.query(Document).filter(Document.sha256 == req.sha256).one_or_none()
            if existing is not None:
                if req.modified_at is not None:
                    existing.modified_at = req.modified_at
                    db.commit()
                job = (
                    db.query(IngestJob)
                    .filter(IngestJob.document_id == existing.id)
                    .order_by(IngestJob.id.desc())
                    .first()
                )
                if job is None:
                    job = IngestJob(document_id=existing.id, status="queued")
                    db.add(job)
                    db.commit()
                    db.refresh(job)
                return IngestResponse(document_id=existing.id, job_id=job.id, status=job.status)
        raise

    job = IngestJob(document_id=doc.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    return IngestResponse(document_id=doc.id, job_id=job.id, status=job.status)


@app.post("/ingest-file", response_model=IngestResponse)
def ingest_file(
    file: UploadFile = File(...),
    source_type: str = Form("pdf"),
    source_name: str = Form("wechat"),
    source_uri: Optional[str] = Form(None),
    modified_at: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    _check_ingest_paused()
    _check_ingest_queue_cap(db)
    # Sync endpoint so FastAPI runs it in a thread pool; avoids blocking the event loop
    # and 503 when the ingest client uploads multiple PDFs.
    data = file.file.read()
    digest = hashlib.sha256(data).hexdigest()

    storage = get_storage()
    stored = storage.upload_bytes(
        key=f"raw/{digest}_{file.filename or 'document.pdf'}",
        data=data,
        content_type=file.content_type or "application/pdf",
    )

    parsed_modified: Optional[dt.datetime] = None
    if modified_at:
        try:
            parsed_modified = dt.datetime.fromisoformat(modified_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    req = IngestRequest(
        sha256=digest,
        filename=file.filename or "document.pdf",
        gcs_raw_uri=stored.uri,
        received_at=dt.datetime.now(dt.timezone.utc),
        modified_at=parsed_modified,
        source_type=source_type,
        source_name=source_name,
        source_uri=source_uri,
    )
    INGEST_REQUESTS.labels(endpoint="ingest-file").inc()
    return ingest(req, db)


def _sanitize_filename_part(title: str, max_len: int = 80) -> str:
    """Sanitize a string for use in a storage key (no path separators or problematic chars)."""
    s = re.sub(r"[^\w\s\-.]", "", title)
    s = re.sub(r"\s+", "_", s.strip())
    return (s[:max_len] if len(s) > max_len else s) or "untitled"


@app.post("/ingest-text", response_model=IngestResponse)
def ingest_text(
    body: IngestTextRequest,
    db: Session = Depends(get_db),
):
    """Ingest HTML or plain text (e.g. Substack email body from Make/Zapier webhook)."""
    _check_ingest_paused()
    _check_ingest_queue_cap(db)

    content_bytes = body.content.encode("utf-8")
    digest = hashlib.sha256(content_bytes).hexdigest()
    ext = ".html" if body.content_type == "text/html" else ".txt"
    safe_title = _sanitize_filename_part(body.title)
    storage_key = f"raw/{digest}_{safe_title}{ext}"

    storage = get_storage()
    stored = storage.upload_bytes(
        key=storage_key,
        data=content_bytes,
        content_type=body.content_type,
    )

    parsed_modified: Optional[dt.datetime] = None
    if body.published_at:
        try:
            parsed_modified = dt.datetime.fromisoformat(body.published_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    req = IngestRequest(
        sha256=digest,
        filename=safe_title + ext,
        gcs_raw_uri=stored.uri,
        received_at=dt.datetime.now(dt.timezone.utc),
        modified_at=parsed_modified,
        source_type=body.source_type,
        source_name=body.source_name,
        source_uri=body.source_uri,
        content_type=body.content_type,
    )
    INGEST_REQUESTS.labels(endpoint="ingest-text").inc()
    return ingest(req, db)


@app.get("/themes", response_model=list[ThemeOut])
def list_themes(
    sort: str = Query("recent", description="recent or label"),
    active_only: bool = Query(False, description="If true, only themes with evidence in the last active_days"),
    active_days: int = Query(30, ge=1, le=365, description="Used when active_only=true"),
    db: Session = Depends(get_db),
):
    now = dt.datetime.now(dt.timezone.utc)
    cutoff_date = (now - dt.timedelta(days=7)).date()
    q = (
        db.query(Theme, func.max(Narrative.last_seen).label("last_updated"))
        .outerjoin(Narrative, Narrative.theme_id == Theme.id)
        .group_by(Theme.id)
    )
    if active_only:
        since_date = (now - dt.timedelta(days=active_days)).date()
        doc_date = func.date(_doc_timestamp())
        active_ids = set(
            r.theme_id
            for r in db.query(Narrative.theme_id)
            .join(Evidence, Evidence.narrative_id == Narrative.id)
            .join(Document, Evidence.document_id == Document.id)
            .filter(doc_date >= since_date)
            .distinct()
            .all()
        )
        if active_ids:
            q = q.filter(Theme.id.in_(active_ids))
        else:
            q = q.filter(Theme.id == -1)
    if sort == "label":
        q = q.order_by(Theme.canonical_label.asc())
    else:
        q = q.order_by(func.max(Narrative.last_seen).desc().nullslast())
    rows = q.all()
    return [
        ThemeOut(
            id=t.id,
            canonical_label=t.canonical_label,
            description=t.description,
            last_updated=last_updated,
            is_new=(t.created_at.date() >= cutoff_date) if t.created_at else False,
        )
        for t, last_updated in rows
    ]


@app.post("/themes", response_model=ThemeIdLabelOut)
def create_theme_user(body: CreateThemeRequest, db: Session = Depends(get_db)):
    """Create a new theme (user-created). Label is canonicalized. Theme is added to My Basket."""
    canon = canonicalize_label(body.canonical_label)
    if not canon:
        raise HTTPException(status_code=400, detail="Theme label cannot be empty")
    existing = db.query(Theme).filter(Theme.canonical_label == canon).one_or_none()
    if existing:
        follow_theme(existing.id)
        return ThemeIdLabelOut(id=existing.id, canonical_label=existing.canonical_label)
    theme = Theme(canonical_label=canon, description=body.description, created_by="user")
    db.add(theme)
    db.commit()
    db.refresh(theme)
    follow_theme(theme.id)
    return ThemeIdLabelOut(id=theme.id, canonical_label=theme.canonical_label)


@app.get("/themes/followed/ids", response_model=list[int])
def list_followed_theme_ids():
    """Return list of followed theme IDs (for UI to show follow state)."""
    return get_followed_theme_ids()


@app.get("/basket", response_model=list[BasketItemOut])
def get_basket(db: Session = Depends(get_db)):
    """List followed themes with minimal fields (id, label, description, instrument_count)."""
    ids = get_followed_theme_ids()
    if not ids:
        return []
    themes = db.query(Theme).filter(Theme.id.in_(ids)).all()
    theme_by_id = {t.id: t for t in themes}
    instrument_counts = (
        db.query(ThemeInstrument.theme_id, func.count(ThemeInstrument.id).label("n"))
        .filter(ThemeInstrument.theme_id.in_(ids))
        .group_by(ThemeInstrument.theme_id)
        .all()
    )
    count_by_id = {r.theme_id: r.n for r in instrument_counts}
    # Preserve order of ids (newest first)
    return [
        BasketItemOut(
            id=theme_by_id[tid].id,
            canonical_label=theme_by_id[tid].canonical_label,
            description=theme_by_id[tid].description,
            instrument_count=count_by_id.get(tid, 0),
        )
        for tid in ids
        if tid in theme_by_id
    ]


@app.post("/themes/{theme_id}/follow")
def follow_theme_endpoint(theme_id: int, db: Session = Depends(get_db)):
    """Add theme to My Basket (idempotent)."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    follow_theme(theme_id)
    return {"followed": True, "theme_id": theme_id}


@app.delete("/themes/{theme_id}/follow")
def unfollow_theme_endpoint(theme_id: int, db: Session = Depends(get_db)):
    """Remove theme from My Basket (idempotent)."""
    unfollow_theme(theme_id)
    return {"followed": False, "theme_id": theme_id}


def _theme_primary_symbol(db: Session, theme_id: int) -> str | None:
    # Single-column query returns the value, not a row
    symbol = (
        db.query(ThemeInstrument.symbol)
        .filter(ThemeInstrument.theme_id == theme_id)
        .order_by(ThemeInstrument.symbol)
        .first()
    )
    return symbol if symbol is not None else None


def _basket_metrics_for_symbol(primary_symbol: str) -> dict:
    """Fetch all basket metrics for one primary symbol (for lazy-loaded basket)."""
    from app.market_data import get_prices_and_valuation, compute_period_returns, get_earnings_estimates, get_eps_growth
    out: dict = {
        "forward_pe": None,
        "peg_ratio": None,
        "latest_rsi": None,
        "pct_1m": None,
        "pct_3m": None,
        "pct_ytd": None,
        "pct_6m": None,
        "quarterly_earnings_growth_yoy": None,
        "quarterly_revenue_growth_yoy": None,
        "next_fy_eps_estimate": None,
        "eps_revision_up_30d": None,
        "eps_revision_down_30d": None,
        "eps_growth_pct": None,
    }
    try:
        data = get_prices_and_valuation(primary_symbol, months=6)
        prices = data.get("prices") or []
        if prices:
            returns = compute_period_returns(prices)
            out["pct_1m"] = returns.get("pct_1m")
            out["pct_3m"] = returns.get("pct_3m")
            out["pct_ytd"] = returns.get("pct_ytd")
            out["pct_6m"] = returns.get("pct_6m")
            last_bar = prices[-1]
            if isinstance(last_bar.get("rsi_14"), (int, float)):
                out["latest_rsi"] = round(float(last_bar["rsi_14"]), 2)
        out["forward_pe"] = data.get("forward_pe")
        out["peg_ratio"] = data.get("peg_ratio")
        out["quarterly_earnings_growth_yoy"] = data.get("quarterly_earnings_growth_yoy")
        out["quarterly_revenue_growth_yoy"] = data.get("quarterly_revenue_growth_yoy")
        est = get_earnings_estimates(primary_symbol)
        out["next_fy_eps_estimate"] = est.get("next_fy_eps_estimate")
        out["eps_revision_up_30d"] = est.get("eps_revision_up_30d")
        out["eps_revision_down_30d"] = est.get("eps_revision_down_30d")
        growth = get_eps_growth(primary_symbol)
        out["eps_growth_pct"] = growth.get("eps_growth_pct")
    except Exception:
        pass
    return out


@app.get("/basket/summary", response_model=list[BasketSummaryItemOut])
def get_basket_summary(
    db: Session = Depends(get_db),
    include_metrics: bool = Query(True, description="If false, return theme list only (fast); use /themes/{id}/basket-metrics to load metrics per theme."),
):
    """List followed themes. With include_metrics=true (default) fetches valuation per theme (slow). Use include_metrics=false for fast load, then GET /themes/{id}/basket-metrics per theme."""
    ids = get_followed_theme_ids()
    if not ids:
        return []
    themes = db.query(Theme).filter(Theme.id.in_(ids)).all()
    theme_by_id = {t.id: t for t in themes}
    instrument_counts = (
        db.query(ThemeInstrument.theme_id, func.count(ThemeInstrument.id).label("n"))
        .filter(ThemeInstrument.theme_id.in_(ids))
        .group_by(ThemeInstrument.theme_id)
        .all()
    )
    count_by_id = {r.theme_id: r.n for r in instrument_counts}
    primary_by_id: dict[int, str] = {}
    for tid, sym in (
        db.query(ThemeInstrument.theme_id, ThemeInstrument.symbol)
        .filter(ThemeInstrument.theme_id.in_(ids))
        .order_by(ThemeInstrument.theme_id, ThemeInstrument.symbol)
        .all()
    ):
        if tid not in primary_by_id:
            primary_by_id[tid] = sym

    result: list[BasketSummaryItemOut] = []
    for tid in ids:
        if tid not in theme_by_id:
            continue
        t = theme_by_id[tid]
        row = BasketSummaryItemOut(
            id=t.id,
            canonical_label=t.canonical_label,
            description=t.description,
            instrument_count=count_by_id.get(tid, 0),
        )
        primary_symbol = primary_by_id.get(tid)
        if primary_symbol:
            row.primary_symbol = primary_symbol
        if include_metrics and primary_symbol:
            metrics = _basket_metrics_for_symbol(primary_symbol)
            row.forward_pe = metrics.get("forward_pe")
            row.peg_ratio = metrics.get("peg_ratio")
            row.latest_rsi = metrics.get("latest_rsi")
            row.pct_1m = metrics.get("pct_1m")
            row.pct_3m = metrics.get("pct_3m")
            row.pct_ytd = metrics.get("pct_ytd")
            row.pct_6m = metrics.get("pct_6m")
            row.quarterly_earnings_growth_yoy = metrics.get("quarterly_earnings_growth_yoy")
            row.quarterly_revenue_growth_yoy = metrics.get("quarterly_revenue_growth_yoy")
            row.next_fy_eps_estimate = metrics.get("next_fy_eps_estimate")
            row.eps_revision_up_30d = metrics.get("eps_revision_up_30d")
            row.eps_revision_down_30d = metrics.get("eps_revision_down_30d")
            row.eps_growth_pct = metrics.get("eps_growth_pct")
        result.append(row)
    return result


@app.get("/themes/{theme_id}/basket-metrics", response_model=ThemeBasketMetricsOut)
def get_theme_basket_metrics(theme_id: int, db: Session = Depends(get_db)):
    """Metrics for this theme's primary ticker (for lazy-loaded basket). Call after GET /basket/summary?include_metrics=false."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    primary_symbol = _theme_primary_symbol(db, theme_id)
    if not primary_symbol:
        return ThemeBasketMetricsOut(theme_id=theme_id)
    metrics = _basket_metrics_for_symbol(primary_symbol)
    return ThemeBasketMetricsOut(
        theme_id=theme_id,
        primary_symbol=primary_symbol,
        **{k: v for k, v in metrics.items() if k in ThemeBasketMetricsOut.model_fields},
    )


@app.get("/themes/contrarian-recent", response_model=list[ThemeIdLabelOut])
def get_themes_contrarian_recent(
    days: int = Query(14, ge=1, le=90, description="Look back days for contrarian evidence"),
    db: Session = Depends(get_db),
):
    """Themes that recently received at least one contrarian narrative (evidence in the last N days)."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    rows = (
        db.query(Theme.id, Theme.canonical_label)
        .join(Narrative, Narrative.theme_id == Theme.id)
        .join(Evidence, Evidence.narrative_id == Narrative.id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(
            Narrative.relation_to_prevailing == "contrarian",
            _doc_timestamp() >= since,
        )
        .distinct()
        .all()
    )
    return [ThemeIdLabelOut(id=r.id, canonical_label=r.canonical_label) for r in rows]


@app.get("/themes/archived", response_model=list[ThemeOut])
def list_archived_themes(
    inactive_days: int = Query(30, ge=1, le=365, description="No evidence in the last N days"),
    db: Session = Depends(get_db),
):
    """Themes with no evidence in the last N days."""
    return get_archived_themes(db, inactive_days=inactive_days)


@app.get("/analytics/themes/trending", response_model=list[ThemeOut])
def analytics_trending(
    recent_days: int = Query(14, ge=1, le=90),
    prior_days: int = Query(30, ge=1, le=180),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Themes where mention count in recent window exceeds prior window."""
    return get_trending_themes(db, recent_days=recent_days, prior_days=prior_days, limit=limit)


@app.get("/analytics/themes/sentiment-rankings", response_model=SentimentRankingsOut)
def analytics_sentiment_rankings(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Most positive and most negative themes by (bullish - bearish) / total over window."""
    return get_sentiment_rankings(db, days=days, limit=limit)


@app.get("/analytics/themes/inflections", response_model=InflectionsOut)
def analytics_inflections(
    recent_days: int = Query(14, ge=1, le=90),
    prior_days: int = Query(30, ge=1, le=180),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Four lists: less bullish, less bearish, attention peaking, most crowded."""
    return get_inflections(db, recent_days=recent_days, prior_days=prior_days, limit=limit)


@app.get("/analytics/themes/debated", response_model=list[ThemeOut])
def analytics_debated(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(30, ge=1, le=100),
    min_score: float = Query(0.3, ge=0, le=1),
    db: Session = Depends(get_db),
):
    """Themes with high debate score (no single dominant narrative)."""
    return get_debated_themes(db, days=days, limit=limit, min_score=min_score)


def _aggregate_network_by_canonical_label(
    doc_themes: dict[int, set[int]],
    theme_mentions: dict[int, int],
    themes_by_id: dict[int, Theme],
) -> tuple[list[ThemeNetworkNodeOut], list[ThemeNetworkEdgeOut]]:
    """Collapse themes that share the same canonical_label into one node with combined volume."""
    theme_ids = list(theme_mentions.keys())
    if not theme_ids:
        return [], []
    # theme_id -> canonical_label; then group by label
    label_to_ids: dict[str, list[int]] = {}
    for tid in theme_ids:
        label = themes_by_id[tid].canonical_label
        label_to_ids.setdefault(label, []).append(tid)
    # Representative theme_id per label (min id so links open a valid theme)
    label_to_repr_id: dict[str, int] = {label: min(ids) for label, ids in label_to_ids.items()}
    # Aggregated mention count per label
    label_mentions: dict[str, int] = {}
    for label, ids in label_to_ids.items():
        label_mentions[label] = sum(theme_mentions[tid] for tid in ids)
    # Edges by canonical label pairs (then map to repr ids)
    label_pair_count: dict[tuple[str, str], int] = {}
    for _doc_id, theme_ids in doc_themes.items():
        labels_in_doc = {themes_by_id[tid].canonical_label for tid in theme_ids}
        labels_sorted = sorted(labels_in_doc)
        for i in range(len(labels_sorted)):
            for j in range(i + 1, len(labels_sorted)):
                pair = (labels_sorted[i], labels_sorted[j])
                label_pair_count[pair] = label_pair_count.get(pair, 0) + 1
    nodes = [
        ThemeNetworkNodeOut(
            id=label_to_repr_id[label],
            canonical_label=label,
            mention_count=label_mentions[label],
        )
        for label in sorted(label_to_repr_id.keys())
    ]
    edges = [
        ThemeNetworkEdgeOut(
            theme_id_a=label_to_repr_id[a],
            theme_id_b=label_to_repr_id[b],
            weight=w,
        )
        for (a, b), w in label_pair_count.items()
    ]
    return nodes, edges


@app.get("/themes/network", response_model=ThemeNetworkOut)
def get_themes_network(
    months: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Theme co-occurrence network: nodes = themes with volume, edges = doc count where both themes appear.
    Themes that share the same canonical_label (e.g. after a merge) are shown as one node with combined volume."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=months * 31)
    rows = (
        db.query(Evidence.document_id, Narrative.theme_id)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(_doc_timestamp() >= since)
        .distinct()
        .all()
    )
    doc_themes: dict[int, set[int]] = {}
    theme_mentions: dict[int, int] = {}
    for doc_id, theme_id in rows:
        doc_themes.setdefault(doc_id, set()).add(theme_id)
        theme_mentions[theme_id] = theme_mentions.get(theme_id, 0) + 1
    theme_ids = sorted(theme_mentions.keys())
    themes_by_id = {t.id: t for t in db.query(Theme).filter(Theme.id.in_(theme_ids)).all()}
    nodes, edges = _aggregate_network_by_canonical_label(doc_themes, theme_mentions, themes_by_id)
    return ThemeNetworkOut(nodes=nodes, edges=edges)


def _network_for_date_range(
    db: Session,
    since: dt.datetime,
    until: dt.datetime,
) -> tuple[list[ThemeNetworkNodeOut], list[ThemeNetworkEdgeOut]]:
    """Compute theme network for documents with document timestamp (modified_at or received_at) in [since, until).
    Themes that share the same canonical_label are shown as one node with combined volume."""
    doc_ts = _doc_timestamp()
    rows = (
        db.query(Evidence.document_id, Narrative.theme_id)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(doc_ts >= since, doc_ts < until)
        .distinct()
        .all()
    )
    doc_themes: dict[int, set[int]] = {}
    theme_mentions: dict[int, int] = {}
    for doc_id, theme_id in rows:
        doc_themes.setdefault(doc_id, set()).add(theme_id)
        theme_mentions[theme_id] = theme_mentions.get(theme_id, 0) + 1
    theme_ids = sorted(theme_mentions.keys())
    themes_by_id = {t.id: t for t in db.query(Theme).filter(Theme.id.in_(theme_ids)).all()}
    return _aggregate_network_by_canonical_label(doc_themes, theme_mentions, themes_by_id)


@app.get("/themes/network/snapshots", response_model=ThemeNetworkSnapshotsOut)
def get_themes_network_snapshots(
    months: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """One network snapshot per month for the last N months. Use to show how relationships change over time."""
    now = dt.datetime.now(dt.timezone.utc)
    snapshots: list[ThemeNetworkSnapshotOut] = []
    for i in range(months - 1, -1, -1):
        # Month window: from (now - (i+1)*~31d) to (now - i*~31d)
        until = now - dt.timedelta(days=i * 31)
        since = until - dt.timedelta(days=31)
        label = since.strftime("%b %Y")
        nodes, edges = _network_for_date_range(db, since, until)
        snapshots.append(
            ThemeNetworkSnapshotOut(period_label=label, nodes=nodes, edges=edges)
        )
    return ThemeNetworkSnapshotsOut(snapshots=snapshots)


def _heuristic_narrative_summary(db: Session, theme_id: int):
    """Build a simple heuristic narrative summary when no cached LLM summary exists."""
    import json as _json
    narratives = (
        db.query(Narrative)
        .filter(Narrative.theme_id == theme_id)
        .order_by(Narrative.first_seen.asc())
        .all()
    )
    if not narratives:
        return NarrativeSummaryExtendedOut(
            summary="No narratives yet for this theme.",
            trending_sub_themes=[],
            inflection_alert=None,
        )
    parts = [f"This theme has {len(narratives)} narrative(s) in the past month. "]
    stances = {}
    for n in narratives:
        st = n.narrative_stance or "unknown"
        stances[st] = stances.get(st, 0) + 1
    if stances:
        stance_parts = [f"{cnt} {s}" for s, cnt in sorted(stances.items(), key=lambda x: -x[1])]
        parts.append(f"Stance mix: {', '.join(stance_parts)}. ")
    for n in narratives[:3]:
        parts.append(f"\"{n.statement[:50]}…\" " if len(n.statement) > 50 else f"\"{n.statement}\" ")
    parts.append("(Full LLM summary will be available after the next daily aggregation run.)")
    return NarrativeSummaryExtendedOut(
        summary="".join(parts).strip(),
        trending_sub_themes=[],
        inflection_alert=None,
    )


@app.get("/themes/narrative-summaries", response_model=dict[str, BatchNarrativeSummaryItemOut])
def get_batch_narrative_summaries(
    theme_ids: str = Query(..., description="Comma-separated theme IDs"),
    db: Session = Depends(get_db),
):
    """
    Return narrative summaries for multiple themes (30d period).
    Cached when available, otherwise heuristic. Cap 50 IDs per request.
    """
    import json as _json
    raw = [s.strip() for s in theme_ids.split(",") if s.strip()]
    ids: list[int] = []
    for s in raw:
        try:
            ids.append(int(s))
        except ValueError:
            continue
    ids = ids[:50]
    if not ids:
        return {}

    cached_list = (
        db.query(ThemeNarrativeSummaryCache)
        .filter(
            ThemeNarrativeSummaryCache.theme_id.in_(ids),
            ThemeNarrativeSummaryCache.period == "30d",
        )
        .all()
    )
    cache_by_theme: dict[int, ThemeNarrativeSummaryCache] = {c.theme_id: c for c in cached_list}

    out: dict[str, BatchNarrativeSummaryItemOut] = {}
    for tid in ids:
        cached = cache_by_theme.get(tid)
        if cached and cached.summary:
            trending = []
            if cached.trending_sub_themes:
                try:
                    trending = _json.loads(cached.trending_sub_themes)
                except Exception:
                    trending = []
            out[str(tid)] = BatchNarrativeSummaryItemOut(
                summary=cached.summary,
                trending_sub_themes=trending,
                inflection_alert=cached.inflection_alert,
            )
        else:
            ext = _heuristic_narrative_summary(db, tid)
            out[str(tid)] = BatchNarrativeSummaryItemOut(
                summary=ext.summary,
                trending_sub_themes=ext.trending_sub_themes,
                inflection_alert=ext.inflection_alert,
            )
    return out


@app.get("/themes/{theme_id}/notes", response_model=ThemeNotesOut)
def get_theme_notes(theme_id: int, db: Session = Depends(get_db)):
    """Get user notes for this theme."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    return ThemeNotesOut(content=theme.user_notes)


@app.patch("/themes/{theme_id}/notes", response_model=ThemeNotesOut)
def patch_theme_notes(theme_id: int, body: ThemeNotesUpdate, db: Session = Depends(get_db)):
    """Update user notes for this theme (upsert)."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    theme.user_notes = body.content if body.content is not None else theme.user_notes
    db.commit()
    db.refresh(theme)
    return ThemeNotesOut(content=theme.user_notes)


@app.get("/themes/{theme_id}", response_model=ThemeWithNarrativesOut)
def get_theme(theme_id: int, db: Session = Depends(get_db)):
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    narratives = (
        db.query(Narrative)
        .filter(Narrative.theme_id == theme_id)
        .order_by(Narrative.last_seen.desc())
        .all()
    )
    # First-appeared date = earliest document date (modified_at or received_at) among docs that cite this narrative
    narrative_ids = [n.id for n in narratives]
    doc_date = _doc_timestamp()
    earliest_doc = (
        db.query(Evidence.narrative_id, func.min(doc_date).label("earliest"))
        .join(Document, Evidence.document_id == Document.id)
        .filter(Evidence.narrative_id.in_(narrative_ids))
        .group_by(Evidence.narrative_id)
        .all()
    )
    date_created_by_nid = {r.narrative_id: r.earliest for r in earliest_doc}
    now = dt.datetime.now(dt.timezone.utc)
    cutoff_date = (now - dt.timedelta(days=7)).date()
    last_updated = max((n.last_seen for n in narratives), default=None) if narratives else None
    is_new = (theme.created_at.date() >= cutoff_date) if theme.created_at else False
    return ThemeWithNarrativesOut(
        id=theme.id,
        canonical_label=theme.canonical_label,
        description=theme.description,
        last_updated=last_updated,
        is_new=is_new,
        narratives=[
            NarrativeOut(
                id=n.id,
                theme_id=n.theme_id,
                statement=n.statement,
                stance=(n.narrative_stance or "unlabeled"),
                relation_to_prevailing=(n.relation_to_prevailing or "consensus"),
                date_created=date_created_by_nid.get(n.id) or n.created_at,
                first_seen=n.first_seen,
                last_seen=n.last_seen,
                status="active",
                sub_theme=n.sub_theme,
                narrative_stance=n.narrative_stance,
                confidence_level=n.confidence_level,
                evidence=[],
            )
            for n in narratives
        ],
    )


@app.get("/narratives/{narrative_id}", response_model=NarrativeOut)
def get_narrative(narrative_id: int, db: Session = Depends(get_db)):
    n = db.query(Narrative).filter(Narrative.id == narrative_id).one_or_none()
    if n is None:
        raise HTTPException(status_code=404, detail="Narrative not found")
    evs = (
        db.query(Evidence)
        .options(joinedload(Evidence.document))
        .filter(Evidence.narrative_id == narrative_id)
        .order_by(Evidence.created_at.desc())
        .limit(50)
        .all()
    )
    # First-appeared date = earliest document date (modified_at or received_at) among docs that cite this narrative
    doc_date = _doc_timestamp()
    earliest = (
        db.query(func.min(doc_date))
        .select_from(Evidence)
        .join(Document, Evidence.document_id == Document.id)
        .filter(Evidence.narrative_id == narrative_id)
        .scalar()
    )
    return NarrativeOut(
        id=n.id,
        theme_id=n.theme_id,
        statement=n.statement,
        stance=(n.narrative_stance or "unlabeled"),
        relation_to_prevailing=(n.relation_to_prevailing or "consensus"),
        date_created=earliest or n.created_at,
        first_seen=n.first_seen,
        last_seen=n.last_seen,
        status="active",
        sub_theme=n.sub_theme,
        narrative_stance=n.narrative_stance,
        confidence_level=n.confidence_level,
        evidence=[
            EvidenceOut(
                id=e.id,
                quote=e.quote,
                page=e.page,
                document_id=e.document_id,
                source_display=e.document.source_name if e.document else None,
            )
            for e in evs
        ],
    )


@app.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    download_url: Optional[str] = None
    text_download_url: Optional[str] = None

    storage = get_storage()
    # Only GCS backend supports signed URLs; otherwise return the raw URI for local dev.
    if isinstance(storage, GcsStorage):
        if doc.gcs_raw_uri:
            download_url = storage.generate_signed_url(uri=doc.gcs_raw_uri)
        if doc.gcs_text_uri:
            text_download_url = storage.generate_signed_url(uri=doc.gcs_text_uri)
    else:
        download_url = doc.gcs_raw_uri
        text_download_url = doc.gcs_text_uri

    return DocumentOut(
        id=doc.id,
        filename=doc.filename,
        summary=doc.summary,
        num_pages=doc.num_pages,
        source_type=doc.source_type,
        source_name=doc.source_name,
        source_uri=doc.source_uri,
        received_at=doc.received_at,
        modified_at=doc.modified_at,
        gcs_raw_uri=doc.gcs_raw_uri,
        gcs_text_uri=doc.gcs_text_uri,
        download_url=download_url,
        text_download_url=text_download_url,
    )


@app.get("/documents/{document_id}/excerpts", response_model=DocumentExcerptsOut)
def get_document_excerpts(document_id: int, db: Session = Depends(get_db)):
    """Return key sentences (evidence quotes) for this document, for highlighting in the extracted text."""
    doc = db.query(Document).filter(Document.id == document_id).one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    rows = (
        db.query(Evidence.quote, Evidence.page)
        .filter(Evidence.document_id == document_id)
        .distinct()
        .all()
    )
    excerpts = [DocumentExcerptOut(quote=(q or "").strip(), page=p) for q, p in rows if (q or "").strip()]
    return DocumentExcerptsOut(excerpts=excerpts)


@app.get("/documents/{document_id}/text")
def get_document_text(document_id: int, db: Session = Depends(get_db)):
    """Return the extracted plain text for the document."""
    doc = db.query(Document).filter(Document.id == document_id).one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.gcs_text_uri:
        raise HTTPException(status_code=404, detail="No extracted text for this document")
    storage = get_storage()
    try:
        raw = storage.download_bytes(uri=doc.gcs_text_uri)
        return Response(content=raw, media_type="text/plain; charset=utf-8")
    except Exception as e:
        logging.exception("Failed to download document text: %s", e)
        raise HTTPException(status_code=502, detail="Failed to load document text")


@app.get("/themes/{theme_id}/documents", response_model=list[ThemeDocumentOut])
def get_theme_documents(theme_id: int, db: Session = Depends(get_db)):
    """Documents that have evidence under this theme's narratives, chronological (newest first)."""
    # Verify theme exists
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    # Evidence -> Document for this theme (via Narrative)
    subq = (
        db.query(Evidence.document_id)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .filter(Narrative.theme_id == theme_id)
        .distinct()
    )
    doc_ids = [r[0] for r in subq.all()]
    if not doc_ids:
        return []
    docs = (
        db.query(Document)
        .filter(Document.id.in_(doc_ids))
        .order_by(_doc_timestamp().desc().nullslast())
        .all()
    )
    out = []
    for doc in docs:
        evs = (
            db.query(Evidence, Narrative)
            .join(Narrative, Narrative.id == Evidence.narrative_id)
            .filter(Evidence.document_id == doc.id, Narrative.theme_id == theme_id)
            .all()
        )
        narratives_seen: dict[int, tuple[str, str, str]] = {}
        excerpts: list[str] = []
        for e, n in evs:
            if n.id not in narratives_seen:
                narratives_seen[n.id] = (n.statement, n.narrative_stance or "unlabeled", n.relation_to_prevailing or "unlabeled")
            if e.quote and e.quote.strip():
                excerpts.append(e.quote.strip())
        doc_date = doc.modified_at or doc.received_at
        out.append(
            ThemeDocumentOut(
                id=doc.id,
                filename=doc.filename,
                received_at=doc_date,
                summary=doc.summary,
                narratives=[
                    ThemeDocumentNarrativeOut(statement=s, stance=st, relation_to_prevailing=rel)
                    for s, st, rel in narratives_seen.values()
                ],
                excerpts=excerpts[:20],
            )
        )
    return out


@app.get("/themes/{theme_id}/narrative-summary", response_model=Union[NarrativeSummaryOut, NarrativeSummaryExtendedOut])
def get_theme_narrative_summary(
    theme_id: int,
    period: str = Query("30d", description="'30d' for past month summary (pre-computed by LLM); 'all' for simple summary"),
    db: Session = Depends(get_db),
):
    """
    Return the pre-computed LLM narrative summary for this theme (past 30 days).
    Summaries are generated daily by the aggregation pipeline, not on every page load.
    Falls back to a simple heuristic summary if no cached summary exists yet.
    """
    import json as _json
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")

    narratives = (
        db.query(Narrative)
        .filter(Narrative.theme_id == theme_id)
        .order_by(Narrative.first_seen.asc())
        .all()
    )
    if not narratives:
        if period == "30d":
            return NarrativeSummaryExtendedOut(summary="No narratives yet for this theme.", trending_sub_themes=[], inflection_alert=None)
        return NarrativeSummaryOut(summary="No narratives yet for this theme.")

    if period != "30d":
        parts = [f"This theme has {len(narratives)} narrative(s). Key views: "]
        for n in narratives[:5]:
            parts.append(f"\"{n.statement[:60]}…\" " if len(n.statement) > 60 else f"\"{n.statement}\" ")
        return NarrativeSummaryOut(summary="".join(parts).strip())

    # period=30d: serve from pre-computed cache
    cached = (
        db.query(ThemeNarrativeSummaryCache)
        .filter(ThemeNarrativeSummaryCache.theme_id == theme_id, ThemeNarrativeSummaryCache.period == "30d")
        .one_or_none()
    )
    if cached and cached.summary:
        trending = []
        if cached.trending_sub_themes:
            try:
                trending = _json.loads(cached.trending_sub_themes)
            except Exception:
                trending = []
        return NarrativeSummaryExtendedOut(
            summary=cached.summary,
            trending_sub_themes=trending,
            inflection_alert=cached.inflection_alert,
        )

    return _heuristic_narrative_summary(db, theme_id)


@app.get("/themes/{theme_id}/insights", response_model=ThemeInsightsOut)
def get_theme_insights_endpoint(
    theme_id: int,
    months: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Narrative evolution insights: trajectory, consensus over time, emerging angles, debate intensity."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    return get_theme_insights(db, theme_id, months=months)


@app.get("/themes/{theme_id}/narrative-shifts", response_model=list[NarrativeShiftOut])
def get_theme_narrative_shifts(theme_id: int, db: Session = Depends(get_db)):
    """Detect when contrarian or refinement narratives emerged recently (last 14 days)."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)
    # Narratives that are contrarian or refinement and have evidence in the last 14 days
    recent_ev = (
        db.query(Evidence, Narrative, _doc_timestamp())
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(
            Narrative.theme_id == theme_id,
            Narrative.relation_to_prevailing.in_(["contrarian", "refinement"]),
            _doc_timestamp() >= window_start,
        )
        .all()
    )
    shifts: list[tuple[str, str]] = []
    seen_narrative: set[int] = set()
    for _e, n, doc_ts in recent_ev:
        if n.id in seen_narrative:
            continue
        seen_narrative.add(n.id)
        date_str = doc_ts.date().isoformat() if doc_ts else ""
        desc = f"{n.relation_to_prevailing.capitalize()} view: {n.statement[:80]}{'…' if len(n.statement) > 80 else ''}"
        shifts.append((date_str, desc))
    shifts.sort(key=lambda x: x[0], reverse=True)
    return [NarrativeShiftOut(date=d, description=desc) for d, desc in shifts[:10]]


def _parse_date(value) -> dt.date:
    """Coerce query result (date or string) to date."""
    if value is None:
        raise ValueError("date is None")
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    if len(s) >= 10:
        return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()
    raise ValueError(f"cannot parse date: {value!r}")


def _theme_metrics_from_evidence(
    db: Session, theme_id: int, since: dt.date
) -> list[ThemeDailyMetricOut]:
    """Compute theme daily metrics from Evidence when ThemeMentionsDaily has no rows."""
    # Daily totals for THIS theme: date -> (doc_count, mention_count)
    doc_date = func.date(_doc_timestamp())
    daily_totals = (
        db.query(
            doc_date.label("date"),
            func.count(func.distinct(Document.id)).label("doc_count"),
            func.count(Evidence.id).label("mention_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Evidence.narrative_id == Narrative.id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(
            Narrative.theme_id == theme_id,
            doc_date >= since,
        )
        .group_by(doc_date)
        .all()
    )
    if not daily_totals:
        return []
    # Total documents per day (by document timestamp: modified_at or received_at); share = theme_doc_count / total_docs.
    total_docs_per_day = (
        db.query(
            doc_date.label("date"),
            func.count(Document.id).label("doc_count"),
        )
        .select_from(Document)
        .filter(doc_date >= since)
        .group_by(doc_date)
        .all()
    )
    total_docs_by_date: dict[dt.date, int] = {}
    for row in total_docs_per_day:
        try:
            d = _parse_date(row.date)
            total_docs_by_date[d] = int(row.doc_count or 0)
        except ValueError:
            continue
    # Relation breakdown per day
    relation_rows = (
        db.query(
            doc_date.label("date"),
            Narrative.relation_to_prevailing,
            func.count(Evidence.id).label("mention_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Evidence.narrative_id == Narrative.id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(
            Narrative.theme_id == theme_id,
            doc_date >= since,
        )
        .group_by(doc_date, Narrative.relation_to_prevailing)
        .all()
    )
    rel_by_date: dict[dt.date, dict[str, int]] = {}
    for r in relation_rows:
        try:
            d = _parse_date(r.date)
        except ValueError:
            continue
        if d not in rel_by_date:
            rel_by_date[d] = {"consensus": 0, "contrarian": 0, "refinement": 0, "new_angle": 0}
        rel = (r.relation_to_prevailing or "consensus").lower()
        if rel not in ("consensus", "contrarian", "refinement", "new_angle"):
            rel = "consensus"
        rel_by_date[d][rel] += int(r.mention_count or 0)
    out = []
    for r in daily_totals:
        try:
            d = _parse_date(r.date)
        except ValueError:
            continue
        rel = rel_by_date.get(d, {})
        mention_count = int(r.mention_count or 0)
        doc_count_this_theme = int(r.doc_count or 0)
        total_docs_that_day = total_docs_by_date.get(d, 0)
        share = float(doc_count_this_theme) / total_docs_that_day if total_docs_that_day > 0 else None
        out.append(
            ThemeDailyMetricOut(
                theme_id=theme_id,
                date=d,
                doc_count=int(r.doc_count or 0),
                mention_count=mention_count,
                share_of_voice=share,
                consensus_count=rel.get("consensus", 0),
                contrarian_count=rel.get("contrarian", 0),
                refinement_count=rel.get("refinement", 0),
                new_angle_count=rel.get("new_angle", 0),
            )
        )
    out.sort(key=lambda x: x.date)
    return out


@app.get("/themes/{theme_id}/metrics", response_model=list[ThemeDailyMetricOut])
def get_theme_metrics(
    theme_id: int,
    months: int = Query(6, ge=1, le=12, description="Time range in months (1-12)"),
    db: Session = Depends(get_db),
):
    since = dt.date.today() - dt.timedelta(days=months * 31)
    rows = (
        db.query(ThemeMentionsDaily)
        .filter(ThemeMentionsDaily.theme_id == theme_id, ThemeMentionsDaily.date >= since)
        .order_by(ThemeMentionsDaily.date.asc())
        .all()
    )
    if rows:
        relation_rows = (
            db.query(ThemeRelationDaily)
            .filter(ThemeRelationDaily.theme_id == theme_id, ThemeRelationDaily.date >= since)
            .all()
        )
        rel_by_date = {r.date: r for r in relation_rows}
        # Recompute share_of_voice as doc_count / total_docs (all docs that day, by document timestamp).
        dates = [r.date for r in rows]
        doc_date = func.date(_doc_timestamp())
        total_docs_rows = (
            db.query(
                doc_date.label("date"),
                func.count(Document.id).label("doc_count"),
            )
            .select_from(Document)
            .filter(doc_date.in_(dates))
            .group_by(doc_date)
            .all()
        )
        total_docs_by_date = {}
        for tr in total_docs_rows:
            total_docs_by_date[tr.date] = int(tr.doc_count or 0)
        return [
            ThemeDailyMetricOut(
                theme_id=r.theme_id,
                date=r.date,
                doc_count=r.doc_count,
                mention_count=r.mention_count,
                share_of_voice=(
                    float(r.doc_count) / total_docs_by_date[r.date]
                    if total_docs_by_date.get(r.date, 0) > 0
                    else None
                ),
                consensus_count=rel_by_date[r.date].consensus_count if rel_by_date.get(r.date) else 0,
                contrarian_count=rel_by_date[r.date].contrarian_count if rel_by_date.get(r.date) else 0,
                refinement_count=rel_by_date[r.date].refinement_count if rel_by_date.get(r.date) else 0,
                new_angle_count=rel_by_date[r.date].new_angle_count if rel_by_date.get(r.date) else 0,
            )
            for r in rows
        ]
    # No pre-aggregated rows: compute from Evidence so the chart shows volume when narratives exist
    return _theme_metrics_from_evidence(db, theme_id, since)


@app.get("/instruments/search", response_model=InstrumentSearchOut)
def search_instruments(
    q: str = Query(..., min_length=1, max_length=64),
):
    """Search tickers by keyword (company name or symbol) via Alpha Vantage SYMBOL_SEARCH for typeahead when adding instruments."""
    from app.market_data import search_symbols
    result = search_symbols(q)
    return InstrumentSearchOut(
        matches=[InstrumentSearchItem(
            symbol=m["symbol"],
            name=m.get("name"),
            type=m.get("type") or "stock",
            region=m.get("region"),
            currency=m.get("currency"),
            match_score=m.get("match_score", 0.0),
        ) for m in result.get("matches") or []],
        message=result.get("message"),
    )


@app.get("/themes/{theme_id}/instruments", response_model=list[ThemeInstrumentOut])
def list_theme_instruments(theme_id: int, db: Session = Depends(get_db)):
    """List stocks/ETFs associated with this theme (manual, from_documents, llm_suggested)."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    rows = db.query(ThemeInstrument).filter(ThemeInstrument.theme_id == theme_id).order_by(ThemeInstrument.symbol).all()
    return [
        ThemeInstrumentOut(id=r.id, theme_id=r.theme_id, symbol=r.symbol, display_name=r.display_name, type=r.type or "stock", source=r.source or "manual")
        for r in rows
    ]


@app.get("/themes/{theme_id}/instruments/summary", response_model=list[InstrumentSummaryOut])
def list_theme_instruments_summary(theme_id: int, db: Session = Depends(get_db)):
    """List instruments for this theme with price and valuation metrics (for basket ticker rows)."""
    from app.market_data import get_prices_and_valuation, compute_period_returns, get_earnings_estimates, get_eps_growth

    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    rows = db.query(ThemeInstrument).filter(ThemeInstrument.theme_id == theme_id).order_by(ThemeInstrument.symbol).all()
    result: list[InstrumentSummaryOut] = []
    for r in rows:
        row = InstrumentSummaryOut(
            id=r.id,
            symbol=r.symbol,
            display_name=r.display_name,
            type=r.type or "stock",
            source=r.source or "manual",
        )
        try:
            data = get_prices_and_valuation(r.symbol, months=6)
            prices = data.get("prices") or []
            if prices:
                returns = compute_period_returns(prices)
                row.pct_1m = returns.get("pct_1m")
                row.pct_3m = returns.get("pct_3m")
                row.pct_ytd = returns.get("pct_ytd")
                last_bar = prices[-1]
                row.last_close = float(last_bar.get("close", 0)) if last_bar.get("close") is not None else None
                if isinstance(last_bar.get("rsi_14"), (int, float)):
                    row.latest_rsi = round(float(last_bar["rsi_14"]), 2)
            row.forward_pe = data.get("forward_pe")
            row.peg_ratio = data.get("peg_ratio")
            row.quarterly_earnings_growth_yoy = data.get("quarterly_earnings_growth_yoy")
            row.quarterly_revenue_growth_yoy = data.get("quarterly_revenue_growth_yoy")
            if data.get("message"):
                row.message = data["message"]
            est = get_earnings_estimates(r.symbol)
            row.next_fy_eps_estimate = est.get("next_fy_eps_estimate")
            row.eps_revision_up_30d = est.get("eps_revision_up_30d")
            row.eps_revision_down_30d = est.get("eps_revision_down_30d")
            growth = get_eps_growth(r.symbol)
            row.eps_growth_pct = growth.get("eps_growth_pct")
        except Exception:
            pass
        result.append(row)
    return result


@app.post("/themes/{theme_id}/instruments", response_model=ThemeInstrumentOut)
def add_theme_instrument(
    theme_id: int,
    body: ThemeInstrumentCreate,
    db: Session = Depends(get_db),
):
    """Add a ticker to this theme (source: manual or llm_suggested)."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    source = (body.source or "manual").lower()
    if source not in ("manual", "llm_suggested"):
        source = "manual"
    symbol = (body.symbol or "").strip().upper()[:32]
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")
    existing = db.query(ThemeInstrument).filter(ThemeInstrument.theme_id == theme_id, ThemeInstrument.symbol == symbol).one_or_none()
    if existing:
        return ThemeInstrumentOut(id=existing.id, theme_id=existing.theme_id, symbol=existing.symbol, display_name=existing.display_name, type=existing.type or "stock", source=existing.source or "manual")
    inst = ThemeInstrument(
        theme_id=theme_id,
        symbol=symbol,
        display_name=(body.display_name or "").strip()[:256] or None,
        type=(body.type or "stock").lower()[:16] or "stock",
        source=source,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return ThemeInstrumentOut(id=inst.id, theme_id=inst.theme_id, symbol=inst.symbol, display_name=inst.display_name, type=inst.type or "stock", source=inst.source or "manual")


@app.delete("/themes/{theme_id}/instruments/{instrument_id}")
def delete_theme_instrument(
    theme_id: int,
    instrument_id: int,
    db: Session = Depends(get_db),
):
    """Remove an instrument from this theme."""
    inst = db.query(ThemeInstrument).filter(ThemeInstrument.id == instrument_id, ThemeInstrument.theme_id == theme_id).one_or_none()
    if inst is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    db.delete(inst)
    db.commit()
    return {"ok": True}


@app.get("/themes/{theme_id}/instruments/from-documents/suggest", response_model=SuggestInstrumentsOut)
def suggest_theme_instruments_from_documents(theme_id: int, db: Session = Depends(get_db)):
    """Suggest tickers found in theme evidence (regex + LLM); no DB write. User adds via POST /instruments with source=from_documents."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    from app.instruments import suggest_instruments_from_documents
    items = suggest_instruments_from_documents(db, theme_id)
    return SuggestInstrumentsOut(
        suggestions=[SuggestedInstrumentItem(symbol=x["symbol"], display_name=x.get("display_name"), type=x.get("type") or "stock") for x in items]
    )


@app.post("/themes/{theme_id}/instruments/from-documents", response_model=list[ThemeInstrumentOut])
def add_theme_instruments_from_documents(theme_id: int, db: Session = Depends(get_db)):
    """Scan theme evidence for ticker mentions and add all with source=from_documents. Prefer GET .../from-documents/suggest + user choice."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    from app.instruments import extract_instruments_from_theme_documents
    created = extract_instruments_from_theme_documents(db, theme_id)
    return [
        ThemeInstrumentOut(id=r.id, theme_id=r.theme_id, symbol=r.symbol, display_name=r.display_name, type=r.type or "stock", source=r.source or "from_documents")
        for r in created
    ]


@app.get("/themes/{theme_id}/instruments/suggest", response_model=SuggestInstrumentsOut)
def suggest_theme_instruments(theme_id: int, db: Session = Depends(get_db)):
    """LLM-suggested tickers for this theme (not persisted; client can add via POST)."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    # Narratives from the past 7 days (by last_seen) for richer LLM context
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    recent = (
        db.query(Narrative.statement)
        .filter(Narrative.theme_id == theme_id, Narrative.last_seen >= since)
        .order_by(Narrative.last_seen.desc())
        .limit(50)
        .all()
    )
    recent_narratives_text = "\n".join((r[0] or "").strip() for r in recent if (r[0] or "").strip()) if recent else None
    from app.instruments import suggest_instruments_llm
    items = suggest_instruments_llm(theme.canonical_label, theme.description, recent_narratives=recent_narratives_text)
    return SuggestInstrumentsOut(
        suggestions=[SuggestedInstrumentItem(symbol=x["symbol"], display_name=x.get("display_name"), type=x.get("type") or "stock") for x in items]
    )


@app.get("/instruments/{symbol}/prices")
def get_instrument_prices(
    symbol: str,
    months: int = Query(6, ge=1, le=12),
):
    """Price history, valuation (trailing/forward PE, PEG), earnings estimates, EPS growth, and technical indicators via Alpha Vantage."""
    from app.market_data import get_prices_and_valuation, get_earnings_estimates, get_eps_growth
    out = dict(get_prices_and_valuation(symbol, months=months))
    est = get_earnings_estimates(symbol)
    out["next_fy_eps_estimate"] = est.get("next_fy_eps_estimate")
    out["eps_revision_up_30d"] = est.get("eps_revision_up_30d")
    out["eps_revision_down_30d"] = est.get("eps_revision_down_30d")
    growth = get_eps_growth(symbol)
    out["eps_growth_pct"] = growth.get("eps_growth_pct")
    out["trailing_12m_eps"] = growth.get("trailing_12m_eps")
    return out


@app.get("/instruments/{symbol}/historical-pe")
def get_instrument_historical_pe(
    symbol: str,
    months: int = Query(24, ge=6, le=60),
):
    """Historical trailing P/E series (daily close / trailing 4Q EPS) and current PE percentile for chart."""
    from app.market_data import get_historical_pe
    return get_historical_pe(symbol, months=months)


@app.get("/themes/{theme_id}/metrics-by-stance", response_model=list[ThemeMetricsByStanceOut])
def get_theme_metrics_by_stance(
    theme_id: int,
    months: int = Query(6, ge=1, le=12),
    confidence: Optional[str] = Query(None, description="Filter by narrative confidence: 'fact', 'opinion', or omit for all"),
    db: Session = Depends(get_db),
):
    """Time-series of narrative mention counts by narrative_stance (bullish/bearish/mixed/neutral) for this theme. Optional confidence filter: fact | opinion."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    since = dt.date.today() - dt.timedelta(days=months * 31)
    doc_date = func.date(_doc_timestamp())
    q = (
        db.query(
            doc_date.label("date"),
            Narrative.narrative_stance,
            func.count(Evidence.id).label("mention_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(Narrative.theme_id == theme_id, doc_date >= since)
    )
    if confidence and confidence.lower() in ("fact", "opinion"):
        q = q.filter(func.lower(func.coalesce(Narrative.confidence_level, "opinion")) == confidence.lower())
    rows = q.group_by(doc_date, Narrative.narrative_stance).all()
    by_date: dict[str, dict[str, int]] = {}
    for r in rows:
        d = r.date.isoformat()[:10] if hasattr(r.date, "isoformat") else str(r.date)[:10]
        st = (r.narrative_stance or "neutral").lower()
        if st not in ("bullish", "bearish", "mixed", "neutral"):
            st = "neutral"
        if d not in by_date:
            by_date[d] = {"bullish_count": 0, "bearish_count": 0, "mixed_count": 0, "neutral_count": 0, "total_count": 0}
        by_date[d][f"{st}_count"] = int(r.mention_count or 0)
        by_date[d]["total_count"] += int(r.mention_count or 0)
    out = [
        ThemeMetricsByStanceOut(
            date=d,
            bullish_count=vals["bullish_count"],
            bearish_count=vals["bearish_count"],
            mixed_count=vals["mixed_count"],
            neutral_count=vals["neutral_count"],
            total_count=vals["total_count"],
        )
        for d, vals in sorted(by_date.items())
    ]
    return out


@app.get("/themes/{theme_id}/metrics-by-confidence", response_model=list[ThemeMetricsByConfidenceOut])
def get_theme_metrics_by_confidence(
    theme_id: int,
    months: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Time-series of narrative mention counts by confidence_level (fact/opinion) for this theme."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    since = dt.date.today() - dt.timedelta(days=months * 31)
    doc_date = func.date(_doc_timestamp())
    rows = (
        db.query(
            doc_date.label("date"),
            Narrative.confidence_level,
            func.count(Evidence.id).label("mention_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(Narrative.theme_id == theme_id, doc_date >= since)
        .group_by(doc_date, Narrative.confidence_level)
        .all()
    )
    by_date: dict[str, dict[str, int]] = {}
    for r in rows:
        d = r.date.isoformat()[:10] if hasattr(r.date, "isoformat") else str(r.date)[:10]
        cl = (r.confidence_level or "opinion").lower()
        if cl not in ("fact", "opinion"):
            cl = "opinion"
        if d not in by_date:
            by_date[d] = {"fact_count": 0, "opinion_count": 0, "total_count": 0}
        by_date[d][f"{cl}_count"] = int(r.mention_count or 0)
        by_date[d]["total_count"] += int(r.mention_count or 0)
    out = [
        ThemeMetricsByConfidenceOut(
            date=d,
            fact_count=vals["fact_count"],
            opinion_count=vals["opinion_count"],
            total_count=vals["total_count"],
        )
        for d, vals in sorted(by_date.items())
    ]
    return out


@app.get("/themes/{theme_id}/stance-by-confidence")
def get_theme_stance_by_confidence(
    theme_id: int,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Aggregate stance breakdown (bullish/bearish/mixed/neutral) split by
    confidence_level (fact vs opinion) for a given time window.
    Returns { fact: {bullish: N, bearish: N, ...}, opinion: {bullish: N, ...} }
    """
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    since = dt.date.today() - dt.timedelta(days=days)
    doc_date = func.date(_doc_timestamp())
    rows = (
        db.query(
            Narrative.confidence_level,
            Narrative.narrative_stance,
            func.count(Evidence.id).label("cnt"),
        )
        .select_from(Evidence)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(Narrative.theme_id == theme_id, doc_date >= since)
        .group_by(Narrative.confidence_level, Narrative.narrative_stance)
        .all()
    )
    result: dict = {
        "fact": {"bullish": 0, "bearish": 0, "mixed": 0, "neutral": 0, "total": 0},
        "opinion": {"bullish": 0, "bearish": 0, "mixed": 0, "neutral": 0, "total": 0},
    }
    for r in rows:
        cl = (r.confidence_level or "opinion").lower()
        if cl not in ("fact", "opinion"):
            cl = "opinion"
        stance = (r.narrative_stance or "neutral").lower()
        if stance not in ("bullish", "bearish", "mixed", "neutral"):
            stance = "neutral"
        cnt = int(r.cnt or 0)
        result[cl][stance] += cnt
        result[cl]["total"] += cnt
    return result


@app.get("/themes/{theme_id}/metrics-by-sub-theme", response_model=list[ThemeSubThemeDailyOut])
def get_theme_metrics_by_sub_theme(
    theme_id: int,
    months: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Daily metrics per sub-theme for stacked share-of-voice chart.

    Always computed live from Evidence + Narrative.sub_theme so the chart
    reflects the *current* sub-theme labels (which can change when new
    documents update an existing narrative).  The precomputed
    ThemeSubThemeMentionsDaily table is still populated by the daily
    aggregation job for other consumers, but is NOT used here because it
    can become stale when sub-theme labels are reassigned after the
    aggregation has already run for a given date.
    """
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    since = dt.date.today() - dt.timedelta(days=months * 31)

    doc_date = func.date(_doc_timestamp())
    from_ev = (
        db.query(
            doc_date.label("date"),
            Narrative.sub_theme,
            func.count(Evidence.id).label("mention_count"),
            func.count(func.distinct(Document.id)).label("doc_count"),
        )
        .select_from(Evidence)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Document.id == Evidence.document_id)
        .filter(
            Narrative.theme_id == theme_id,
            Narrative.sub_theme.isnot(None),
            Narrative.sub_theme != "",
            doc_date >= since,
        )
        .group_by(doc_date, Narrative.sub_theme)
        .order_by(doc_date.asc(), Narrative.sub_theme.asc())
        .all()
    )
    return [
        ThemeSubThemeDailyOut(
            date=(r.date.isoformat() if hasattr(r.date, "isoformat") else str(r.date)[:10]),
            sub_theme=r.sub_theme or "",
            doc_count=int(r.doc_count or 0),
            mention_count=int(r.mention_count or 0),
        )
        for r in from_ev
    ]


@app.get("/themes/{theme_id}/narratives", response_model=list[NarrativeOut])
def get_theme_narratives(
    theme_id: int,
    date: Optional[str] = Query(None, description="'today' to list narratives that got evidence today (newest first)"),
    since: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD) to list narratives with evidence on or after this date"),
    limit: Optional[int] = Query(None, ge=1, le=500, description="Max number of narratives to return (newest first)"),
    on_latest_date: bool = Query(False, description="If true, return all narratives with evidence on the theme's most recent activity date (no limit)"),
    db: Session = Depends(get_db),
):
    """List narratives for this theme. With date=today or since=... returns only narratives with evidence on that day(s), newest first, with evidence. With on_latest_date=true returns all narratives on the most recent date."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if theme is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    doc_date = func.date(_doc_timestamp())
    theme_narrative_ids = [r[0] for r in db.query(Narrative.id).filter(Narrative.theme_id == theme_id).all()]
    if on_latest_date:
        # Find the most recent document date for this theme, then all narratives with evidence on that date
        max_date_row = (
            db.query(func.max(doc_date).label("max_d"))
            .select_from(Evidence)
            .join(Document, Document.id == Evidence.document_id)
            .filter(Evidence.narrative_id.in_(theme_narrative_ids))
            .first()
        )
        if not max_date_row or max_date_row.max_d is None:
            narrative_ids = []
        else:
            latest_d = max_date_row.max_d
            if isinstance(latest_d, dt.datetime):
                latest_d = latest_d.date()
            elif isinstance(latest_d, str):
                latest_d = dt.datetime.strptime(latest_d[:10], "%Y-%m-%d").date()
            narrative_ids = [
                r[0]
                for r in db.query(Evidence.narrative_id)
                .join(Document, Document.id == Evidence.document_id)
                .filter(Evidence.narrative_id.in_(theme_narrative_ids), doc_date == latest_d)
                .distinct()
                .all()
            ]
    elif date == "today":
        today = dt.date.today()
        narrative_ids = [
            r[0]
            for r in db.query(Evidence.narrative_id)
            .join(Document, Document.id == Evidence.document_id)
            .filter(Evidence.narrative_id.in_(theme_narrative_ids), doc_date == today)
            .distinct()
            .all()
        ]
    elif since:
        try:
            since_d = dt.datetime.strptime(since[:10], "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="since must be YYYY-MM-DD")
        narrative_ids = [
            r[0]
            for r in db.query(Evidence.narrative_id)
            .join(Document, Document.id == Evidence.document_id)
            .filter(Evidence.narrative_id.in_(theme_narrative_ids), doc_date >= since_d)
            .distinct()
            .all()
        ]
    else:
        narrative_ids = theme_narrative_ids

    if not narrative_ids:
        return []

    # Order by last_seen desc (newest first). When on_latest_date, do not apply limit.
    q = (
        db.query(Narrative)
        .filter(Narrative.id.in_(narrative_ids))
        .order_by(Narrative.last_seen.desc())
    )
    if limit is not None and not on_latest_date:
        q = q.limit(limit)
    narratives = q.all()
    earliest_doc = (
        db.query(Evidence.narrative_id, func.min(doc_date).label("earliest"))
        .join(Document, Document.id == Evidence.document_id)
        .filter(Evidence.narrative_id.in_(narrative_ids))
        .group_by(Evidence.narrative_id)
        .all()
    )
    date_created_by_nid = {r.narrative_id: r.earliest for r in earliest_doc}
    result = []
    for n in narratives:
        evs = (
            db.query(Evidence)
            .options(joinedload(Evidence.document))
            .filter(Evidence.narrative_id == n.id)
            .order_by(Evidence.created_at.desc())
            .limit(20)
            .all()
        )
        result.append(
            NarrativeOut(
                id=n.id,
                theme_id=n.theme_id,
                statement=n.statement,
                stance=(n.narrative_stance or "unlabeled"),
                relation_to_prevailing=n.relation_to_prevailing or "consensus",
                date_created=date_created_by_nid.get(n.id) or n.created_at,
                first_seen=n.first_seen,
                last_seen=n.last_seen,
                status="active",
                sub_theme=n.sub_theme,
                narrative_stance=n.narrative_stance,
                confidence_level=n.confidence_level,
                evidence=[
                    EvidenceOut(
                        id=e.id,
                        quote=e.quote,
                        page=e.page,
                        document_id=e.document_id,
                        source_display=e.document.source_name if e.document else None,
                    )
                    for e in evs
                ],
            )
        )
    return result


@app.get("/narratives/{narrative_id}/metrics", response_model=list[NarrativeDailyMetricOut])
def get_narrative_metrics(narrative_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(NarrativeMentionsDaily)
        .filter(NarrativeMentionsDaily.narrative_id == narrative_id)
        .order_by(NarrativeMentionsDaily.date.asc())
        .all()
    )
    return [
        NarrativeDailyMetricOut(
            narrative_id=r.narrative_id,
            date=r.date,
            doc_count=r.doc_count,
            mention_count=r.mention_count,
            burst_score=r.burst_score,
            accel_score=r.accel_score,
            novelty_score=r.novelty_score,
        )
        for r in rows
    ]


@app.get("/admin/ingest-failures", response_model=list[IngestJobOut])
def list_ingest_failures(limit: int = 50, db: Session = Depends(get_db)):
    jobs = (
        db.query(IngestJob)
        .options(joinedload(IngestJob.document))
        .filter(IngestJob.status == "error")
        .order_by(IngestJob.finished_at.desc().nullslast(), IngestJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        IngestJobOut(
            id=j.id,
            document_id=j.document_id,
            filename=j.document.filename if j.document else None,
            source_name=j.document.source_name if j.document else None,
            source_type=j.document.source_type if j.document else None,
            status=j.status,
            error_message=j.error_message,
            created_at=j.created_at,
            started_at=j.started_at,
            finished_at=j.finished_at,
        )
        for j in jobs
    ]


@app.get("/admin/ingest-jobs", response_model=list[IngestJobOut])
def list_all_ingest_jobs(limit: int = 500, db: Session = Depends(get_db)):
    """Return all ingest jobs for the admin ingest-status view.

    Always returns ALL queued, processing, and done jobs so live status is
    accurate, then fills the remaining budget with the most recent error jobs.
    """
    # 1) Always include every queued / processing / done job (no limit).
    priority_jobs = (
        db.query(IngestJob)
        .options(joinedload(IngestJob.document))
        .filter(IngestJob.status.in_(["queued", "processing", "done"]))
        .order_by(IngestJob.created_at.desc())
        .all()
    )

    # 2) Fill remaining budget with error jobs (most recent first).
    remaining = max(limit - len(priority_jobs), 0)
    error_jobs = (
        db.query(IngestJob)
        .options(joinedload(IngestJob.document))
        .filter(IngestJob.status == "error")
        .order_by(IngestJob.created_at.desc())
        .limit(remaining)
        .all()
    ) if remaining > 0 else []

    # Merge: priority jobs first, then error jobs.
    merged = [*priority_jobs, *error_jobs]

    return [
        IngestJobOut(
            id=j.id,
            document_id=j.document_id,
            filename=j.document.filename if j.document else None,
            source_name=j.document.source_name if j.document else None,
            source_type=j.document.source_type if j.document else None,
            status=j.status,
            error_message=j.error_message,
            created_at=j.created_at,
            started_at=j.started_at,
            finished_at=j.finished_at,
        )
        for j in merged
    ]


@app.post("/admin/ingest-jobs/requeue", response_model=RequeueIngestJobsOut)
def requeue_error_ingest_jobs():
    """Reset ingest jobs in 'error' (cancelled or failed) back to 'queued' so the worker will retry them."""
    with engine.begin() as conn:
        result = conn.execute(
            update(IngestJob)
            .where(IngestJob.status == "error")
            .values(
                status="queued",
                started_at=None,
                finished_at=None,
                error_message=None,
            )
        )
        rowcount = result.rowcount
    return RequeueIngestJobsOut(requeued=rowcount)


@app.post("/admin/ingest-jobs/cancel-all", response_model=CancelIngestJobsOut)
def cancel_all_pending_ingest_jobs(db: Session = Depends(get_db)):
    """Cancel all queued and processing ingest jobs so no more documents are sent to the LLM."""
    result = db.execute(
        update(IngestJob)
        .where(IngestJob.status.in_(["queued", "processing"]))
        .values(status="error", error_message="cancelled")
    )
    db.commit()
    return CancelIngestJobsOut(cancelled=result.rowcount)


@app.get("/settings/extraction-prompt", response_model=ExtractionPromptOut)
def get_extraction_prompt() -> ExtractionPromptOut:
    """Return the current theme/narrative extraction prompt template (editable by user)."""
    return ExtractionPromptOut(
        prompt_template=get_extraction_prompt_template(),
        hint="Use {{schema}} and {{text}} as placeholders. Saving writes to prompts/extract_themes.txt.",
    )


@app.put("/settings/extraction-prompt", response_model=ExtractionPromptOut)
def update_extraction_prompt(body: ExtractionPromptUpdate) -> ExtractionPromptOut:
    """Overwrite the extraction prompt template. Affects future ingest jobs using the LLM API."""
    set_extraction_prompt_template(body.prompt_template)
    return ExtractionPromptOut(
        prompt_template=get_extraction_prompt_template(),
        hint="Use {{schema}} and {{text}} as placeholders. Saving writes to prompts/extract_themes.txt.",
    )


@app.post("/admin/extraction-dry-run")
def extraction_dry_run(
    body: ExtractionDryRunRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Run theme/narrative extraction with one or more models and return their outputs.
    No database writes: use this to compare extraction quality across models (e.g. gpt-4o-mini vs gpt-4o).
    Provide either body.text (raw document text) or body.document_id (load text from stored document).
    Uses current LLM_PROVIDER; pass models e.g. ['gpt-4o-mini', 'gpt-4o'] to compare.
    """
    from dataclasses import asdict

    text: str | None = None
    if body.document_id is not None and body.text:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of 'text' or 'document_id', not both.",
        )
    if body.document_id is not None:
        doc = db.query(Document).filter(Document.id == body.document_id).one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if not doc.gcs_text_uri:
            raise HTTPException(
                status_code=400,
                detail="Document has no extracted text (gcs_text_uri). Run ingest first.",
            )
        storage = get_storage()
        try:
            text = storage.download_bytes(uri=doc.gcs_text_uri).decode("utf-8", errors="replace")
        except Exception as e:
            logging.exception("Failed to download document text: %s", e)
            raise HTTPException(status_code=502, detail="Failed to load document text from storage")
    elif body.text:
        text = body.text
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide 'text' (raw document text) or 'document_id' (existing document).",
        )

    models_to_run = body.models if body.models else [settings.llm_model or "gpt-4o-mini"]
    results: dict[str, dict] = {}
    for model in models_to_run:
        model = (model or "").strip()
        if not model:
            continue
        try:
            extracted = extract_themes_api(text=text, model_override=model)
            results[model] = asdict(extracted)
        except Exception as e:
            results[model] = {"error": str(e)}

    return {
        "results": results,
        "text_preview": (text[:500] + "…") if len(text) > 500 else text,
        "text_length": len(text),
    }


@app.get("/admin/themes", response_model=list[AdminThemeOut])
def list_admin_themes(
    sort: str = Query("label", description="label or recent"),
    db: Session = Depends(get_db),
):
    """List all themes with first_appeared (earliest doc date), document count, last_updated for the admin theme-merge UI."""
    doc_date = _doc_timestamp()
    q = (
        db.query(
            Theme,
            func.count(distinct(Evidence.document_id)).label("document_count"),
            func.min(doc_date).label("first_doc_date"),
            func.max(Narrative.last_seen).label("last_updated"),
        )
        .outerjoin(Narrative, Narrative.theme_id == Theme.id)
        .outerjoin(Evidence, Evidence.narrative_id == Narrative.id)
        .outerjoin(Document, Document.id == Evidence.document_id)
        .group_by(Theme.id)
    )
    if sort == "recent":
        q = q.order_by(func.max(Narrative.last_seen).desc().nullslast())
    else:
        q = q.order_by(Theme.canonical_label.asc())
    rows = q.all()
    out = []
    for t, document_count, first_doc_date, last_updated in rows:
        first_appeared = first_doc_date if first_doc_date is not None else t.created_at
        out.append(
            AdminThemeOut(
                id=t.id,
                canonical_label=t.canonical_label,
                description=t.description,
                first_appeared=first_appeared,
                document_count=document_count or 0,
                last_updated=last_updated,
            )
        )
    return out


@app.post("/admin/themes", response_model=ThemeIdLabelOut)
def create_theme(body: CreateThemeRequest, db: Session = Depends(get_db)) -> ThemeIdLabelOut:
    """Create a new theme by label (e.g. for reassigning narratives into a new theme). Label is canonicalized (lowercase, single spaces)."""
    canon = canonicalize_label(body.canonical_label)
    if not canon:
        raise HTTPException(status_code=400, detail="Theme label cannot be empty")
    existing = db.query(Theme).filter(Theme.canonical_label == canon).one_or_none()
    if existing:
        return ThemeIdLabelOut(id=existing.id, canonical_label=existing.canonical_label)
    theme = Theme(canonical_label=canon, description=body.description, created_by="system")
    db.add(theme)
    db.commit()
    db.refresh(theme)
    return ThemeIdLabelOut(id=theme.id, canonical_label=theme.canonical_label)


@app.patch("/admin/themes/{theme_id}", response_model=ThemeIdLabelOut)
def patch_theme(theme_id: int, body: PatchThemeRequest, db: Session = Depends(get_db)) -> ThemeIdLabelOut:
    """Rename a theme (update canonical_label) and/or description. Old label is stored as an alias so extraction still resolves to this theme."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")
    if body.canonical_label is not None:
        canon = canonicalize_label(body.canonical_label)
        if not canon:
            raise HTTPException(status_code=400, detail="Theme label cannot be empty")
        other = db.query(Theme).filter(Theme.canonical_label == canon, Theme.id != theme_id).one_or_none()
        if other:
            raise HTTPException(status_code=400, detail=f"Another theme already has the label '{canon}'")
        old_label = theme.canonical_label
        theme.canonical_label = canon
        if old_label != canon:
            ensure_alias(db, theme_id, old_label, created_by="user", confidence=0.98)
    if body.description is not None:
        theme.description = body.description
    db.commit()
    db.refresh(theme)
    return ThemeIdLabelOut(id=theme.id, canonical_label=theme.canonical_label)


@app.delete("/admin/themes/{theme_id}")
def delete_theme(theme_id: int, db: Session = Depends(get_db)):
    """Delete a theme and all related data (narratives, evidence, aliases, instruments, daily stats, etc.)."""
    theme = db.query(Theme).filter(Theme.id == theme_id).one_or_none()
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")
    # Delete tables that reference theme_id but are not ORM cascade from Theme
    db.query(ThemeMergeReinforcement).filter(ThemeMergeReinforcement.target_theme_id == theme_id).delete(
        synchronize_session="fetch"
    )
    db.query(ThemeMentionsDaily).filter(ThemeMentionsDaily.theme_id == theme_id).delete(synchronize_session="fetch")
    db.query(ThemeRelationDaily).filter(ThemeRelationDaily.theme_id == theme_id).delete(synchronize_session="fetch")
    db.query(ThemeSubThemeMetrics).filter(ThemeSubThemeMetrics.theme_id == theme_id).delete(synchronize_session="fetch")
    db.query(ThemeSubThemeMentionsDaily).filter(ThemeSubThemeMentionsDaily.theme_id == theme_id).delete(
        synchronize_session="fetch"
    )
    db.query(ThemeNarrativeSummaryCache).filter(ThemeNarrativeSummaryCache.theme_id == theme_id).delete(
        synchronize_session="fetch"
    )
    unfollow_theme(theme_id)
    db.delete(theme)
    db.commit()
    return Response(status_code=204)


@app.get("/admin/themes/diagnostic")
def theme_diagnostic(
    label: str = Query(..., description="Theme canonical_label (exact or partial)"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Explain why a theme may be missing from the network or have an empty share-of-voice chart.
    Network and metrics both filter by document timestamp (modified_at or received_at) in the last 6–12 months.
    """
    # Find theme(s) matching label (exact first, then ilike)
    theme = db.query(Theme).filter(Theme.canonical_label == label).first()
    if not theme:
        theme = db.query(Theme).filter(Theme.canonical_label.ilike(f"%{label}%")).first()
    if not theme:
        return {
            "found": False,
            "message": f"No theme with canonical_label matching '{label}'.",
            "hint": "Check spelling and try the exact label from the themes list.",
        }

    doc_ts = _doc_timestamp()
    since_6mo = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=6 * 31)
    since_12mo = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=12 * 31)

    narrative_count = db.query(Narrative).filter(Narrative.theme_id == theme.id).count()
    evidence_count = (
        db.query(Evidence.id)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .filter(Narrative.theme_id == theme.id)
        .count()
    )

    # Date range of documents that have evidence for this theme
    date_range = (
        db.query(func.min(doc_ts), func.max(doc_ts))
        .select_from(Evidence)
        .join(Narrative, Evidence.narrative_id == Narrative.id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(Narrative.theme_id == theme.id)
        .first()
    )
    min_ts, max_ts = date_range if date_range else (None, None)
    min_doc_date = min_ts.date() if min_ts else None
    max_doc_date = max_ts.date() if max_ts else None

    # Evidence count in network/metrics windows
    in_6mo = (
        db.query(Evidence.id)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(Narrative.theme_id == theme.id, doc_ts >= since_6mo)
        .count()
    )
    in_12mo = (
        db.query(Evidence.id)
        .join(Narrative, Narrative.id == Evidence.narrative_id)
        .join(Document, Evidence.document_id == Document.id)
        .filter(Narrative.theme_id == theme.id, doc_ts >= since_12mo)
        .count()
    )

    daily_rows = (
        db.query(ThemeMentionsDaily)
        .filter(ThemeMentionsDaily.theme_id == theme.id)
        .count()
    )

    return {
        "found": True,
        "theme_id": theme.id,
        "canonical_label": theme.canonical_label,
        "narrative_count": narrative_count,
        "evidence_count": evidence_count,
        "document_date_range": {
            "min": str(min_doc_date) if min_doc_date else None,
            "max": str(max_doc_date) if max_doc_date else None,
        },
        "network_and_metrics_window": "Documents are included only if document date (modified_at or received_at) is within the last 6 or 12 months.",
        "evidence_in_last_6_months": in_6mo,
        "evidence_in_last_12_months": in_12mo,
        "appears_in_network_6mo": in_6mo > 0,
        "appears_in_network_12mo": in_12mo > 0,
        "theme_mentions_daily_rows": daily_rows,
        "share_of_voice_source": "ThemeMentionsDaily (run daily aggregations) or computed from Evidence when empty.",
        "reason_network_missing": (
            "Theme has no evidence on documents dated within the last 6/12 months."
            if (in_6mo == 0 and in_12mo == 0) and evidence_count > 0
            else "Theme has no evidence at all."
            if evidence_count == 0
            else "Only in 12-month window. Switch the network to '1 year' to see this theme."
            if in_6mo == 0 and in_12mo > 0
            else None
        ),
        "reason_chart_empty": (
            "No evidence in the last 6/12 months, so no data points in the chart range."
            if (in_6mo == 0 and in_12mo == 0) and evidence_count > 0
            else "No evidence for this theme."
            if evidence_count == 0
            else "Try '1 year' on the theme page so the chart includes older document dates."
            if in_6mo == 0 and in_12mo > 0
            else None
        ),
    }


@app.get("/admin/themes/suggest-merges", response_model=SuggestMergesOut)
def suggest_theme_merges(
    db: Session = Depends(get_db),
    embedding_threshold: Optional[float] = Query(None, ge=0.0, le=1.0, description="Min cosine similarity for label embedding (default from settings)"),
    content_embedding_threshold: Optional[float] = Query(None, ge=0.0, le=1.0, description="Min cosine similarity for content embedding"),
    use_llm: bool = Query(False, description="Use LLM to suggest merge groups"),
    use_content_embedding: bool = Query(True, description="Use content (narratives+quotes) embedding"),
    require_both_embeddings: Optional[bool] = Query(None, description="Only merge when both label and content similarity pass"),
):
    """
    Suggest theme merge groups (dry run): themes that refer to the same investment thesis.
    Uses embedding similarity (label + content), and optionally LLM. Pass query params to override merge parameters.
    """
    opts = MergeOptions(
        embedding_threshold=embedding_threshold,
        content_embedding_threshold=content_embedding_threshold,
        use_llm=use_llm,
        use_content_embedding=use_content_embedding,
        require_both_embeddings=require_both_embeddings,
    )
    merge_sets = compute_merge_candidates(db, options=opts)
    suggestions = [
        SuggestMergeGroupOut(
            theme_ids=ms.theme_ids,
            labels=ms.labels if ms.labels else [str(t) for t in ms.theme_ids],
            canonical_theme_id=ms.canonical_theme_id,
        )
        for ms in merge_sets
    ]
    return SuggestMergesOut(suggestions=suggestions)


@app.post("/admin/themes/merge", response_model=ThemeMergeOut)
def merge_themes(body: ThemeMergeRequest, db: Session = Depends(get_db)) -> ThemeMergeOut:
    """
    Merge source theme into target: move narratives, aliases, daily stats; delete source theme.
    """
    narratives_moved = execute_theme_merge(db, body.source_theme_id, body.target_theme_id)
    db.commit()
    return ThemeMergeOut(
        merged=True,
        source_theme_id=body.source_theme_id,
        target_theme_id=body.target_theme_id,
        narratives_moved=narratives_moved,
    )


@app.post("/admin/themes/reassign-narratives", response_model=ReassignNarrativesOut)
def reassign_narratives(body: ReassignNarrativesRequest, db: Session = Depends(get_db)) -> ReassignNarrativesOut:
    """
    Move selected narratives to a target theme. Use when narratives were miscategorized
    (e.g. metaX narratives under meta). If a narrative with the same statement already
    exists in the target theme, evidence is merged into it and the duplicate narrative is removed.
    """
    target = db.query(Theme).filter(Theme.id == body.target_theme_id).one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Target theme not found")
    moved = 0
    skipped = 0
    for nid in body.narrative_ids:
        narrative = db.query(Narrative).filter(Narrative.id == nid).one_or_none()
        if not narrative:
            continue
        existing = (
            db.query(Narrative)
            .filter(
                Narrative.theme_id == body.target_theme_id,
                Narrative.statement == narrative.statement,
            )
            .one_or_none()
        )
        if existing:
            # Same statement already in target: move evidence to existing narrative, then delete source
            db.query(Evidence).filter(Evidence.narrative_id == nid).update(
                {Evidence.narrative_id: existing.id},
                synchronize_session="fetch",
            )
            db.query(Narrative).filter(Narrative.id == nid).delete(synchronize_session="fetch")
            skipped += 1
        else:
            narrative.theme_id = body.target_theme_id
            moved += 1
    db.commit()
    return ReassignNarrativesOut(
        moved=moved,
        skipped=skipped,
        target_theme_id=body.target_theme_id,
        target_label=target.canonical_label,
    )


@app.post("/admin/re-extract")
def re_extract_documents(
    document_ids: Optional[list[int]] = Query(None, description="Document IDs to re-extract (omit for ALL)"),
    last: Optional[int] = Query(None, description="If set, re-extract only the N most recently completed ingest(s); e.g. last=1 for last doc only. Ignores document_ids when set."),
    db: Session = Depends(get_db),
) -> dict:
    """
    Re-extract themes/narratives for existing documents using the current prompt.
    Deletes old evidence for the selected document(s) and requeues their ingest jobs.
    Use ?last=1 to re-extract only the most recently completed document (safe default).
    """
    if last is not None and last > 0:
        jobs = (
            db.query(IngestJob)
            .filter(IngestJob.status == "done")
            .order_by(IngestJob.finished_at.desc().nullslast())
            .limit(last)
            .all()
        )
    elif document_ids:
        jobs = (
            db.query(IngestJob)
            .filter(IngestJob.document_id.in_(document_ids), IngestJob.status == "done")
            .all()
        )
    else:
        jobs = db.query(IngestJob).filter(IngestJob.status == "done").all()

    if not jobs:
        return {"requeued": 0, "message": "No completed ingest jobs found to re-extract."}

    doc_ids_to_requeue = [j.document_id for j in jobs]

    # Clear all extraction-derived data for these documents (avoids duplicate/stale narratives and quotes)
    deleted_evidence = (
        db.query(Evidence)
        .filter(Evidence.document_id.in_(doc_ids_to_requeue))
        .delete(synchronize_session="fetch")
    )

    # Remove narratives that no longer have any evidence (e.g. only cited this document)
    from sqlalchemy import exists
    orphan_ids = [
        r[0]
        for r in db.query(Narrative.id)
        .filter(~exists().where(Evidence.narrative_id == Narrative.id))
        .all()
    ]
    deleted_narratives = 0
    if orphan_ids:
        deleted_narratives = (
            db.query(Narrative)
            .filter(Narrative.id.in_(orphan_ids))
            .delete(synchronize_session="fetch")
        )

    # Clear document summaries so UI does not show stale takeaways until worker repopulates
    db.query(Document).filter(Document.id.in_(doc_ids_to_requeue)).update(
        {"summary": None}, synchronize_session="fetch"
    )

    # Requeue the ingest jobs
    for j in jobs:
        j.status = "queued"
        j.started_at = None
        j.finished_at = None
        j.error_message = None
    db.commit()

    return {
        "requeued": len(jobs),
        "document_ids": doc_ids_to_requeue,
        "evidence_deleted": deleted_evidence,
        "orphan_narratives_deleted": deleted_narratives,
        "message": f"Requeued {len(jobs)} document(s) for re-extraction with current prompt. "
                   f"Deleted {deleted_evidence} old evidence rows and {deleted_narratives} orphaned narratives. "
                   "The worker will re-process them and populate sub_theme / narrative_stance / confidence_level.",
    }


@app.post("/admin/run-daily-aggregations")
def trigger_daily_aggregations(
    date: Optional[str] = None,
    generate_summaries: bool = Query(True, description="Also generate LLM narrative summaries for all themes"),
) -> dict:
    """
    Lightweight admin/debug endpoint so Cloud Scheduler (or a human)
    can trigger daily aggregations + LLM narrative summaries.
    """
    target_date = dt.date.fromisoformat(date) if date else None
    run_daily_aggregations(target_date)
    summaries_generated = 0
    if generate_summaries:
        db = next(get_db())
        try:
            summaries_generated = generate_theme_narrative_summaries(db)
        finally:
            db.close()
    return {
        "ok": True,
        "date": (target_date or dt.date.today()).isoformat(),
        "summaries_generated": summaries_generated,
    }


@app.post("/admin/generate-narrative-summaries")
def trigger_narrative_summaries(
    theme_id: Optional[int] = Query(None, description="Generate for a specific theme (omit for all)"),
    db: Session = Depends(get_db),
) -> dict:
    """Generate LLM narrative summaries for themes (past 30 days). Pre-computes what the theme page shows."""
    count = generate_theme_narrative_summaries(db, theme_id=theme_id)
    return {"ok": True, "summaries_generated": count}
