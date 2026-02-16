# Maintenance Audit – Investing Agent

Reference document for functionalities, algorithms, configuration, unused code/tables, LLM usage, memory assessment, and helper scripts. Use this like a PRD for maintenance and onboarding.

---

## 1. Functionalities, Algorithms, Config, and Parameters

### A. Document Ingestion Pipeline

| Functionality | Location | Description |
|---------------|----------|-------------|
| PDF upload (metadata) | `backend/app/main.py` | `POST /ingest` – ingest by metadata (filename, source, optional GCS URI) |
| PDF upload (file) | `backend/app/main.py` | `POST /ingest-file` – multipart upload and ingest |
| Background worker | `backend/app/worker.py` | Polls for queued jobs, processes one at a time |
| PDF text extraction | `backend/app/extract/pdf_text.py` | PyMuPDF-based extraction |
| Disclosure trim | `backend/app/extract/disclosure_trim.py` | Removes legal/disclosure sections before LLM |
| Text chunking | `backend/app/extract/chunking.py` | Chunk size 1800 chars, overlap 200 (configurable in code) |
| Embedding generation | `backend/app/llm/embeddings.py` | OpenAI or Vertex; batch size 20 |

**Config / .env (where to change):** Root `.env`. Backend reads via `backend/app/settings.py`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `STORAGE_BACKEND` | `local` | `local` or `gcs` |
| `LOCAL_STORAGE_DIR` | `.local_storage` | Local storage path |
| `GCS_BUCKET` | (empty) | GCS bucket when `STORAGE_BACKEND=gcs` |
| `GCS_PREFIX` | `investing-agent` | Prefix inside bucket |
| `MAX_QUEUED_INGEST_JOBS` | `0` | Cap on queued+processing jobs; 0 = no cap |
| `PAUSE_INGEST` | `false` | When true, reject all new ingest requests |

---

### B. Theme/Narrative Extraction (LLM)

| Functionality | Location | Description |
|---------------|----------|-------------|
| LLM extraction (API key) | `backend/app/llm/api_extract.py` | OpenAI, Gemini, or OpenAI-compatible; structured JSON extraction |
| Vertex extraction | `backend/app/llm/vertex.py` | Vertex AI Gemini when `ENABLE_VERTEX=true` |
| Heuristic fallback | `backend/app/llm/heuristic.py` | Word-frequency extraction; no LLM |
| Prompt template | `backend/app/prompts/extract_themes_default.txt` | Default prompt; user-editable via `PUT /settings/extraction-prompt` |

**Config / .env:** Root `.env` → `backend/app/settings.py`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `openai` | `openai` \| `gemini` \| `openai_compatible` |
| `LLM_API_KEY` | (empty) | API key; if unset, heuristic extraction used |
| `LLM_MODEL` | `gpt-4o-mini` | Model name |
| `LLM_BASE_URL` | (empty) | Base URL for OpenAI-compatible APIs |
| `LLM_TIMEOUT_SECONDS` | `180` | Request timeout |
| `LLM_DELAY_AFTER_REQUEST_SECONDS` | `0.0` | Delay after each LLM call (rate limiting) |
| `USE_HEURISTIC_EXTRACTION` | `false` | Force heuristic only; no LLM/Vertex |
| `ENABLE_VERTEX` | `false` | Use Vertex for extraction/embeddings |
| `VERTEX_GEMINI_MODEL` | `gemini-2.0-flash` | Vertex Gemini model |
| `VERTEX_EMBED_MODEL` | `gemini-embedding-001` | Vertex embedding model |

---

### C. Theme Deduplication and Merging

| Functionality | Location | Description |
|---------------|----------|-------------|
| Resolution during ingest | `backend/app/worker.py` | Exact match → alias → embedding similarity → Dice text similarity |
| Admin merge suggestions | `backend/app/theme_merge.py` | Label + optional content embedding; optional LLM suggestions |
| LLM merge suggestions | `backend/app/llm/suggest_merges.py` | When `THEME_MERGE_USE_LLM_SUGGEST=true` |
| Merge reinforcement | `backend/app/theme_merge.py` | Store source label+embedding; resolve new labels to merged theme during extraction |

**Config / .env:** Root `.env` → `backend/app/settings.py` (lines 46–64).

| Variable | Default | Purpose |
|----------|---------|---------|
| `THEME_SIMILARITY_USE_EMBEDDING` | `true` | Use embedding similarity when provider available |
| `THEME_SIMILARITY_USE_TEXT` | `true` | Use Dice text similarity |
| `THEME_SIMILARITY_EMBEDDING_THRESHOLD` | `0.92` | Min cosine similarity to merge (0–1) |
| `THEME_SIMILARITY_TEXT_THRESHOLD` | `0.7` | Min Dice coefficient (0–1) |
| `THEME_MERGE_SUGGESTION_EMBEDDING_THRESHOLD` | `0.92` | Label embedding threshold for suggest-merges |
| `THEME_MERGE_USE_LLM_SUGGEST` | `false` | Use LLM to suggest merge groups |
| `THEME_MERGE_USE_CONTENT_EMBEDDING` | `false` | Use narratives+quotes for content embedding |
| `THEME_MERGE_CONTENT_EMBEDDING_THRESHOLD` | `0.90` | Content embedding similarity threshold |
| `THEME_MERGE_REQUIRE_BOTH_EMBEDDINGS` | `false` | Require both label and content similarity |
| `THEME_MERGE_CONTENT_WEIGHT` | `0.5` | Weight for content vs label (0=label only, 1=content only) |
| `THEME_MERGE_MAX_NARRATIVES_PER_THEME` | `5` | Max narratives per theme for content embedding |
| `THEME_MERGE_MAX_QUOTES_PER_THEME` | `8` | Max quotes per theme |
| `THEME_MERGE_MAX_QUOTE_CHARS` | `250` | Max characters per quote |
| `THEME_MERGE_REINFORCEMENT_ENABLED` | `true` | Use merge reinforcement during extraction |
| `THEME_MERGE_REINFORCEMENT_THRESHOLD` | `0.8` | Min cosine sim to resolve to reinforcement target |

---

### D. Daily Aggregation and Analytics

| Functionality | Location | Description |
|---------------|----------|-------------|
| Daily mention counts | `backend/app/aggregations.py` | Per narrative/theme/doc date; share-of-voice |
| Burst / accel / novelty | `backend/app/aggregations.py` | Per narrative; formulas in code |
| Sub-theme daily metrics | `backend/app/aggregations.py` (lines 240–265) | `ThemeSubThemeMentionsDaily` |
| Sub-theme metrics (novelty_type, narrative_stage) | `backend/app/aggregations.py` | `compute_sub_theme_metrics` |
| LLM narrative summaries | `backend/app/aggregations.py` | `generate_theme_narrative_summaries`; cached in `ThemeNarrativeSummaryCache` |
| Theme insights | `backend/app/insights.py` | Trajectory, consensus evolution, debate intensity |

**Triggered by:** `POST /admin/run-daily-aggregations` or Cloud Scheduler (2 AM UTC in production).

---

### E. Frontend Dashboard (Next.js)

#### Theme list (home page)

- **Route/entry:** `/` → `ThemesPageClient`
- **What it does:** Shows all active themes as cards with sparkline chart, latest metrics, and **“unread/updated” alert styling**.
- **User controls:**
  - **Volume range selector:** `months` query param from URL (`6` or `12` months) controls aggregation window and chart span.
  - **Sort order:** Backend `/themes` supports `sort=recent|label`; UI uses this to show either recently active or alphabetically ordered themes.
- **Unread / alert behavior (high‑level):**
  - Each theme has a `last_updated` timestamp from the backend.
  - Frontend stores **per‑theme `last_read_at`** timestamps in:
    - Browser `localStorage` (`investing-agent-read-theme-data`) and
    - A small in‑memory cache (for non‑browser contexts).
  - **A theme card shows as “new/updated” (alert style) when:**
    - The theme has recent activity, **and**
    - Either it has **never been read** or its current `last_updated` is **newer than** the stored `last_read_at`.
  - **Mark as read (per theme):**
    - Clicking a theme card (or explicit “mark read” UI) updates `last_read_at` for that `theme_id` to **now** via `markThemeAsRead` and the `/api/themes/read-status` API.
  - **Mark all as read:**
    - “Mark all” control calls `/api/themes/read-status` with `{ mark_all: true }`, which sets a **global `all_dismissed_at`** timestamp so that all current updates are considered “seen”.
  - **Backend persistence:**
    - `backend/app/theme_read_state.py` keeps a JSON file `theme_read_state.json` (theme_id → last read ISO timestamp) so read state **survives backend restarts** (MVP: single global store, not per‑user).

#### Theme detail page

- **Route:** `/themes/[id]`
- **What it does:** Deep‑dive on a single theme:
  - Time‑series charts for mentions, share of voice, stance mix, confidence levels, and sub‑themes.
  - LLM narrative summary (30‑day by default, cached in DB).
  - Theme insights: trajectory, consensus/debate, narrative shifts.
  - Lists of narratives with stance, confidence, and evidence quotes.
- **Key parameters:**
  - **Metrics window:** `months` (frontend) or default 6 months for the `/themes/{id}/metrics*` endpoints.
  - **Narratives list:** `/themes/{id}/narratives?date=today|since=YYYY-MM-DD` allows showing only today’s narratives or since a given date.

#### Theme network view

- **Route:** `/themes/network`
- **What it does:** Visualizes **co‑occurrence network** of themes (nodes sized by mentions, edges by co‑mentions).
- **Key parameters:**
  - `months` query param to `/themes/network` and `/themes/network/snapshots` controls look‑back window (default 6 months).

#### Document viewer

- **Route:** `/documents/[id]`
- **What it does:** Shows a single document:
  - Basic metadata (filename, received_at, summary).
  - Extracted plain text (with optional excerpts highlighted for evidence).
- **Key endpoints:**
  - `/documents/{id}` – metadata and URLs.
  - `/documents/{id}/excerpts` – key quotes for highlight.
  - `/documents/{id}/text` – full extracted text.

#### Admin pages

- **Admin dashboard:** `/admin`
  - High‑level view with tabs for failures, themes, settings, watch directories.
- **Ingest failures:** `/admin/failures`
  - Lists failed ingest jobs (from `/admin/ingest-failures`).
  - Buttons for **requeueing** error jobs and **cancelling** pending ones via admin endpoints.
- **Theme management:** `/admin/themes`
  - Lists themes with additional diagnostics.
  - Supports **merge operations** (select source/target theme, run merge) and optionally **suggest merges** using embedding + optional LLM.
  - Parameters surfaced from backend include thresholds like `embedding_threshold`, `content_threshold`, and `use_llm`.
- **Settings (extraction prompt):** `/admin/settings`
  - UI to view/edit the extraction prompt used for LLM/heuristic theme extraction.
  - Reads from `/settings/extraction-prompt` and writes via `PUT /settings/extraction-prompt`.
- **Watch directories:** `/admin/watch-dirs`
  - Displays and edits the list of directories that the ingest client should watch for PDFs.
  - Persists configuration in `watch_dirs.json` (and corresponding backend handlers).

**Frontend config:** `.env.local` → `NEXT_PUBLIC_API_BASE_URL` (backend API URL for all fetches).

---

### F. All API Endpoints

| Method | Path | Query / Body | Purpose |
|--------|------|--------------|---------|
| GET | `/health` | — | Health check |
| GET | `/metrics` | — | Prometheus metrics |
| POST | `/ingest` | Body: `IngestRequest` | Ingest by metadata |
| POST | `/ingest-file` | multipart/form-data | Upload and ingest file |
| GET | `/themes` | `sort=recent\|label` | List themes |
| GET | `/themes/contrarian-recent` | `days=14` | Themes with recent contrarian narratives |
| GET | `/themes/network` | `months=6` | Theme co-occurrence network |
| GET | `/themes/network/snapshots` | `months=6` | Monthly network snapshots |
| GET | `/themes/{theme_id}` | — | Theme with narratives |
| GET | `/themes/{theme_id}/documents` | — | Documents for theme |
| GET | `/themes/{theme_id}/narrative-summary` | `period=30d\|all` | Narrative summary (cached) |
| GET | `/themes/{theme_id}/insights` | `months=6` | Theme insights |
| GET | `/themes/{theme_id}/narrative-shifts` | — | Recent narrative shifts |
| GET | `/themes/{theme_id}/metrics` | `months=6` | Daily metrics |
| GET | `/themes/{theme_id}/metrics-by-stance` | `months=6` | Metrics by stance |
| GET | `/themes/{theme_id}/metrics-by-confidence` | `months=6` | Metrics by confidence |
| GET | `/themes/{theme_id}/stance-by-confidence` | `days=30` | Stance breakdown by confidence |
| GET | `/themes/{theme_id}/metrics-by-sub-theme` | `months=6` | Sub-theme metrics |
| GET | `/themes/{theme_id}/narratives` | `date=today\|since=YYYY-MM-DD` | Narratives for theme |
| GET | `/narratives/{narrative_id}` | — | Narrative with evidence |
| GET | `/narratives/{narrative_id}/metrics` | — | Narrative daily metrics |
| GET | `/documents/{document_id}` | — | Document details |
| GET | `/documents/{document_id}/excerpts` | — | Document excerpts (evidence quotes) |
| GET | `/documents/{document_id}/text` | — | Extracted plain text |
| GET | `/admin/ingest-failures` | `limit=50` | Failed ingest jobs |
| GET | `/admin/ingest-jobs` | `limit=500` | All ingest jobs |
| POST | `/admin/ingest-jobs/requeue` | — | Requeue error jobs |
| POST | `/admin/ingest-jobs/cancel-all` | — | Cancel all pending jobs |
| GET | `/admin/themes` | `sort=label\|recent` | Themes for admin |
| GET | `/admin/themes/diagnostic` | `label=...` | Theme diagnostic info |
| GET | `/admin/themes/suggest-merges` | `embedding_threshold`, `content_threshold`, `use_llm`, etc. | Suggest theme merges |
| POST | `/admin/themes/merge` | Body: `ThemeMergeRequest` | Execute theme merge |
| POST | `/admin/re-extract` | `document_ids=...` | Re-extract documents |
| POST | `/admin/run-daily-aggregations` | `date=YYYY-MM-DD`, `generate_summaries=true` | Run daily aggregations |
| POST | `/admin/generate-narrative-summaries` | `theme_id=...` (optional) | Generate narrative summaries |
| GET | `/settings/extraction-prompt` | — | Get extraction prompt |
| PUT | `/settings/extraction-prompt` | Body: `ExtractionPromptOut` | Update extraction prompt |

---

### G. Environment Variables – Full Table

**Where to change:** Root `.env` for backend/worker/ingest-client; `frontend/.env.local` for frontend. Backend loads via `backend/app/settings.py` (env_file `../.env`).

| Variable | Default | Purpose | Used by |
|----------|---------|---------|---------|
| `DATABASE_URL` | `sqlite:///./dev.db` | DB connection | Backend, worker |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Backend URL for ingest client | Ingest client |
| `STORAGE_BACKEND` | `local` | `local` or `gcs` | Backend, worker |
| `GCS_BUCKET` | (empty) | GCS bucket name | Backend, worker |
| `GCS_PREFIX` | `investing-agent` | GCS object prefix | Backend, worker |
| `LOCAL_STORAGE_DIR` | `.local_storage` | Local storage dir | Backend, worker |
| `GCP_PROJECT` | (empty) | GCP project (Vertex) | Backend, worker |
| `GCP_LOCATION` | `us-central1` | Vertex region | Backend, worker |
| `VERTEX_GEMINI_MODEL` | `gemini-2.0-flash` | Vertex Gemini model | Backend, worker |
| `VERTEX_EMBED_MODEL` | `gemini-embedding-001` | Vertex embed model | Backend, worker |
| `ENABLE_VERTEX` | `false` | Use Vertex AI | Backend, worker |
| `EMBEDDING_PROVIDER` | `auto` | `auto` \| `openai` \| `vertex` \| `none` | Backend, worker |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embed model | Backend, worker |
| `LLM_PROVIDER` | `openai` | `openai` \| `gemini` \| `openai_compatible` | Backend, worker |
| `LLM_API_KEY` | (empty) | LLM API key | Backend, worker |
| `LLM_MODEL` | `gpt-4o-mini` | LLM model name | Backend, worker |
| `LLM_BASE_URL` | (empty) | OpenAI-compatible base URL | Backend, worker |
| `LLM_TIMEOUT_SECONDS` | `180` | LLM request timeout | Backend, worker |
| `LLM_DELAY_AFTER_REQUEST_SECONDS` | `0.0` | Delay after each LLM call | Backend, worker |
| `USE_HEURISTIC_EXTRACTION` | `false` | No LLM; heuristic only | Backend, worker |
| `THEME_SIMILARITY_USE_EMBEDDING` | `true` | Embedding similarity for dedup | Backend, worker |
| `THEME_SIMILARITY_USE_TEXT` | `true` | Text (Dice) similarity | Backend, worker |
| `THEME_SIMILARITY_EMBEDDING_THRESHOLD` | `0.92` | Min cosine sim to merge | Backend, worker |
| `THEME_SIMILARITY_TEXT_THRESHOLD` | `0.7` | Min Dice coefficient | Backend, worker |
| `THEME_MERGE_SUGGESTION_EMBEDDING_THRESHOLD` | `0.92` | Label embedding threshold (suggest-merges) | Backend |
| `THEME_MERGE_USE_LLM_SUGGEST` | `false` | LLM merge suggestions | Backend |
| `THEME_MERGE_USE_CONTENT_EMBEDDING` | `false` | Content embedding for merges | Backend |
| `THEME_MERGE_CONTENT_EMBEDDING_THRESHOLD` | `0.90` | Content embedding threshold | Backend |
| `THEME_MERGE_REQUIRE_BOTH_EMBEDDINGS` | `false` | Require label + content sim | Backend |
| `THEME_MERGE_CONTENT_WEIGHT` | `0.5` | Content vs label weight | Backend |
| `THEME_MERGE_MAX_NARRATIVES_PER_THEME` | `5` | Max narratives for content embed | Backend |
| `THEME_MERGE_MAX_QUOTES_PER_THEME` | `8` | Max quotes per theme | Backend |
| `THEME_MERGE_MAX_QUOTE_CHARS` | `250` | Max quote length | Backend |
| `THEME_MERGE_REINFORCEMENT_ENABLED` | `true` | Merge reinforcement during extraction | Backend, worker |
| `THEME_MERGE_REINFORCEMENT_THRESHOLD` | `0.8` | Reinforcement similarity threshold | Backend, worker |
| `LOG_FILE` | (empty) | Backend log file path | Backend, worker |
| `MAX_QUEUED_INGEST_JOBS` | `0` | Cap on queued+processing jobs | Backend |
| `PAUSE_INGEST` | `false` | Reject new ingest requests | Backend |
| `ENABLE_AUTH` | `false` | API auth (MVP off) | Backend |
| `WATCH_DIR` | (defaults to `watch_pdfs/`) | Watch folder for PDFs | Ingest client |
| `POLL_SECONDS` | `5` | Watch folder poll interval | Ingest client |
| `HTTPS_PROXY` / `HTTP_PROXY` | (empty) | Proxy for LLM/API calls | Backend, worker |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend API URL | Frontend (`.env.local`) |

---

## 2. Unused Code

**Cleanup applied:** Dead code below has been removed (see migration `0010_drop_unused_tables_and_columns` and related code edits).

| Item | Location | Notes |
|------|----------|--------|
| **NarrativeAlias model** | `backend/app/models.py` lines 138–147 | Defined but never used in application logic; only referenced in `backend/scripts/clear_db.py` for cleanup. |
| **_update_narrative_status** | `backend/app/aggregations.py` lines 149–174 | Function is defined but its call is commented out at lines 305–311. Comment: "Labelling disabled: do not update narrative.status; to be reworked". |
| **Narrative.stance** | `backend/app/models.py` line 122 | Always set to `"unlabeled"` or `"neutral"`; LLM extractors hardcode `stance="neutral"` (api_extract.py, vertex.py, heuristic.py); worker sets `stance="unlabeled"`. The field `narrative_stance` (bullish/bearish/mixed/neutral) from LLM is used instead; old `stance` is effectively dead. |
| **Narrative.status** | `backend/app/models.py` line 127 | Always `"unlabeled"`; the function that would update it (`_update_narrative_status`) is commented out. |

---

## 3. Unused Database Tables and Columns

**Cleanup applied:** Tables and columns below have been dropped via migration `0010_drop_unused_tables_and_columns`.

| Item | Location | Status |
|------|----------|--------|
| **narrative_aliases** table | `backend/app/models.py` lines 138–147 | Never queried or inserted in application logic; only in `clear_db.py`. |
| **Document.language** | `backend/app/models.py` line 45 | Never set, never queried. |
| **Document.published_at** | `backend/app/models.py` line 39 | Never set, never queried. |
| **Document.source_metadata** | `backend/app/models.py` line 34 | Set during ingest but never queried. |
| **Evidence.chunk_id** | `backend/app/models.py` line 155 | Always set to `None` in `backend/app/worker.py` line 397; never queried. |
| **Evidence.confidence** | `backend/app/models.py` line 158 | Never set; always NULL. |
| **Narrative.stance** | `backend/app/models.py` line 122 | Always "unlabeled"/"neutral"; superseded by `narrative_stance`. |
| **Narrative.status** | `backend/app/models.py` line 127 | Always "unlabeled"; update logic commented out. |
| **feedback** table | `backend/app/models.py` lines 164–174 | Written to during theme merges (`backend/app/theme_merge.py` ~521); never read or queried elsewhere. |

---

## 4. Local Variables Storing Counts, Status, Switches

| Variable | Type | Location | Purpose |
|----------|------|----------|---------|
| `settings.pause_ingest` | bool | `backend/app/settings.py` | Checked in main.py:171–175; pauses all ingest. |
| `settings.max_queued_ingest_jobs` | int | `backend/app/settings.py` | Checked in main.py:160–167; 0 = no cap. |
| `settings.enable_auth` | bool | `backend/app/settings.py` | Auth toggle (MVP off). |
| `settings.enable_vertex` | bool | `backend/app/settings.py` | Vertex AI toggle. |
| `settings.use_heuristic_extraction` | bool | `backend/app/settings.py` | Force heuristic extraction; no LLM. |
| `settings.theme_merge_use_llm_suggest` | bool | `backend/app/settings.py` | LLM merge suggestions. |
| `settings.theme_merge_use_content_embedding` | bool | `backend/app/settings.py` | Content embedding for merges. |
| `settings.theme_merge_require_both_embeddings` | bool | `backend/app/settings.py` | Require both label and content similarity. |
| `settings.theme_merge_reinforcement_enabled` | bool | `backend/app/settings.py` | Merge reinforcement during extraction. |
| `_MAX_ENTRIES = 500` | int | `backend/app/theme_read_state.py` | Bounded cache for theme read/unread. |
| `_MAX_DOC_CHARS = 120_000` | int | `backend/app/llm/api_extract.py` | Max document characters sent to LLM. |

---

## 5. LLM Call Sites and Usage Tracking

### Chat completion (4 call sites)

| # | Function | File | Model config | Max tokens | Retry | Triggered by |
|---|----------|------|--------------|------------|-------|--------------|
| 1 | `extract_themes_and_narratives` | `backend/app/llm/api_extract.py` | `settings.llm_model` | 4096 | 5× exponential backoff | Worker per document |
| 2 | `extract_themes_and_narratives` | `backend/app/llm/vertex.py` | `settings.vertex_gemini_model` | 4096 | 3× | Worker when `ENABLE_VERTEX=true` |
| 3 | `generate_theme_narrative_summaries` | `backend/app/aggregations.py` | `settings.llm_model` | 2048 | — | Daily aggregation; cached in `ThemeNarrativeSummaryCache` |
| 4 | `suggest_theme_merge_groups` | `backend/app/llm/suggest_merges.py` | `settings.llm_model` | 4096 | 3× | `GET /admin/themes/suggest-merges?use_llm=true` |

### Embeddings (2 sites)

| Function | File | Batch size | Used by |
|----------|------|------------|---------|
| `embed_texts` | `backend/app/llm/embeddings.py` | 20 | Worker (theme resolution), theme_merge (content embedding) |
| `embed_texts` (Vertex) | `backend/app/llm/vertex.py` | — | Same when Vertex enabled |

### Current usage tracking

- **Logged:** `input_len` (and provider/model) in logs.
- **Not implemented:** Token counting, cost tracking, usage dashboard.

**Recommendation:** Add token/cost tracking (e.g. response usage, cumulative counters) if you need budget or rate-limit visibility.

---

## 6. Memory Leak Assessment

- **No significant memory leaks identified.**
- **DB sessions:** Closed in `finally` blocks in `backend/app/db.py`, `backend/app/worker.py`, `backend/app/aggregations.py`.
- **File handles:** PDF documents closed with `doc.close()` in `finally` in `backend/app/extract/pdf_text.py`.
- **Connection pooling:** SQLite uses `NullPool`; PostgreSQL uses `pool_recycle=300` in `backend/app/db.py`.
- **Theme read state:** Bounded cache `_MAX_ENTRIES = 500` in `backend/app/theme_read_state.py`.

**Minor considerations:**

- **theme_merge.py** – `_candidates_content_embedding()`: `all_embeddings` list grows with theme count; temporary per request but can be large with 1000+ themes.
- **main.py** – Network aggregation: dicts `label_to_ids`, `label_mentions`, `label_pair_count` grow with theme count; properly scoped but unbounded.

---

## 7. Helper Scripts and Curl Examples

### Python scripts (backend)

Run from `backend/` with `.venv` active (e.g. `cd backend && .venv/bin/python scripts/...`).

| Script | Purpose |
|--------|---------|
| `scripts/cancel_ingest_jobs.py` | Cancel all queued/processing ingest jobs |
| `scripts/clear_db.py` | Wipe database |
| `scripts/fix_alembic_revision.py` | Fix Alembic revision issues |
| `scripts/list_ingest_jobs.py` | List ingest jobs as JSON (optional limit arg) |
| `scripts/requeue_error_ingest_jobs.py` | Requeue failed ingest jobs |
| `scripts/requeue_stuck_ingest_jobs.py` | Requeue stuck ingest jobs |
| `scripts/run_theme_merges.py` | Run theme merge operations |
| `scripts/run_theme_sub_theme_metrics.py` | Compute sub-theme metrics |

### Shell script

| Script | Purpose |
|--------|---------|
| `dev.sh` | Start backend, worker, ingest client, and frontend (from repo root) |

### Admin API endpoints (curl-able)

Base URL assumed: `http://127.0.0.1:8000`.

```bash
# Health check
curl -sf "http://127.0.0.1:8000/health"

# Run daily aggregations (optional date; default today)
curl -X POST "http://127.0.0.1:8000/admin/run-daily-aggregations?date=2025-02-10&generate_summaries=true"

# Generate narrative summaries for all themes, or one theme
curl -X POST "http://127.0.0.1:8000/admin/generate-narrative-summaries"
curl -X POST "http://127.0.0.1:8000/admin/generate-narrative-summaries?theme_id=320"

# Ingest jobs
curl -X POST "http://127.0.0.1:8000/admin/ingest-jobs/requeue"
curl -X POST "http://127.0.0.1:8000/admin/ingest-jobs/cancel-all"
curl "http://127.0.0.1:8000/admin/ingest-failures?limit=50"
curl "http://127.0.0.1:8000/admin/ingest-jobs?limit=500"

# Theme merge suggestions (optional LLM)
curl "http://127.0.0.1:8000/admin/themes/suggest-merges?embedding_threshold=0.92&use_llm=false"

# Merge two themes (POST body)
curl -X POST "http://127.0.0.1:8000/admin/themes/merge" \
  -H "Content-Type: application/json" \
  -d '{"source_theme_id": 1, "target_theme_id": 2}'

# Re-extract documents
curl -X POST "http://127.0.0.1:8000/admin/re-extract?document_ids=1,2,3"

# Admin theme list and diagnostic
curl "http://127.0.0.1:8000/admin/themes?sort=label"
curl "http://127.0.0.1:8000/admin/themes/diagnostic?label=SomeTheme"
```

---

*Last updated from codebase maintenance audit. For env details see also `ENV.md` and `.env.example`; for LLM setup see `LLM_SETUP.md`.*

# Re-extract only the last completed ingest (e.g. the last Gmail)
curl -X POST "http://127.0.0.1:8000/admin/re-extract?last=1"


# Dry-run extraction and compare different LLM models. 
 curl -X POST "http://localhost:8000/admin/extraction-dry-run" \
  -H "Content-Type: application/json" \
  -d '{"document_id": 1184, "models": ["gpt-4o-mini", "gpt-4o"]}'