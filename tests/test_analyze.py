from pathlib import Path

from PIL import Image

from animal_tracker.analyze import analyze_frames
from animal_tracker.detector import Detection
from animal_tracker.frames import Frame


class ScriptedDetector:
    """Returns a fixed list of detections per frame, in order."""

    def __init__(self, per_frame):
        self._per_frame = iter(per_frame)

    def detect(self, image):
        return next(self._per_frame)


def frames(n):
    return [Frame(index=i, seconds=float(i), image=Image.new("RGB", (64, 48))) for i in range(n)]


def animal(conf):
    return Detection("animal", conf, (0.1, 0.1, 0.5, 0.5))


def run(per_frame, **kw):
    return analyze_frames(Path("clip.mp4"), frames(len(per_frame)), ScriptedDetector(per_frame), **kw)


def test_animal_in_two_frames_is_flagged():
    result = run([[], [animal(0.8)], [animal(0.6)], []])
    assert result.has_animal
    assert result.best.detection.confidence == 0.8
    assert result.best.frame.index == 1


def test_single_frame_blip_is_ignored():
    assert not run([[], [animal(0.9)], [], []]).has_animal


def test_low_confidence_is_ignored():
    assert not run([[animal(0.2)], [animal(0.25)]]).has_animal


def test_people_and_vehicles_never_flag():
    person = Detection("person", 0.95, (0, 0, 1, 1))
    car = Detection("vehicle", 0.95, (0, 0, 1, 1))
    assert not run([[person], [car], [person]]).has_animal


def test_one_frame_clip_needs_that_frame():
    assert run([[animal(0.7)]]).has_animal


def test_empty_clip():
    result = run([])
    assert not result.has_animal
    assert result.best is None
