output "gcs_bucket" {
  value = google_storage_bucket.docs.name
}

output "cloudsql_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "worker_url" {
  value = google_cloud_run_v2_service.worker.uri
}

output "aggregator_url" {
  value = google_cloud_run_v2_service.aggregator.uri
}

output "pubsub_topic" {
  value = google_pubsub_topic.ingest.name
}

