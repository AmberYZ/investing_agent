from __future__ import annotations

import datetime as dt

from app.settings import settings
from app.storage.base import StorageBackend, StoredObject


class GcsStorage(StorageBackend):
    def __init__(self, *, bucket: str, prefix: str):
        from google.cloud import storage

        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket)
        self.prefix = prefix.strip("/").rstrip("/")

    def _blob_name(self, key: str) -> str:
        key = key.lstrip("/")
        if not self.prefix:
            return key
        return f"{self.prefix}/{key}"

    def upload_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        blob = self.bucket.blob(self._blob_name(key))
        blob.upload_from_string(data, content_type=content_type)
        return StoredObject(uri=f"gs://{self.bucket.name}/{blob.name}")

    def download_bytes(self, *, uri: str) -> bytes:
        if not uri.startswith("gs://"):
            raise ValueError(f"Unsupported gcs uri: {uri}")
        _, rest = uri.split("gs://", 1)
        bucket_name, blob_name = rest.split("/", 1)
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.download_as_bytes()

    def generate_signed_url(self, *, uri: str, expires_in: int = 3600) -> str:
        """
        Generate a V4 signed URL for a given gs:// URI.

        This is used by the API to provide time-limited access to PDFs for the dashboard.
        """
        if not uri.startswith("gs://"):
            raise ValueError(f"Unsupported gcs uri: {uri}")
        _, rest = uri.split("gs://", 1)
        bucket_name, blob_name = rest.split("/", 1)
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=dt.timedelta(seconds=expires_in),
            method="GET",
        )


def get_storage() -> StorageBackend:
    if settings.storage_backend == "local":
        from app.storage.local import LocalStorage

        return LocalStorage(settings.local_storage_dir)
    if settings.storage_backend == "gcs":
        if not settings.gcs_bucket:
            raise ValueError("GCS_BUCKET is required when STORAGE_BACKEND=gcs")
        return GcsStorage(bucket=settings.gcs_bucket, prefix=settings.gcs_prefix)
    raise ValueError(f"Unknown STORAGE_BACKEND={settings.storage_backend}")

