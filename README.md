# Animal tracker

Watches Ring camera clips for animals and emails an alert with a boxed snapshot.

**Status:** step 1 and 2 of the plan. The detector and alert email work on clips you
pass in by hand. The Ring connection (webhook and clip download) and the cloud
deploy come next.

## How it decides

1. Samples 1 frame per second from the clip with ffmpeg.
2. Runs [MegaDetector](https://github.com/agentmorris/MegaDetector) on each frame.
   It labels boxes as animal, person or vehicle, and only animals count.
3. Flags the clip when an animal scores at least 0.3 in at least 2 frames, which
   filters one-frame false positives like leaves or shadows.
4. Emails the frame with the highest score, with the animal boxed.

People and vehicles never trigger an alert. Alerts are limited to one per camera
every 10 minutes (`animal_tracker/cooldown.py`).

## Try it on your own clips

Needs Python 3.11+ and ffmpeg.

```sh
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[models]"
animal-tracker clips/*.mp4 --save-frame out/
```

Each clip prints a line like `raccoon.mp4: ANIMAL (6/30 frames, best 0.91 at 4s)`,
and the boxed frame lands in `out/`. The model weights (about 280 MB) download on
first run.

### Sending a test email

Uses Gmail by default. Create an [app password](https://myaccount.google.com/apppasswords)
(needs 2-Step Verification), then:

```sh
export ALERT_SMTP_USERNAME=you@gmail.com
export ALERT_SMTP_PASSWORD='the app password'   # never commit this
export ALERT_TO=you@gmail.com                    # optional, defaults to the username
animal-tracker clips/raccoon.mp4 --camera "Front Door" --email
```

Or run it in Docker:

```sh
docker build -t animal-tracker .
docker run --rm -v "$PWD/clips:/clips" animal-tracker /clips/raccoon.mp4
```

## Tests

```sh
pip install -e ".[dev]"
pytest
```

The tests use a scripted detector, so they run without the model.
