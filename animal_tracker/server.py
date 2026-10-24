"""Web service for Cloud Run: Ring account linking, webhooks, and the clip worker.

Routes
  GET/POST /ring/link    Account Link URL (Neil signs in with LINK_PASSWORD)
  POST     /ring/token   Token Exchange URL (called by Ring)
  POST     /ring/webhook Ring event webhook; answers within 5 s, queues the work
  POST     /tasks/clip   Worker, called by Cloud Tasks; downloads and checks a clip
  GET      /healthz
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, abort, request

from . import ring
from .events import clip_request_for_event, parse_event
from .store import FirestoreStore, MemoryStore, Store, allow_alert

log = logging.getLogger("animal_tracker")
logging.basicConfig(level=logging.INFO)


def create_app(store: Store | None = None, enqueue=None, process=None) -> Flask:
    app = Flask(__name__)
    ring_app = ring.RingApp(
        client_id=os.environ["RING_CLIENT_ID"],
        client_secret=os.environ["RING_CLIENT_SECRET"],
        hmac_key=os.environ["RING_HMAC_KEY"],
    )
    store = store or (FirestoreStore() if os.environ.get("USE_FIRESTORE") == "1" else MemoryStore())
    link_password = os.environ["LINK_PASSWORD"]
    tasks_token = os.environ["TASKS_TOKEN"]
    enqueue = enqueue or cloud_tasks_enqueue
    process = process or process_clip

    @app.get("/healthz")
    def healthz():
        return "ok"

    @app.post("/ring/token")
    def token_exchange():
        code = request.form.get("code", "")
        if not code or request.form.get("client_id") != ring_app.client_id:
            abort(400)
        account_id = ring.handle_token_exchange(ring_app, store, code)
        log.info("stored tokens for Ring account %s (unclaimed)", account_id)
        return "", 200

    @app.route("/ring/link", methods=["GET", "POST"])
    def account_link():
        nonce = request.values.get("nonce", "")
        time_ms = request.values.get("time", "")
        if request.method == "GET":
            return LINK_FORM.format(nonce=_esc(nonce), time=_esc(time_ms), error="")
        if not hmac.compare_digest(request.form.get("password", ""), link_password):
            return LINK_FORM.format(nonce=_esc(nonce), time=_esc(time_ms),
                                    error="<p>Wrong password.</p>"), 401
        try:
            account_id = ring.handle_account_link(ring_app, store, nonce, time_ms, "animal-tracker")
        except ring.RingError as err:
            log.warning("account link failed: %s", err)
            return f"<p>Linking failed: {_esc(str(err))}</p>", 400
        log.info("linked Ring account %s", account_id)
        return "<p>Ring is linked. You can close this page.</p>"

    @app.post("/ring/webhook")
    def webhook():
        raw = request.get_data()
        if not ring.webhook_signature_ok(ring_app, raw, request.headers.get("X-Signature")):
            log.warning("webhook with bad signature rejected")
            abort(401)
        payload = json.loads(raw)
        event = parse_event(payload)
        log.info("webhook %s: %s", event.type, json.dumps(payload)[:2000])
        if event.type != "motion_detected":
            return "", 200
        if event.request_id and not store.add_once("seen_event", event.request_id, {"t": 1}):
            return "", 200  # Ring retry of an event we already queued
        enqueue(payload)
        return "", 200

    @app.post("/tasks/clip")
    def clip_task():
        if not hmac.compare_digest(request.headers.get("X-Tasks-Token", ""), tasks_token):
            abort(403)
        process(ring_app, store, parse_event(request.get_json()))
        return "", 200

    return app


def process_clip(ring_app: ring.RingApp, store: Store, event) -> None:
    """Download the event's clip, look for animals, and email if one is found."""
    from .alert import build_alert, send
    from .analyze import analyze_clip
    from .config import smtp_from_env
    from .detector import MegaDetector

    accounts = store.list("ring_account")
    account_id = event.account_id or next(iter(accounts), None)
    if not account_id or not event.device_id:
        log.error("event missing account or device: %s", json.dumps(event.raw)[:1000])
        return
    client = ring.RingClient(ring_app, store, account_id)
    mp4 = client.download_clip(event.device_id, clip_request_for_event(event))

    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "clip.mp4"
        clip.write_bytes(mp4)
        result = analyze_clip(clip, _detector(MegaDetector))
    best = result.best
    log.info("device %s: animal=%s (%d/%d frames)", event.device_id, result.has_animal,
             len(result.sightings), result.frames_checked)
    if not result.has_animal:
        return
    cooldown = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "600"))
    if not allow_alert(store, event.device_id, event.occurred_at, cooldown):
        log.info("alert for %s skipped by cooldown", event.device_id)
        return
    settings = smtp_from_env()
    camera = _camera_name(store, client, event.device_id)
    local = event.occurred_at.astimezone(ZoneInfo(os.environ.get("ALERT_TIMEZONE", "UTC")))
    send(build_alert(best, camera, local, settings.sender, settings.recipient), settings)
    log.info("alert emailed for %s", camera)


_DETECTOR = None


def _detector(factory):
    # Loading MegaDetector takes seconds, so keep one per process.
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = factory()
    return _DETECTOR


def _camera_name(store: Store, client: ring.RingClient, device_id: str) -> str:
    cached = store.get("device", device_id)
    if cached:
        return cached["name"]
    name = device_id
    try:
        info = client.json("GET", f"/v1/devices/{device_id}")
        data = info.get("data", info)
        name = (data.get("attributes") or {}).get("name") or data.get("name") or device_id
    except ring.RingError as err:
        log.warning("could not fetch device name: %s", err)
    store.put("device", device_id, {"name": name})
    return name


def cloud_tasks_enqueue(payload: dict) -> None:
    from google.cloud import tasks_v2

    client = tasks_v2.CloudTasksClient()
    queue = client.queue_path(
        os.environ["GOOGLE_CLOUD_PROJECT"], os.environ["TASKS_LOCATION"], os.environ["TASKS_QUEUE"]
    )
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": os.environ["SERVICE_URL"].rstrip("/") + "/tasks/clip",
            "headers": {"Content-Type": "application/json", "X-Tasks-Token": os.environ["TASKS_TOKEN"]},
            "body": json.dumps(payload).encode(),
        },
        "dispatch_deadline": timedelta(minutes=10),
    }
    client.create_task(parent=queue, task=task)


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


LINK_FORM = """<!doctype html><meta name="viewport" content="width=device-width">
<title>Link Ring to Animal tracker</title>
<h1>Link Ring to Animal tracker</h1>{error}
<form method="post">
<input type="hidden" name="nonce" value="{nonce}"><input type="hidden" name="time" value="{time}">
<label>Password <input type="password" name="password" autofocus></label>
<button>Link</button></form>"""
