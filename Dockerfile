FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# CPU-only PyTorch keeps the image small; the cloud service has no GPU.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml README.md ./
COPY animal_tracker ./animal_tracker
RUN pip install --no-cache-dir ".[models]"
# Download the MegaDetector weights at build time so the first alert is not slow.
RUN python -c "from animal_tracker.detector import MegaDetector; MegaDetector()"

ENTRYPOINT ["animal-tracker"]
