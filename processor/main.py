"""
processor/main.py — Video Processor Flask App

POST /process
Body: { "job_id": "ABC123", "gcs_uri": "gs://bucket/path.mp4", "creator_name": "Name" }

Flow:
1. Download source from GCS to /tmp
2. Select ~5 segments of 7 seconds each (evenly spaced)
3. For each segment:
   a. Extract clip with FFmpeg
   b. Add rotating text overlay (creator name, random phrases)
   c. Add random background music track (from sounds/ folder)
   d. Output as {job_id}_clip_{N}.mp4
4. Zip all clips
5. Upload ZIP to GCS: gs://bucket/results/{job_id}/clips.zip
6. Return { "status": "ok", "zip_gcs_uri": "gs://...", "clip_count": 5 }
"""

import os
import tempfile
import shutil
import logging
import zipfile

from flask import Flask, request, jsonify
from google.cloud import storage as gcs

from processor.clip_generator import generate_clip
from processor.scene_detect import select_timestamps, get_duration

app = Flask(__name__)
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

GCS_BUCKET = os.environ.get("GCS_BUCKET", "bunny-clip-tool-videos")
CLIP_DURATION = 7  # seconds
TARGET_CLIPS = 5

# GCS client — lazy-initialized so the module can import without credentials
_gcs_client = None
_bucket = None


def _get_bucket():
    global _gcs_client, _bucket
    if _bucket is None:
        _gcs_client = gcs.Client()
        _bucket = _gcs_client.bucket(GCS_BUCKET)
    return _bucket


def _get_gcs_client():
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs.Client()
    return _gcs_client


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/process", methods=["POST"])
def process_video():
    data = request.get_json()
    job_id = data["job_id"]
    gcs_uri = data["gcs_uri"]
    creator_name = data.get("creator_name", "Creator")

    logger.info(f"[{job_id}] Job started — source={gcs_uri}")
    tmp_dir = tempfile.mkdtemp(prefix=f"proc_{job_id}_")

    try:
        # 1. Download source from GCS
        source_path = os.path.join(tmp_dir, "source.mp4")
        _download_from_gcs(gcs_uri, source_path)
        logger.info(
            f"[{job_id}] Downloaded source "
            f"({os.path.getsize(source_path) / 1024 / 1024:.1f} MB)"
        )

        # 2. Get video duration
        duration = get_duration(source_path)
        logger.info(f"[{job_id}] Video duration: {duration:.1f}s")

        # 3. Select clip timestamps
        timestamps = select_timestamps(duration, CLIP_DURATION, TARGET_CLIPS)
        logger.info(
            f"[{job_id}] Selected {len(timestamps)} clip timestamps: {timestamps}"
        )

        # 4. Generate clips
        clip_paths = []
        for i, start_time in enumerate(timestamps):
            clip_path = os.path.join(tmp_dir, f"{job_id}_clip_{i + 1:02d}.mp4")
            generate_clip(
                source_path=source_path,
                output_path=clip_path,
                start_time=start_time,
                duration=CLIP_DURATION,
                creator_name=creator_name,
                clip_number=i + 1,
            )
            clip_paths.append(clip_path)
            logger.info(f"[{job_id}] Generated clip {i + 1}/{len(timestamps)}")

        # 5. Zip all clips
        zip_path = os.path.join(tmp_dir, f"{job_id}_clips.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for cp in clip_paths:
                zf.write(cp, os.path.basename(cp))
        logger.info(
            f"[{job_id}] ZIP created "
            f"({os.path.getsize(zip_path) / 1024 / 1024:.1f} MB)"
        )

        # 6. Upload ZIP to GCS
        zip_gcs_key = f"results/{job_id}/clips.zip"
        _get_bucket().blob(zip_gcs_key).upload_from_filename(zip_path)
        zip_gcs_uri = f"gs://{GCS_BUCKET}/{zip_gcs_key}"
        logger.info(f"[{job_id}] Uploaded ZIP to {zip_gcs_uri}")

        return jsonify(
            {
                "status": "ok",
                "zip_gcs_uri": zip_gcs_uri,
                "clip_count": len(clip_paths),
            }
        )

    except Exception as e:
        logger.error(f"[{job_id}] Processing failed: {e}", exc_info=True)
        return jsonify({"error": str(e)[:500]}), 500

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.info(f"[{job_id}] Cleaned up {tmp_dir}")


def _download_from_gcs(gcs_uri: str, destination: str):
    """Download a file from GCS. No credentials needed — uses Cloud Run service account."""
    path = gcs_uri.replace("gs://", "")
    bucket_name, blob_name = path.split("/", 1)
    b = _get_gcs_client().bucket(bucket_name)
    b.blob(blob_name).download_to_filename(destination)
