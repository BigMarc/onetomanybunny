# ── Dockerfile ────────────────────────────────────────────────
# Video Processor service — needs FFmpeg and all heavy dependencies.

FROM python:3.11-slim

# FFmpeg is required for moviepy video processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080

# Cloud Run: gunicorn with long timeout for video jobs
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "3600", \
     "--workers", "1", \
     "--worker-class", "sync", \
     "main:app"]
