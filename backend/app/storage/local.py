from __future__ import annotations

from pathlib import Path

from app.storage.base import StorageBackend, StoredObject


class LocalStorage(StorageBackend):
    def __init__(self, root_dir: str):
        self.root = Path(root_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def upload_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(uri=f"file://{path}")

    def download_bytes(self, *, uri: str) -> bytes:
        if not uri.startswith("file://"):
            raise ValueError(f"Unsupported local uri: {uri}")
        path = Path(uri[len("file://") :])
        return path.read_bytes()

    def is_managed_uri(self, uri: str) -> bool:
        """True if uri is under this storage root (safe to delete). External watch-dir files are not."""
        if not uri.startswith("file://"):
            return False
        try:
            path = Path(uri[len("file://") :]).resolve()
            return path == self.root or self.root in path.parents
        except OSError:
            return False

    def delete_object(self, *, uri: str) -> None:
        if not uri.startswith("file://"):
            raise ValueError(f"Unsupported local uri: {uri}")
        # Never delete originals outside the storage root (watch-dir files).
        if not self.is_managed_uri(uri):
            return
        path = Path(uri[len("file://") :])
        if path.exists():
            path.unlink()

