# ── Dockerfile ────────────────────────────────────────────────
# Video Processor service — needs FFmpeg and all heavy dependencies.

FROM python:3.11-slim

# FFmpeg + fonts + utilities for moviepy video processing with text overlays
# Playfair Display (primary) and DejaVu Sans Bold (fallback)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1-mesa-dri \
    fontconfig \
    fonts-dejavu-core \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Playfair Display Bold from Google Fonts
RUN mkdir -p /usr/share/fonts/truetype/playfair && \
    wget -q -O /tmp/playfair.zip "https://fonts.google.com/download?family=Playfair+Display" && \
    unzip -q /tmp/playfair.zip -d /tmp/playfair && \
    cp /tmp/playfair/static/PlayfairDisplay-Bold.ttf /usr/share/fonts/truetype/playfair/ && \
    cp /tmp/playfair/static/PlayfairDisplay-ExtraBold.ttf /usr/share/fonts/truetype/playfair/ 2>/dev/null || true && \
    rm -rf /tmp/playfair /tmp/playfair.zip && \
    fc-cache -f -v

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
