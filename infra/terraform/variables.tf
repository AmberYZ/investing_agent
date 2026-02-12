variable "project_id" {
  type        = string
  description = "GCP project id"
}

variable "region" {
  type        = string
  description = "Primary region for Cloud Run / Cloud SQL"
  default     = "us-central1"
}

variable "prefix" {
  type        = string
  description = "Resource name prefix"
  default     = "investing-agent"
}

variable "gcs_bucket_name" {
  type        = string
  description = "GCS bucket name (must be globally unique)"
}

variable "db_tier" {
  type        = string
  description = "Cloud SQL instance tier"
  default     = "db-f1-micro"
}

variable "db_name" {
  type        = string
  description = "Database name"
  default     = "narratives"
}

variable "db_user" {
  type        = string
  description = "Database username"
  default     = "appuser"
}

variable "db_password" {
  type        = string
  description = "Database user password"
  sensitive   = true
}

variable "api_image" {
  type        = string
  description = "Container image for API (e.g. us-docker.pkg.dev/.../api:tag)"
}

variable "worker_image" {
  type        = string
  description = "Container image for worker (e.g. us-docker.pkg.dev/.../worker:tag)"
}

variable "aggregator_image" {
  type        = string
  description = "Container image for aggregator (e.g. us-docker.pkg.dev/.../aggregator:tag)"
}

