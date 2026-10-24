"""Object detectors that find animals in a single image."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass
class Detection:
    label: str  # "animal", "person" or "vehicle"
    confidence: float
    # Normalised box: x, y of the top-left corner, then width and height, each 0 to 1.
    box: tuple[float, float, float, float]


class Detector(Protocol):
    def detect(self, image: Image.Image) -> list[Detection]: ...


class MegaDetector:
    """Wraps Microsoft's MegaDetector, trained on camera-trap images.

    Model weights download on first use and are cached by the megadetector package.
    """

    LABELS = {"1": "animal", "2": "person", "3": "vehicle"}

    def __init__(self, model: str = "MDV5A", min_confidence: float = 0.05):
        from megadetector.detection.run_detector import load_detector

        self._model = load_detector(model)
        self._min_confidence = min_confidence

    def detect(self, image: Image.Image) -> list[Detection]:
        result = self._model.generate_detections_one_image(
            image, image_id="frame", detection_threshold=self._min_confidence
        )
        return [
            Detection(
                label=self.LABELS.get(d["category"], d["category"]),
                confidence=float(d["conf"]),
                box=tuple(d["bbox"]),
            )
            for d in result.get("detections") or []
        ]
