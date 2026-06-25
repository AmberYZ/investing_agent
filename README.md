# Investing Narrative Agent

Ingest PDFs (from a local watch folder), extract **themes**, **narratives**, and **supporting quotes**, store results in the cloud-ready database schema, and visualize theme/narrative trends over time.

## Repo layout

- `backend/`: FastAPI API + worker (PDF extraction + Vertex AI extraction + embeddings)
- `ingest-client/`: local folder watcher/uploader (Mac)
- `frontend/`: dashboard (Next.js) (scaffold)
- `infra/`: deployment notes/scripts (scaffold)

## Python version

This project targets **Python 3.10+** (3.12 recommended). Python 3.9 is past end of life; Google and other libraries may show warnings or drop support. Use a supported interpreter for the backend and ingest-client venvs.

- **macOS (Homebrew):** `brew install python@3.12` then `python3.12 -m venv .venv`
- **pyenv:** `pyenv install 3.12` then `pyenv local 3.12` (repo root has `.python-version`)

After upgrading, recreate the venv and reinstall deps (see below).

## Local dev quickstart (MVP)

1. Configure env (see **[ENV.md](ENV.md)** for the full list)

```bash
cp .env.example .env
# So the dashboard can reach the API:
cp frontend/.env.local.example frontend/.env.local
```

2. **Start everything** (one command)

```bash
./dev.sh
# or: ./start.sh
```

This starts the API, ingest worker, PDF watcher, and dashboard together. The worker and watcher **auto-restart** if they crash. Press **Ctrl+C** once to stop all services.

- Dashboard: http://localhost:3000
- API: http://127.0.0.1:8000
- Drop PDFs into **`watch_pdfs/`** at the repo root (or set `WATCH_DIR` in `.env`)

The script creates `backend/.venv`, installs Python deps, and frees ports 8000/3000 if they are still in use from a previous run.

### Running services separately (optional)

Use separate terminals only if you want isolated logs or to restart one service without touching the others:

| Terminal | Command | Purpose |
|----------|---------|---------|
| **1** | `cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` | API |
| **2** | `cd backend && .venv/bin/python -m app.worker` | Ingest worker |
| **3** | `cd ingest-client && ../backend/.venv/bin/python -m ingest_client.watcher` | PDF watcher |
| **4** | `cd frontend && npm run dev` | Dashboard |

If port 8000 is in use: `lsof -ti:8000 | xargs kill -9` (macOS/Linux).

### Manual setup (without dev.sh)

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

In other terminals: `.venv/bin/python -m app.worker`, ingest watcher, and `cd frontend && npm run dev`.

For **local dev you do not need** the Google Cloud stack (no `grpcio` build). If you later enable GCS or Vertex AI, run `pip install -r requirements-gcp.txt` in the same venv.

## GCP / Vertex AI setup notes

If you want **cloud storage + Gemini extraction**:

1. Install GCP dependencies (avoids `grpcio` wheel issues for local-only dev):
   ```bash
   cd backend && source .venv/bin/activate
   pip install -r requirements-gcp.txt
   ```
2. Set `STORAGE_BACKEND=gcs`, `GCS_BUCKET=...`
3. Set `ENABLE_VERTEX=true`, `GCP_PROJECT=...`, `GCP_LOCATION=...`
4. Ensure Application Default Credentials (ADC) are available via `GOOGLE_APPLICATION_CREDENTIALS`

The ingest client always calls `POST /ingest-file`; the backend then writes the PDF to the configured storage backend (local filesystem or GCS).

## Optional: Postgres locally

If you install Docker, you can run Postgres locally via:

```bash
docker compose up -d db
```

Then set `DATABASE_URL` in `.env` to a Postgres URL (see `.env.example` comments) and restart the API/worker.

## Troubleshooting

### Python 3.9 / google-auth warning

If you see a warning that Python 3.9 is past end of life and to upgrade: install Python 3.12 (e.g. `brew install python@3.12` or `pyenv install 3.12`), then recreate the venvs and reinstall dependencies:

```bash
cd backend
rm -rf .venv
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
# If you use GCS/Vertex:
.venv/bin/pip install -r requirements-gcp.txt
```

Do the same for `ingest-client/` if you use its venv. Then restart the API and worker.

### pip “dependency conflicts” after install

If you see “dependency conflicts” involving `minimagen`, `tensorflow`, `wandb`, `jupyter-server`, etc., pip is warning about **other packages** already installed in that Python environment, not about this project’s requirements. The install usually still succeeds (exit code 0).

To avoid mixing with those packages, use a **dedicated venv** for the backend so only this project’s deps are installed:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then run the API with `.venv/bin/python -m uvicorn app.main:app --reload --port 8000` (see table above).

### `ERROR: Failed building wheel for grpcio`

**Local dev (sqlite + local storage)** no longer installs Google Cloud packages, so you shouldn’t see this. Use only:

```bash
pip install -r requirements.txt
```

If you need **GCS or Vertex AI**, install the optional GCP deps and hit this error:

1. **Upgrade pip** then install GCP deps: `pip install --upgrade pip && pip install -r requirements-gcp.txt`
2. **On macOS**, install Xcode Command Line Tools: `xcode-select --install`
3. Use Python 3.10+ for the venv (3.12 recommended; 3.9 is EOL): `python3.12 -m venv .venv`, then remove the old `.venv` and reinstall: `pip install -r requirements.txt` (and `requirements-gcp.txt` if needed).

