from datetime import datetime, timedelta

from PIL import Image

from animal_tracker.alert import build_alert
from animal_tracker.analyze import Sighting
from animal_tracker.store import MemoryStore, allow_alert
from animal_tracker.detector import Detection
from animal_tracker.frames import Frame


def sighting():
    frame = Frame(0, 0.0, Image.new("RGB", (320, 240), "white"))
    return Sighting(frame, Detection("animal", 0.87, (0.25, 0.25, 0.5, 0.5)))


def test_alert_has_subject_and_inline_image():
    msg = build_alert(
        sighting(), "Front Door", datetime(2026, 10, 24, 2, 14),
        "me@example.com", "me@example.com", species="Raccoon",
        clip_url="https://example.com/clip",
    )
    assert msg["Subject"] == "Raccoon at Front Door, 2:14 AM"
    assert "87%" in msg.get_body(("plain",)).get_content()
    images = [p for p in msg.walk() if p.get_content_type() == "image/jpeg"]
    assert len(images) == 1
    html = msg.get_body(("html",)).get_content()
    assert images[0]["Content-ID"].strip("<>") in html
    assert "https://example.com/clip" in html


def test_alert_without_species():
    msg = build_alert(sighting(), "Backyard", datetime(2026, 10, 24, 14, 5), "a@x", "b@x")
    assert msg["Subject"] == "Animal at Backyard, 2:05 PM"


def test_cooldown_per_camera():
    store = MemoryStore()
    t = datetime(2026, 10, 24, 2, 0)
    assert allow_alert(store, "front", t, 600)
    assert not allow_alert(store, "front", t + timedelta(minutes=5), 600)
    assert allow_alert(store, "back", t + timedelta(minutes=5), 600)
    assert allow_alert(store, "front", t + timedelta(minutes=10), 600)
