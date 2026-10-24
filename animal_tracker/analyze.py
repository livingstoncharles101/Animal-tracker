"""Decide whether a clip contains an animal."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .detector import Detection, Detector
from .frames import Frame, sample_frames


@dataclass
class Sighting:
    frame: Frame
    detection: Detection


@dataclass
class ClipResult:
    clip: Path
    frames_checked: int
    sightings: list[Sighting] = field(default_factory=list)
    has_animal: bool = False

    @property
    def best(self) -> Sighting | None:
        return max(self.sightings, key=lambda s: s.detection.confidence, default=None)


def analyze_frames(
    clip: Path,
    frames: list[Frame],
    detector: Detector,
    threshold: float = 0.3,
    min_frames: int = 2,
) -> ClipResult:
    """Flag the clip when an animal above `threshold` shows up in `min_frames` frames.

    Requiring more than one frame filters out one-off false positives such as
    leaves or shadows. A clip with fewer frames than `min_frames` needs all of them.
    """
    result = ClipResult(clip=clip, frames_checked=len(frames))
    frames_with_animal = 0
    for frame in frames:
        animals = [
            d for d in detector.detect(frame.image)
            if d.label == "animal" and d.confidence >= threshold
        ]
        if animals:
            frames_with_animal += 1
            best = max(animals, key=lambda d: d.confidence)
            result.sightings.append(Sighting(frame=frame, detection=best))
    needed = min(min_frames, len(frames)) if frames else 1
    result.has_animal = frames_with_animal >= needed
    return result


def analyze_clip(
    clip: Path,
    detector: Detector,
    fps: float = 1.0,
    threshold: float = 0.3,
    min_frames: int = 2,
) -> ClipResult:
    frames = sample_frames(clip, fps=fps)
    return analyze_frames(clip, frames, detector, threshold=threshold, min_frames=min_frames)
