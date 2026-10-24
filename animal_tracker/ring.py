"""Ring's official partner API, used through a Ring Private Use App.

Docs: https://developer.amazon.com/docs/ring/api-documentation.html
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from .store import Store

TOKEN_URL = "https://oauth.ring.com/oauth/token"
API_BASE = "https://api.amazonvision.com"
USER_AGENT = "AnimalTracker/0.1"
# Ring rejects link nonces older than this.
NONCE_MAX_AGE_SECONDS = 600
# Refresh a little before the ~4 hour access token expiry.
REFRESH_MARGIN_SECONDS = 300


@dataclass
class RingApp:
    client_id: str
    client_secret: str
    hmac_key: str
    # Ring asks for a stable hardware id per client; any UUID kept constant works.
    hardware_id: str = str(uuid.uuid5(uuid.NAMESPACE_URL, "animal-tracker"))


class RingError(RuntimeError):
    pass


def _http(method: str, url: str, *, headers: dict[str, str], body: bytes | None = None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as err:
        raise RingError(f"{method} {url} -> {err.code}: {err.read()[:500]!r}") from err


def _token_request(app: RingApp, fields: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(
        {**fields, "client_id": app.client_id, "client_secret": app.client_secret}
    ).encode()
    _, _, data = _http(
        "POST", TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
        body=body,
    )
    tokens = json.loads(data)
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 14400))
    return tokens


def exchange_code(app: RingApp, code: str) -> dict[str, Any]:
    return _token_request(app, {"grant_type": "authorization_code", "code": code})


def refresh(app: RingApp, refresh_token: str) -> dict[str, Any]:
    return _token_request(app, {"grant_type": "refresh_token", "refresh_token": refresh_token})


def link_nonce(app: RingApp, time_ms: str, account_id: str) -> str:
    """The nonce Ring sends to the Account Link URL for this account."""
    digest = hmac.new(
        app.hmac_key.encode(), f"{time_ms}:{account_id}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def nonce_fresh(time_ms: str, now: float | None = None) -> bool:
    try:
        sent = int(time_ms) / 1000
    except ValueError:
        return False
    now = time.time() if now is None else now
    return 0 <= now - sent <= NONCE_MAX_AGE_SECONDS


def webhook_signature_ok(app: RingApp, raw_body: bytes, header: str | None) -> bool:
    """Check the `X-Signature` header: "sha256=" + hex HMAC-SHA256 of the raw body."""
    if not header:
        return False
    expected = "sha256=" + hmac.new(app.hmac_key.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


class RingClient:
    """Calls the Ring API for one linked account, refreshing its token as needed."""

    def __init__(self, app: RingApp, store: Store, account_id: str):
        self._app = app
        self._store = store
        self._account_id = account_id

    def _access_token(self) -> str:
        tokens = self._store.get("ring_account", self._account_id)
        if tokens is None:
            raise RingError(f"Ring account {self._account_id} is not linked")
        if tokens["expires_at"] - REFRESH_MARGIN_SECONDS < time.time():
            fresh = refresh(self._app, tokens["refresh_token"])
            tokens = {**tokens, **fresh}
            self._store.put("ring_account", self._account_id, tokens)
        return tokens["access_token"]

    def request(self, method: str, path: str, payload: Any = None, accept: str = "application/json"):
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "Hardware_Id": self._app.hardware_id,
        }
        body = json.dumps(payload).encode() if payload is not None else None
        return _http(method, API_BASE + path, headers=headers, body=body)

    def json(self, method: str, path: str, payload: Any = None) -> Any:
        _, _, data = self.request(method, path, payload)
        return json.loads(data) if data else None

    def download_clip(self, device_id: str, request_body: dict[str, Any]) -> bytes:
        """Download a recorded clip as MP4 bytes.

        `request_body` is built by `clip_request_for_event`; its exact fields are
        still to be confirmed against Ring's Media Clips docs.
        """
        _, content_type, data = self.request(
            "POST", f"/v1/devices/{device_id}/media/video/download", request_body,
            accept="video/mp4, application/json",
        )
        if content_type.startswith("application/json"):
            # Ring may answer with a link to the MP4 rather than the bytes.
            info = json.loads(data)
            url = _find_url(info)
            if not url:
                raise RingError(f"clip download returned no video: {data[:300]!r}")
            _, _, data = _http("GET", url, headers={"User-Agent": USER_AGENT})
        return data


def _find_url(obj: Any) -> str | None:
    if isinstance(obj, str) and obj.startswith("https://"):
        return obj
    if isinstance(obj, dict):
        obj = list(obj.values())
    if isinstance(obj, list):
        for item in obj:
            if (found := _find_url(item)):
                return found
    return None


# --- Account linking (Ring's one-way flow) ---------------------------------

def handle_token_exchange(app: RingApp, store: Store, code: str) -> str:
    """Token Exchange URL: swap the code, find the account id, keep it unclaimed."""
    tokens = exchange_code(app, code)
    _, _, data = _http(
        "GET", API_BASE + "/v1/users/me",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Hardware_Id": app.hardware_id,
        },
    )
    account_id = _account_id(json.loads(data))
    previous = store.get("ring_account", account_id) or {}
    store.put("ring_account", account_id, {**previous, **tokens, "account_id": account_id})
    return account_id


def _account_id(me: dict[str, Any]) -> str:
    data = me.get("data", me)
    for key in ("id", "account_id", "accountId"):
        if data.get(key):
            return str(data[key])
    raise RingError(f"no account id in /v1/users/me response: {json.dumps(me)[:300]}")


def handle_account_link(app: RingApp, store: Store, nonce: str, time_ms: str, label: str) -> str:
    """Account Link URL, after Neil has signed in: match the nonce and complete the link."""
    if not nonce_fresh(time_ms):
        raise RingError("link request expired; start again from the Ring app")
    for account_id, tokens in store.list("ring_account").items():
        if hmac.compare_digest(link_nonce(app, time_ms, account_id), nonce):
            client = RingClient(app, store, account_id)
            client.json("POST", "/v1/accounts/me/app-integrations",
                        {"account_identifier": label, "nonce": nonce})
            client.json("PATCH", "/v1/accounts/me/app-integrations", {"status": "completed"})
            store.put("ring_account", account_id, {**tokens, "claimed": True})
            return account_id
    raise RingError("no pending Ring account matches this link request")
