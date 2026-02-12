# Environment variables – where to set them

The app uses **two** env locations. Set these so the dashboard can reach the API and the ingest client can find the watch folder and API.

---

## 1. Repo root `.env`

Used by: **backend API**, **ingest worker**, **ingest client**.

```bash
# From repo root
cp .env.example .env
# Then edit .env
```

| Variable | Required | Default / example | Notes |
|----------|----------|-------------------|--------|
| `DATABASE_URL` | Yes | `sqlite:///./dev.db` | Or Postgres: `postgresql+psycopg://postgres:postgres@localhost:5432/narratives` |
| `API_BASE_URL` | For ingest client | `http://localhost:8000` | Ingest client uses this to call the API. |
| `STORAGE_BACKEND` | No | `local` | `local` or `gcs`. |
| `GCS_BUCKET` | If `STORAGE_BACKEND=gcs` | — | GCS bucket name. |
| `GCS_PREFIX` | No | `investing-agent` | Prefix inside the bucket. |
| `LOCAL_STORAGE_DIR` | No | `.local_storage` | Used when `STORAGE_BACKEND=local`. |
| `GCP_PROJECT` | If using Vertex | — | GCP project for Gemini/embeddings. |
| `GCP_LOCATION` | No | `us-central1` | Vertex AI region. |
| `VERTEX_GEMINI_MODEL` | No | `gemini-2.0-flash` | Gemini model name. |
| `VERTEX_EMBED_MODEL` | No | `gemini-embedding-001` | Embedding model. |
| `ENABLE_VERTEX` | No | `false` | Set `true` to use Vertex for extraction/embeddings. |
| `LLM_PROVIDER` | No | `openai` | For API-key extraction: `openai` or `gemini`. |
| `LLM_API_KEY` | If using LLM extraction | — | API key (OpenAI, Gemini, DeepSeek, etc.). If set, theme extraction uses this instead of heuristic. See [LLM_SETUP.md](LLM_SETUP.md). |
| `LLM_MODEL` | No | `gpt-4o-mini` | Model name (e.g. `gemini-1.5-flash`, `deepseek-chat`). |
| `LLM_BASE_URL` | No | — | Optional; for OpenAI-compatible APIs (e.g. `https://api.deepseek.com`). |
| `LLM_DELAY_AFTER_REQUEST_SECONDS` | No | `0` | Optional delay in seconds after each LLM/Vertex extraction. Use e.g. `1.0` with 1000+ docs to avoid rate limits (OpenAI RPM). |
| `USE_HEURISTIC_EXTRACTION` | No | `false` | If `true`, always use heuristic extraction (no LLM/Vertex), ignoring `LLM_API_KEY` and Vertex. |
| `THEME_SIMILARITY_USE_EMBEDDING` | No | `true` | Use Vertex embedding similarity for theme deduplication when Vertex is enabled. |
| `THEME_SIMILARITY_USE_TEXT` | No | `true` | Use token (Dice) text similarity for theme deduplication; no API required. |
| `THEME_SIMILARITY_EMBEDDING_THRESHOLD` | No | `0.92` | Min cosine similarity (0–1) to merge themes via embedding. |
| `THEME_SIMILARITY_TEXT_THRESHOLD` | No | `0.7` | Min Dice coefficient (0–1) to merge themes via token similarity. |
| `LOG_FILE` | No | — | Optional path for backend log file (worker + API). Example: `backend/logs/backend.log`. Leave unset for stdout only. |
| `ENABLE_AUTH` | No | `false` | Future: API auth. |
| `WATCH_DIR` | No | `watch_pdfs/` | If unset or the path doesn’t exist, the ingest client uses **`watch_pdfs/`** at the repo root (created automatically). Drop PDFs there and they’ll be ingested. You can set `WATCH_DIR` to any other folder (e.g. your WeChat download folder). |
| `POLL_SECONDS` | No | `5` | How often the ingest client scans the watch folder. |

**Example – in repo root `.env`:**  
To use a specific folder (e.g. your desktop test folder), add this line with **no quotes** and **no spaces around `=`**:

```bash
WATCH_DIR=/Users/bigoneamberzhang/Desktop/investing_agent_test
```

The path must exist on disk. Restart the ingest client (or `./dev.sh`) after changing `.env`.

---

## 2. Frontend `.env.local`

Used by: **Next.js dashboard** (so it knows the API URL when rendering and in the browser).

**If this is missing or wrong, you get errors like “Failed to fetch themes” or fetch errors for `/themes`, `/themes/{id}`, etc.**

```bash
# From repo root
cp frontend/.env.local.example frontend/.env.local
# Then edit if your API is not on localhost:8000
```

| Variable | Required | Default / example | Notes |
|----------|----------|-------------------|--------|
| `NEXT_PUBLIC_API_BASE_URL` | Yes | `http://localhost:8000` | **Must** point at your running backend API (no trailing slash). Use `http://127.0.0.1:8000` if localhost is unreliable. |

After changing `.env.local`, restart the Next.js dev server (`npm run dev` or `./dev.sh`).

---

## Quick checklist

- [ ] **Repo root:** `cp .env.example .env` and set at least `WATCH_DIR` (and `DATABASE_URL` if using Postgres).
- [ ] **Frontend:** `cp frontend/.env.local.example frontend/.env.local` and set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` (or your API URL).
- [ ] Backend API is running (e.g. `uvicorn app.main:app --port 8000` or `./dev.sh`).
- [ ] Restart the frontend after editing `frontend/.env.local`.
