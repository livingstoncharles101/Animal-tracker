FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir /models
# CPU-only PyTorch keeps the image small; the cloud service has no GPU.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml README.md ./
COPY animal_tracker ./animal_tracker
RUN pip install --no-cache-dir ".[models,cloud]"
# Bake the MegaDetector weights into the image so cold starts don't download them.
RUN TMPDIR=/models python -c "from animal_tracker.detector import MegaDetector; MegaDetector()" \
 && ls /models/megadetector_models/*.pt
ENV MEGADETECTOR_MODEL=/models/megadetector_models/md_v5a.0.1.pt

# One worker process (one model in memory) with threads, so webhooks are answered
# quickly while a clip is being checked.
ENV PORT=8080
CMD exec gunicorn --bind ":$PORT" --workers 1 --threads 4 --timeout 600 \
    "animal_tracker.server:create_app()"
