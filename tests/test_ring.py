import hashlib
import hmac
import json
import time

import pytest

from animal_tracker import ring
from animal_tracker.events import clip_request_for_event, parse_event
from animal_tracker.store import MemoryStore

APP = ring.RingApp(client_id="cid", client_secret="secret", hmac_key="hkey")


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(b"hkey", body, hashlib.sha256).hexdigest()


def test_webhook_signature():
    body = b'{"a":1}'
    assert ring.webhook_signature_ok(APP, body, sign(body))
    assert not ring.webhook_signature_ok(APP, body + b" ", sign(body))
    assert not ring.webhook_signature_ok(APP, body, None)


def test_nonce_freshness():
    now = time.time()
    assert ring.nonce_fresh(str(int(now * 1000)), now)
    assert not ring.nonce_fresh(str(int((now - 601) * 1000)), now)
    assert not ring.nonce_fresh(str(int((now + 60) * 1000)), now)
    assert not ring.nonce_fresh("junk", now)


def test_link_nonce_has_no_padding():
    nonce = ring.link_nonce(APP, "1700000000000", "acct-1")
    assert "=" not in nonce and "+" not in nonce and "/" not in nonce


class FakeHttp:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, *, headers, body=None):
        self.calls.append((method, url, headers, body))
        if url == ring.TOKEN_URL:
            return 200, "application/json", json.dumps(
                {"access_token": "at", "refresh_token": "rt", "expires_in": 14400}).encode()
        if url.endswith("/v1/users/me"):
            return 200, "application/json", b'{"data": {"id": "acct-1"}}'
        return 200, "application/json", b"{}"


def test_full_link_flow(monkeypatch):
    http = FakeHttp()
    monkeypatch.setattr(ring, "_http", http)
    store = MemoryStore()

    assert ring.handle_token_exchange(APP, store, "the-code") == "acct-1"
    token_body = http.calls[0][3].decode()
    assert "grant_type=authorization_code" in token_body and "client_secret=secret" in token_body

    t = str(int(time.time() * 1000))
    nonce = ring.link_nonce(APP, t, "acct-1")
    assert ring.handle_account_link(APP, store, nonce, t, "animal-tracker") == "acct-1"
    methods = [(m, u.removeprefix(ring.API_BASE)) for m, u, _, _ in http.calls[2:]]
    assert methods == [("POST", "/v1/accounts/me/app-integrations"),
                       ("PATCH", "/v1/accounts/me/app-integrations")]
    headers = http.calls[2][2]
    assert headers["Authorization"] == "Bearer at" and headers["Hardware_Id"]
    assert store.get("ring_account", "acct-1")["claimed"]


def test_link_rejects_wrong_nonce(monkeypatch):
    monkeypatch.setattr(ring, "_http", FakeHttp())
    store = MemoryStore()
    ring.handle_token_exchange(APP, store, "code")
    with pytest.raises(ring.RingError):
        ring.handle_account_link(APP, store, "wrong", str(int(time.time() * 1000)), "x")


def test_expired_token_is_refreshed(monkeypatch):
    http = FakeHttp()
    monkeypatch.setattr(ring, "_http", http)
    store = MemoryStore()
    store.put("ring_account", "acct-1",
              {"access_token": "old", "refresh_token": "rt0", "expires_at": time.time() - 1})
    ring.RingClient(APP, store, "acct-1").json("GET", "/v1/devices")
    assert "grant_type=refresh_token" in http.calls[0][3].decode()
    assert http.calls[1][2]["Authorization"] == "Bearer at"
    assert store.get("ring_account", "acct-1")["refresh_token"] == "rt"


def test_parse_event_and_clip_request():
    event = parse_event({
        "meta": {"request_id": "r1", "time": "2026-10-24T02:14:00Z"},
        "data": {"type": "motion_detected",
                 "attributes": {"sub_type": "other", "device_id": "dev9", "component_ids": ["c1"]}},
    })
    assert (event.request_id, event.type, event.device_id) == ("r1", "motion_detected", "dev9")
    assert event.occurred_at.hour == 2
    body = clip_request_for_event(event)
    assert body["components"] == ["c1"]
    assert body["end_time"] - body["start_time"] == 30_000
