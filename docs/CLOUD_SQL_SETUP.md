# Google Cloud SQL Setup Guide

This guide walks you through configuring **Google Cloud SQL (PostgreSQL)** so your Investing Agent databases run in the cloud instead of local SQLite.

---

## Prerequisites

1. **Google Cloud project** with billing enabled.
2. **gcloud CLI** installed and authenticated:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```
3. **Required APIs** enabled (Terraform will enable these if you use it):
   - Cloud SQL Admin: `sqladmin.googleapis.com`
   - Secret Manager (if using Terraform): `secretmanager.googleapis.com`

---

## Option A: Provision Cloud SQL with Terraform (recommended)

Your repo already has Terraform in `infra/terraform/` that creates Cloud SQL, GCS, Cloud Run, etc. If you **only want the database** (no Cloud Run yet), you can create just the Cloud SQL resources and skip the services that need container images.

### 1. Create a `terraform.tfvars` file

From the repo root:

```bash
cd infra/terraform
```

Create `terraform.tfvars` (do not commit this file; add `*.tfvars` to `.gitignore` if needed):

```hcl
project_id       = "your-gcp-project-id"
region           = "us-central1"
prefix           = "investing-agent"
gcs_bucket_name  = "your-unique-bucket-name"   # must be globally unique
db_tier          = "db-f1-micro"               # smallest; use db-g1-small for production
db_name          = "narratives"
db_user          = "appuser"
db_password      = "YOUR_SECURE_PASSWORD"      # choose a strong password
# Leave these as placeholders when only provisioning the DB:
api_image        = "gcr.io/cloud-runner/placeholder"
worker_image     = "gcr.io/cloud-runner/placeholder"
aggregator_image = "gcr.io/cloud-runner/placeholder"
```

### 2. Apply only the Cloud SQL and dependency resources

This creates the Postgres instance, database, user, GCS bucket, and secrets **without** deploying Cloud Run (so placeholder images are never pulled):

```bash
terraform init
terraform apply \
  -target=google_project_service.services \
  -target=google_storage_bucket.docs \
  -target=google_secret_manager_secret.db_password \
  -target=google_secret_manager_secret_version.db_password_v1 \
  -target=google_sql_database_instance.postgres \
  -target=google_sql_database.db \
  -target=google_sql_user.user
```

Type `yes` when prompted. When it finishes, note the output (you’ll need the connection name).

### 3. Get the Cloud SQL connection name

```bash
terraform output cloudsql_connection_name
```

Example: `your-project:us-central1:investing-agent-pg`. You’ll use this for the Cloud SQL Auth Proxy.

---

## Option B: Create Cloud SQL manually (no Terraform)

If you prefer not to use Terraform, create the instance with **gcloud** or the **GCP Console**.

### Using gcloud

1. **Enable the API**
   ```bash
   gcloud services enable sqladmin.googleapis.com
   ```

2. **Create the instance** (Postgres 16, smallest tier)
   ```bash
   gcloud sql instances create investing-agent-pg \
     --database-version=POSTGRES_16 \
     --tier=db-f1-micro \
     --region=us-central1
   ```
   This can take several minutes.

3. **Create the database**
   ```bash
   gcloud sql databases create narratives --instance=investing-agent-pg
   ```

4. **Create the user and set password**
   ```bash
   gcloud sql users create appuser \
     --instance=investing-agent-pg \
     --password=YOUR_SECURE_PASSWORD
   ```

5. **Get the connection name**
   ```bash
   gcloud sql instances describe investing-agent-pg --format='value(connectionName)'
   ```
   Example: `your-project:us-central1:investing-agent-pg`.

### Using the GCP Console

1. Open [Cloud SQL](https://console.cloud.google.com/sql).
2. Click **Create instance** → **Choose PostgreSQL**.
3. Set instance ID (e.g. `investing-agent-pg`), password for the default user, region (e.g. `us-central1`), and tier (e.g. **Micro**).
4. Create the instance, then add a database (`narratives`) and an additional user (`appuser`) if you don’t use the postgres user.
5. Copy the **Connection name** from the instance details (e.g. `project:region:instance`).

---

## Connect from your Mac (Cloud SQL Auth Proxy)

Cloud SQL is not exposed to the public internet by default. To connect from your laptop, use the **Cloud SQL Auth Proxy**, which opens a secure tunnel and listens on `127.0.0.1:5432`.

### 1. Install the proxy

```bash
brew install cloud-sql-proxy
```

Or download from: https://cloud.google.com/sql/docs/postgres/connect-auth-proxy#install

### 2. Start the proxy

Replace `PROJECT:REGION:INSTANCE` with your connection name (from Terraform output or gcloud/Console):

```bash
cloud-sql-proxy PROJECT:REGION:INSTANCE
```

Example:

```bash
cloud-sql-proxy your-project:us-central1:investing-agent-pg
```

Leave this running in a terminal. It will listen on `127.0.0.1:5432` by default.

### 3. Point your app at Postgres in `.env`

In your repo root `.env` (same values you used for Terraform or gcloud):

```env
# Replace with your actual db_user, db_password, db_name
DATABASE_URL=postgresql+psycopg://appuser:YOUR_SECURE_PASSWORD@127.0.0.1:5432/narratives
```

Use the same password you set for `appuser` (Terraform `db_password` or gcloud `--password`).

### 4. Run migrations

From the repo root or `backend/`:

```bash
cd backend && alembic upgrade head
```

### 5. Start your backend

With the proxy still running in another terminal, start the API/worker as usual. They will use `DATABASE_URL` from `.env` and talk to Cloud SQL via the proxy.

---

## Summary checklist

| Step | Action |
|------|--------|
| 1 | Create Cloud SQL (Terraform **Option A** or manual **Option B**). |
| 2 | Install and run **Cloud SQL Auth Proxy** with your instance’s connection name. |
| 3 | Set **DATABASE_URL** in `.env` to `postgresql+psycopg://user:password@127.0.0.1:5432/narratives`. |
| 4 | Run **`alembic upgrade head`** in `backend/`. |
| 5 | Start the backend; use the app as before with the cloud DB. |

---

## Optional: Move data from SQLite to Postgres

If you have existing data in `dev.db`:

- You can **export from SQLite and import into Postgres** using tools or custom scripts (schema is already compatible via Alembic).
- Or **start fresh** on Cloud SQL and re-ingest documents; then you can remove local `dev.db` to free space.

---

## Security notes

- **Never commit** `terraform.tfvars` or `.env` (they contain passwords). They are already in `.gitignore` or should be.
- Use a **strong password** for `db_user`; consider rotating it in Secret Manager or Cloud SQL later.
- The proxy uses your **gcloud credentials** to authenticate to Cloud SQL; no database password is sent over the internet.

---

## Troubleshooting

- **“Connection refused” to 127.0.0.1:5432**  
  Ensure the Cloud SQL Auth Proxy is running and the connection name is correct.

- **“password authentication failed”**  
  Double-check `db_user` and `db_password` in `.env` match the Cloud SQL user (and that the user exists).

- **Terraform apply fails on Cloud Run**  
  If you run a full `terraform apply` (without `-target`), you must provide **real** container image URLs that exist in your project. Use the `-target` flow above if you only want the DB for now.

For full cloud deployment (API + worker + aggregator on Cloud Run), see [CLOUD_MIGRATION.md](./CLOUD_MIGRATION.md).
