"""Command line: check clips for animals and optionally email an alert.

    animal-tracker clip.mp4 [more.mp4 ...] [--camera "Front Door"] [--email]
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .alert import build_alert, send
from .analyze import analyze_clip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("clips", nargs="+", type=Path)
    parser.add_argument("--camera", default="Ring camera")
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--min-frames", type=int, default=2)
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--save-frame", type=Path, help="Folder to save the boxed best frame")
    parser.add_argument("--email", action="store_true", help="Send an alert email for animal clips")
    args = parser.parse_args(argv)

    from .detector import MegaDetector

    detector = MegaDetector()
    for clip in args.clips:
        result = analyze_clip(
            clip, detector, fps=args.fps, threshold=args.threshold, min_frames=args.min_frames
        )
        best = result.best
        verdict = "ANIMAL" if result.has_animal else "no animal"
        detail = (
            f", best {best.detection.confidence:.2f} at {best.frame.seconds:.0f}s"
            if best else ""
        )
        print(
            f"{clip.name}: {verdict} ({len(result.sightings)}/{result.frames_checked} frames{detail})"
        )
        if result.has_animal and args.save_frame:
            from .alert import annotated_jpeg

            args.save_frame.mkdir(parents=True, exist_ok=True)
            (args.save_frame / f"{clip.stem}.jpg").write_bytes(annotated_jpeg(best))
        if result.has_animal and args.email:
            from .config import smtp_from_env

            settings = smtp_from_env()
            msg = build_alert(
                best, args.camera, datetime.now(), settings.sender, settings.recipient
            )
            send(msg, settings)
            print(f"  emailed {settings.recipient}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
