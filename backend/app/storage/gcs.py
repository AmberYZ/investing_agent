from __future__ import annotations

import datetime as dt

from app.storage.base import StorageBackend, StoredObject


class GcsStorage(StorageBackend):
    def __init__(self, *, bucket: str, prefix: str):
        try:
            from google.cloud import storage
        except ImportError as e:
            raise ImportError(
                "GCS storage requires google-cloud-storage. Install with: "
                "pip install -r requirements.txt -r requirements-gcp.txt  (from backend/)"
            ) from e

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

    def delete_object(self, *, uri: str) -> None:
        if not uri.startswith("gs://"):
            raise ValueError(f"Unsupported gcs uri: {uri}")
        _, rest = uri.split("gs://", 1)
        bucket_name, blob_name = rest.split("/", 1)
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        # Ignore if already gone (idempotent delete).
        try:
            blob.delete(if_generation_match=None)
        except Exception:
            if blob.exists():
                raise

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

