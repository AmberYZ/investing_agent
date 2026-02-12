terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  api_name        = "${var.prefix}-api"
  worker_name     = "${var.prefix}-worker"
  aggregator_name = "${var.prefix}-aggregator"
  topic_name      = "${var.prefix}-ingest"
}

# Enable required APIs
resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "pubsub.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# Storage bucket
resource "google_storage_bucket" "docs" {
  name                        = var.gcs_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }
}

# Secrets
resource "google_secret_manager_secret" "db_password" {
  secret_id = "${var.prefix}-db-password"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_password_v1" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = var.db_password
}

# Cloud SQL (Postgres)
resource "google_sql_database_instance" "postgres" {
  name             = "${var.prefix}-pg"
  region           = var.region
  database_version = "POSTGRES_16"

  settings {
    tier = var.db_tier
  }

  deletion_protection = true

  depends_on = [google_project_service.services]
}

resource "google_sql_database" "db" {
  name     = var.db_name
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "user" {
  name     = var.db_user
  instance = google_sql_database_instance.postgres.name
  password = var.db_password
}

# Service accounts
resource "google_service_account" "api" {
  account_id   = "${var.prefix}-api"
  display_name = "Investing agent API"
}

resource "google_service_account" "worker" {
  account_id   = "${var.prefix}-worker"
  display_name = "Investing agent worker"
}

resource "google_service_account" "aggregator" {
  account_id   = "${var.prefix}-aggregator"
  display_name = "Investing agent aggregator"
}

# IAM bindings
resource "google_project_iam_member" "api_storage" {
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_storage" {
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "api_cloudsql" {
  role   = "roles/cloudsql.client"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_cloudsql" {
  role   = "roles/cloudsql.client"
  member = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "aggregator_cloudsql" {
  role   = "roles/cloudsql.client"
  member = "serviceAccount:${google_service_account.aggregator.email}"
}

resource "google_project_iam_member" "api_secret" {
  role   = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_secret" {
  role   = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "aggregator_secret" {
  role   = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.aggregator.email}"
}

# Pub/Sub
resource "google_pubsub_topic" "ingest" {
  name = local.topic_name
}

resource "google_project_iam_member" "api_pubsub_publish" {
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_pubsub_subscribe" {
  role   = "roles/pubsub.subscriber"
  member = "serviceAccount:${google_service_account.worker.email}"
}

# Cloud Run services
resource "google_cloud_run_v2_service" "api" {
  name     = local.api_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api.email
    containers {
      image = var.api_image
      env {
        name  = "STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.docs.name
      }
      env {
        name  = "GCS_PREFIX"
        value = var.prefix
      }
      env {
        name  = "DATABASE_URL"
        value = "postgresql+psycopg://${var.db_user}:${var.db_password}@/${var.db_name}?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
      }
      env {
        name  = "ENABLE_VERTEX"
        value = "true"
      }
      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GCP_LOCATION"
        value = var.region
      }
      env {
        name  = "PUBSUB_TOPIC"
        value = google_pubsub_topic.ingest.name
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "worker" {
  name     = local.worker_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.worker.email
    containers {
      image = var.worker_image
      env {
        name  = "STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.docs.name
      }
      env {
        name  = "GCS_PREFIX"
        value = var.prefix
      }
      env {
        name  = "DATABASE_URL"
        value = "postgresql+psycopg://${var.db_user}:${var.db_password}@/${var.db_name}?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
      }
      env {
        name  = "ENABLE_VERTEX"
        value = "true"
      }
      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GCP_LOCATION"
        value = var.region
      }
    }
  }
}

resource "google_cloud_run_v2_service" "aggregator" {
  name     = local.aggregator_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.aggregator.email
    containers {
      image = var.aggregator_image
      env {
        name  = "DATABASE_URL"
        value = "postgresql+psycopg://${var.db_user}:${var.db_password}@/${var.db_name}?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
      }
    }
  }
}

# Pub/Sub push subscription -> worker endpoint
resource "google_pubsub_subscription" "ingest_push" {
  name  = "${var.prefix}-ingest-push"
  topic = google_pubsub_topic.ingest.name

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.worker.uri}/pubsub/ingest"
    oidc_token {
      service_account_email = google_service_account.worker.email
    }
  }
}

# Cloud Scheduler -> aggregator endpoint
resource "google_cloud_scheduler_job" "daily_aggregate" {
  name             = "${var.prefix}-daily-aggregate"
  description      = "Daily narrative/theme metric aggregation"
  schedule         = "0 2 * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.aggregator.uri}/aggregate/daily"
    oidc_token {
      service_account_email = google_service_account.aggregator.email
    }
  }
}

