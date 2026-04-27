from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredObject:
    uri: str


class StorageBackend:
    def upload_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject:  # pragma: no cover
        raise NotImplementedError

    def download_bytes(self, *, uri: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def delete_object(self, *, uri: str) -> None:  # pragma: no cover
        raise NotImplementedError

