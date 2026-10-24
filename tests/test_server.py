import hashlib
import hmac
import json

import pytest

from animal_tracker.store import MemoryStore


@pytest.fixture
def setup(monkeypatch):
    for k, v in {"RING_CLIENT_ID": "cid", "RING_CLIENT_SECRET": "s", "RING_HMAC_KEY": "hkey",
                 "LINK_PASSWORD": "pw", "TASKS_TOKEN": "tt"}.items():
        monkeypatch.setenv(k, v)
    from animal_tracker.server import create_app

    queued, processed = [], []
    app = create_app(store=MemoryStore(), enqueue=queued.append,
                     process=lambda ring_app, store, event: processed.append(event))
    return app.test_client(), queued, processed


def post_webhook(client, payload, signature=None):
    body = json.dumps(payload).encode()
    sig = signature or "sha256=" + hmac.new(b"hkey", body, hashlib.sha256).hexdigest()
    return client.post("/ring/webhook", data=body, headers={"X-Signature": sig},
                       content_type="application/json")


MOTION = {"meta": {"request_id": "r1"}, "data": {"type": "motion_detected"}}


def test_webhook_queues_motion_once(setup):
    client, queued, _ = setup
    assert post_webhook(client, MOTION).status_code == 200
    assert post_webhook(client, MOTION).status_code == 200  # Ring retry
    assert queued == [MOTION]


def test_webhook_ignores_other_events(setup):
    client, queued, _ = setup
    post_webhook(client, {"meta": {"request_id": "r2"}, "data": {"type": "device_online"}})
    assert queued == []


def test_webhook_rejects_bad_signature(setup):
    client, queued, _ = setup
    assert post_webhook(client, MOTION, signature="sha256=00").status_code == 401
    assert queued == []


def test_task_needs_token(setup):
    client, _, processed = setup
    assert client.post("/tasks/clip", json=MOTION).status_code == 403
    assert client.post("/tasks/clip", json=MOTION, headers={"X-Tasks-Token": "tt"}).status_code == 200
    assert processed[0].request_id == "r1"


def test_link_page_needs_password(setup):
    client, _, _ = setup
    page = client.get("/ring/link?nonce=n%22x&time=1")
    assert page.status_code == 200 and b"n&quot;x" in page.data
    assert client.post("/ring/link", data={"nonce": "n", "time": "1", "password": "no"}).status_code == 401
