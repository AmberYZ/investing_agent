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

2. Run backend API (defaults: sqlite + local storage; Vertex disabled)

```bash
cd backend
python3.12 -m venv .venv   # or python3 if that’s already 3.10+
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```
(Using `.venv/bin/python` avoids "no module named 'fastapi'" if the venv isn’t activated.)

For **local dev you do not need** the Google Cloud stack (no `grpcio` build). If you later enable GCS or Vertex AI, run `pip install -r requirements-gcp.txt` in the same venv.

3. Run worker (separate terminal)

```bash
cd backend
.venv/bin/python -m app.worker
```

4. Run local ingest client (separate terminal)

```bash
cd ingest-client
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ingest_client.watcher
```

5. Run the dashboard (separate terminal)

```bash
cd frontend
npm install && npm run dev
```

Open http://localhost:3000.

**To see themes on the dashboard:** the ingest client is already running (no separate terminal needed). Drop PDF files into the **`watch_pdfs/`** folder at the repo root; it is created automatically if you don’t set `WATCH_DIR` in `.env`. The watcher will upload them and the worker will extract themes (using heuristics by default; set `ENABLE_VERTEX=true` for Gemini extraction). You can instead set `WATCH_DIR` in `.env` to any folder that already contains PDFs.

### One command: `./dev.sh`

From the repo root, run `./dev.sh` to start backend, worker, ingest client, and frontend together. The script **frees port 8000** before starting so the backend always runs the latest code (avoids "Backend may be running old code" from the ingest client). Press Ctrl+C to stop everything.

### Running backend and frontend separately (recommended for development)

Running each service in its own terminal makes it easy to **restart only the backend** after code changes and keeps logs separate.

| Terminal | Command | Purpose |
|----------|---------|---------|
| **1** | `cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` | API (restart this when you change backend code) |
| **2** | `cd backend && .venv/bin/python -m app.worker` | Ingest worker |
| **3** | `cd ingest-client && .venv/bin/python -m ingest_client.watcher` | PDF watcher (uses watch dirs from API or config file) |
| **4** | `cd frontend && npm run dev` | Dashboard at http://localhost:3000 |

If something was already using port 8000, free it first: `lsof -ti:8000 | xargs kill -9` (macOS/Linux), then start the backend in terminal 1.

**Stopping the ingest client:** The watcher runs until you stop it. If you used `./dev.sh`, press **Ctrl+C** in that terminal once to stop all services (backend, worker, ingest client, frontend). If you started the ingest client in its own terminal (e.g. terminal 3 above), go to that terminal and press **Ctrl+C** to stop only the watcher. To find and kill the watcher process: `pkill -f ingest_client.watcher`.

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

### `ERROR: Failed building wheel for grpcio`

**Local dev (sqlite + local storage)** no longer installs Google Cloud packages, so you shouldn’t see this. Use only:

```bash
pip install -r requirements.txt
```

If you need **GCS or Vertex AI**, install the optional GCP deps and hit this error:

1. **Upgrade pip** then install GCP deps: `pip install --upgrade pip && pip install -r requirements-gcp.txt`
2. **On macOS**, install Xcode Command Line Tools: `xcode-select --install`
3. Use Python 3.10+ for the venv (3.12 recommended; 3.9 is EOL): `python3.12 -m venv .venv`, then remove the old `.venv` and reinstall: `pip install -r requirements.txt` (and `requirements-gcp.txt` if needed).

