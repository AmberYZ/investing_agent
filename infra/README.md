# Infra (GCP)

This folder contains Terraform to provision the MVP cloud resources:

- GCS bucket for PDFs and extracted text
- Cloud SQL (Postgres) instance + DB + user
- Pub/Sub topic + push subscription (ingest jobs)
- Cloud Run services (api/worker/aggregator)
- Cloud Scheduler job (daily aggregation trigger)
- Secret Manager secrets (DB password and app env)

## Prereqs

- `gcloud auth application-default login`
- Terraform installed
- A GCP project with billing enabled

## Usage

```bash
cd infra/terraform
terraform init
terraform apply
```

After apply, Terraform outputs the Cloud Run URLs.

## Notes

- The codebase supports local dev (sqlite + local storage). Cloud deploy switches to Cloud SQL + GCS + Pub/Sub.
- You still need to build and deploy container images for `api`, `worker`, and `aggregator` (Terraform provisions the services and expects image URLs).

