"""Limit alerts to one per camera per cooldown window."""

from __future__ import annotations

from datetime import datetime, timedelta


class Cooldown:
    def __init__(self, window: timedelta = timedelta(minutes=10)):
        self._window = window
        self._last_sent: dict[str, datetime] = {}

    def allow(self, camera: str, now: datetime) -> bool:
        """True if an alert for `camera` may go out now; records it if so."""
        last = self._last_sent.get(camera)
        if last is not None and now - last < self._window:
            return False
        self._last_sent[camera] = now
        return True
