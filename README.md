# Animal tracker

Watches Ring camera clips for animals and emails an alert with a boxed snapshot.

**Status:** the detector and alert email work on clips you pass in by hand. The Ring
connection and Cloud Run service are written and unit-tested but not yet deployed;
the video download request body and webhook payload still need confirming against
a real Ring account (see `animal_tracker/events.py`).

## How it fits together

1. Ring posts a signed `motion_detected` webhook to `/ring/webhook`.
2. The service checks the `X-Signature` HMAC, drops Ring retries by `meta.request_id`,
   and queues the event in Cloud Tasks so it can answer Ring within 5 seconds.
3. Cloud Tasks calls `/tasks/clip`, which downloads the clip from Ring, checks it,
   and emails if an animal is found.

Ring tokens, seen event ids and the last alert time per camera live in Firestore.

## How it decides

1. Samples 1 frame per second from the clip with ffmpeg.
2. Runs [MegaDetector](https://github.com/agentmorris/MegaDetector) on each frame.
   It labels boxes as animal, person or vehicle, and only animals count.
3. Flags the clip when an animal scores at least 0.3 in at least 2 frames, which
   filters one-frame false positives like leaves or shadows.
4. Emails the frame with the highest score, with the animal boxed.

People and vehicles never trigger an alert. Alerts are limited to one per camera
every 10 minutes (`ALERT_COOLDOWN_SECONDS`).

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

## Deploy to Google Cloud

1. Create the secrets once. Values come from the Ring private app's key CSV, a
   Gmail app password, and two random strings you make up:

   ```sh
   printf %s 'CLIENT_ID'  | gcloud secrets create ring-client-id --data-file=-
   printf %s 'SECRET'     | gcloud secrets create ring-client-secret --data-file=-
   printf %s 'HMAC_KEY'   | gcloud secrets create ring-hmac-key --data-file=-
   printf %s 'APP_PASS'   | gcloud secrets create smtp-password --data-file=-
   openssl rand -hex 16 | gcloud secrets create link-password --data-file=-
   openssl rand -hex 32 | gcloud secrets create tasks-token --data-file=-
   ```

2. `PROJECT=your-project ALERT_EMAIL=you@gmail.com ./scripts/deploy.sh`
3. Paste the three URLs it prints into the Ring developer portal, then use
   **Connect Ring account** there. When the link page asks for a password, use the
   `link-password` secret (`gcloud secrets versions access latest --secret=link-password`).

## Tests

```sh
pip install -e ".[dev]"
pytest
```

The tests use a scripted detector and a fake Ring API, so they run without the
model or any accounts.
