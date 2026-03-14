"""Storage backends for blobs (PDFs, extracted text). Use get_storage() for the configured backend."""
from __future__ import annotations

from app.storage.base import StorageBackend, StoredObject
from app.storage.gcs import GcsStorage
from app.storage.local import LocalStorage

__all__ = ["StorageBackend", "StoredObject", "LocalStorage", "GcsStorage", "get_storage"]


def get_storage() -> StorageBackend:
    from app.settings import settings

    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_dir)
    if settings.storage_backend == "gcs":
        if not settings.gcs_bucket:
            raise ValueError("GCS_BUCKET is required when STORAGE_BACKEND=gcs")
        return GcsStorage(bucket=settings.gcs_bucket, prefix=settings.gcs_prefix)
    raise ValueError(f"Unknown STORAGE_BACKEND={settings.storage_backend}")
