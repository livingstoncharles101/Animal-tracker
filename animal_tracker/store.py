"""Small persistent state: Ring tokens, seen webhook ids, last alert per camera.

Cloud Run scales to zero between events, so this cannot live in memory in
production. `FirestoreStore` keeps it in Firestore; `MemoryStore` is for tests
and local runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class Store(Protocol):
    def get(self, kind: str, key: str) -> dict[str, Any] | None: ...
    def put(self, kind: str, key: str, value: dict[str, Any]) -> None: ...
    def list(self, kind: str) -> dict[str, dict[str, Any]]: ...
    def add_once(self, kind: str, key: str, value: dict[str, Any]) -> bool:
        """Store `value` unless `key` exists; True if it was added."""
        ...


class MemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    def get(self, kind, key):
        return self._data.get(kind, {}).get(key)

    def put(self, kind, key, value):
        self._data.setdefault(kind, {})[key] = dict(value)

    def list(self, kind):
        return dict(self._data.get(kind, {}))

    def add_once(self, kind, key, value):
        bucket = self._data.setdefault(kind, {})
        if key in bucket:
            return False
        bucket[key] = dict(value)
        return True


class FirestoreStore:
    def __init__(self, prefix: str = "animal_tracker"):
        from google.cloud import firestore

        self._db = firestore.Client()
        self._prefix = prefix

    def _col(self, kind):
        return self._db.collection(f"{self._prefix}_{kind}")

    def get(self, kind, key):
        snap = self._col(kind).document(key).get()
        return snap.to_dict() if snap.exists else None

    def put(self, kind, key, value):
        self._col(kind).document(key).set(value)

    def list(self, kind):
        return {snap.id: snap.to_dict() for snap in self._col(kind).stream()}

    def add_once(self, kind, key, value):
        from google.api_core.exceptions import AlreadyExists

        try:
            self._col(kind).document(key).create(value)
            return True
        except AlreadyExists:
            return False


def allow_alert(store: Store, camera_id: str, now: datetime, window_seconds: int) -> bool:
    """Per-camera cooldown kept in the store, so it survives restarts."""
    last = store.get("last_alert", camera_id)
    if last and now.timestamp() - last["at"] < window_seconds:
        return False
    store.put("last_alert", camera_id, {"at": now.timestamp()})
    return True
