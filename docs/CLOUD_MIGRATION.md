# Cloud Migration Guide (Beyond GCS File Storage)

You’ve moved file storage to Google Cloud Storage. Here’s what else you can move to the cloud to save local space and run more in GCP.

---

## 1. **Database: SQLite → Cloud SQL (Postgres)**

**What:** Your app already supports Postgres. Moving from local `dev.db` (SQLite) to Cloud SQL removes the database file from your machine and keeps all themes, documents, and caches in the cloud.

**Benefits:**
- No local `dev.db` (can grow large with many documents).
- Same database can be used by Cloud Run when you deploy.
- Backups and durability handled by GCP.

**How:**

1. **Provision Cloud SQL** (if not already):
   ```bash
   cd infra/terraform
   terraform init && terraform apply
   ```
   Provide `db_password`, `api_image`, `worker_image`, `aggregator_image` (images can be placeholders if you only want the DB for now).

2. **Connect from your Mac** using the Cloud SQL Auth Proxy:
   ```bash
   brew install cloud-sql-proxy  # or download from Google
   cloud-sql-proxy INSTANCE_CONNECTION_NAME
   ```
   Get `INSTANCE_CONNECTION_NAME` from Terraform output or GCP Console (e.g. `project:region:investing-agent-pg`).

3. **Point the app at Postgres** in `.env`:
   ```env
   # Replace with your Terraform vars (db_user, db_password, db_name)
   DATABASE_URL=postgresql+psycopg://appuser:YOUR_DB_PASSWORD@127.0.0.1:5432/narratives
   ```

4. **Run migrations** (from repo root or `backend/`):
   ```bash
   cd backend && alembic upgrade head
   ```

5. **Optional:** Export existing SQLite data and import into Postgres, or start fresh on Cloud SQL. After switching, you can remove `dev.db` to free local space.

---

## 2. **State Files (theme read state, followed themes, watch dirs)**

**What:** JSON files under `backend/app/prompts/` (or `STATE_DIR`): `theme_read_state.json`, `followed_themes.json`, `watch_dirs.json`.

**Options:**

- **A) Cloud-synced folder (no code changes)**  
  Set in `.env`:
  ```env
  STATE_DIR=/path/to/Google Drive/InvestingAgentState
  ```
  Create that folder in Google Drive (or Dropbox), so state is synced and not only on one machine. The app already uses `STATE_DIR` when set.

- **B) Store state in GCS (code change)**  
  You could add a small “state backend” that reads/writes these JSON files from your existing GCS bucket (e.g. `gs://your-bucket/investing-agent/state/...`). Then when `STORAGE_BACKEND=gcs`, state would live in the cloud and nothing would be stored under `backend/app/prompts/` on disk. This would require adding state read/write via your existing GCS storage layer.

---

## 3. **Logs**

**What:** Optional `LOG_FILE` in `.env` writes backend logs to a file.

**Recommendation:**
- **Local:** Leave `LOG_FILE` empty to only use stdout and avoid log files on disk.
- **Cloud Run:** Don’t set `LOG_FILE`; Cloud Run sends stdout/stderr to **Cloud Logging** automatically.

---

## 4. **Run the Backend on Cloud Run (full cloud)**

**What:** Your Terraform already provisions Cloud Run services (API, worker, aggregator), Cloud SQL, GCS, Pub/Sub, and Cloud Scheduler. If you build and deploy the container images, the entire backend runs in GCP.

**Benefits:**
- No local backend process and no local DB or file storage (everything in Cloud SQL + GCS).
- Ingest queue runs on Pub/Sub; worker scales with load.
- Daily aggregation runs on a schedule in the cloud.

**Steps (high level):**
1. Build and push API, worker, and aggregator images to Artifact Registry (or another registry Terraform can use).
2. Run `terraform apply` with the image URLs.
3. Point the frontend’s API base URL at the Cloud Run API URL.
4. Optionally host the frontend on Vercel or Cloud Run so the whole app is in the cloud.

After that, you only need the repo (and optionally the frontend) locally; the heavy data and compute live in GCP.

---

## Summary

| Item              | Where it lives now       | Move to                          |
|-------------------|--------------------------|----------------------------------|
| **Files (PDFs, etc.)** | ~~Local / GCS~~          | ✅ Already GCS                   |
| **Database**      | SQLite `dev.db`          | Cloud SQL (Postgres)             |
| **State JSON**    | `backend/app/prompts/`   | `STATE_DIR` → Drive or GCS       |
| **Logs**          | Optional local file      | Leave unset or use Cloud Logging |
| **Backend process** | Local Python            | Cloud Run (API + worker + aggregator) |

**Suggested order:**  
1) Switch to Cloud SQL and run migrations (biggest local space win).  
2) Set `STATE_DIR` to a Google Drive folder if you want state in the cloud without code changes.  
3) When ready, build and deploy to Cloud Run so the backend runs entirely in GCP.
