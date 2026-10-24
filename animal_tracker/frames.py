"""Sample still frames from a video clip with ffmpeg."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass
class Frame:
    index: int
    seconds: float
    image: Image.Image


def sample_frames(clip: Path, fps: float = 1.0, max_frames: int = 120) -> list[Frame]:
    """Return frames from `clip` at `fps` frames per second, at most `max_frames`."""
    with tempfile.TemporaryDirectory() as tmp:
        pattern = str(Path(tmp) / "frame_%05d.jpg")
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", str(clip),
                "-vf", f"fps={fps}",
                "-frames:v", str(max_frames),
                "-q:v", "2",
                pattern,
            ],
            check=True,
        )
        frames = []
        for i, path in enumerate(sorted(Path(tmp).glob("frame_*.jpg"))):
            with Image.open(path) as img:
                frames.append(Frame(index=i, seconds=i / fps, image=img.convert("RGB")))
        return frames
