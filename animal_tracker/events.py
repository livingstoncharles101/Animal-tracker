"""Read Ring webhook events.

The field paths below follow the hints in Ring's docs (`meta.request_id`,
`attributes.sub_type`, `attributes.component_ids`); the full v1.1 payload is
not in the public docs, so parsing is lenient and the raw event is logged.
Confirm against a real webhook before relying on anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RingEvent:
    request_id: str | None
    type: str | None
    device_id: str | None
    account_id: str | None
    occurred_at: datetime
    sub_type: str | None = None
    component_ids: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _first(d: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        cur: Any = d
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur not in (None, ""):
            return cur
    return None


def _time(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def parse_event(payload: dict[str, Any]) -> RingEvent:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    attrs = data.get("attributes") or {}
    return RingEvent(
        request_id=_first(payload, "meta.request_id", "request_id"),
        type=_first(data, "type", "attributes.type", "event_type"),
        device_id=_first(
            data, "attributes.device_id", "relationships.device.data.id",
            "relationships.devices.data.id", "device_id",
        ),
        account_id=_first(
            data, "attributes.account_id", "relationships.account.data.id",
            "account_id",
        ) or _first(payload, "meta.account_id"),
        occurred_at=_time(_first(data, "attributes.timestamp", "attributes.time")
                          or _first(payload, "meta.time")),
        sub_type=attrs.get("sub_type"),
        component_ids=list(attrs.get("component_ids") or []),
        raw=payload,
    )


def clip_request_for_event(event: RingEvent, seconds: int = 30) -> dict[str, Any]:
    """Body for the video download call covering this event.

    TODO: field names are a placeholder until confirmed from Ring's Media Clips
    docs or the developer Playground. `components` is documented.
    """
    start = int(event.occurred_at.timestamp() * 1000)
    body: dict[str, Any] = {"start_time": start, "end_time": start + seconds * 1000}
    if event.component_ids:
        body["components"] = event.component_ids
    return body
