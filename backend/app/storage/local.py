from __future__ import annotations

import os
from pathlib import Path

from app.storage.base import StorageBackend, StoredObject


class LocalStorage(StorageBackend):
    def __init__(self, root_dir: str):
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def upload_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(uri=f"file://{path.absolute()}")

    def download_bytes(self, *, uri: str) -> bytes:
        if not uri.startswith("file://"):
            raise ValueError(f"Unsupported local uri: {uri}")
        path = Path(uri[len('file://') :])
        return path.read_bytes()

