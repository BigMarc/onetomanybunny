"""
Bunny Clip Tool — Cloud Run Entry Point
========================================

Accepts two input modes:

Mode A — FROM TELEGRAM BOT:
  POST /process
  { "gcs_uri": "gs://bucket/uploads/JOB123/source_video.mp4",
    "job_id": "JOB123",
    "creator_name": "Sofia",
    "output_folder_id": "1abc..." }

Mode B — FROM APPS SCRIPT (Google Drive monitor):
  POST /process
  { "video_file_id": "1abc...",
    "creator_name": "Sofia" }

Both modes produce the same output: clips in Drive + JSON response.
"""

import os
import uuid
import logging
import tempfile
from flask import Flask, request, jsonify

from config.settings import (
    SHEETS_ID, SOUNDS_FOLDER_ID,
    PROCESSED_FOLDER_ID, NOTIFICATION_EMAIL, GCS_BUCKET
)
from processor.drive_handler import (
    download_file, get_random_sound, upload_clip,
    get_or_create_creator_folder
)
from processor.sheets_handler import get_rotating_titles
from processor.video_processor import process_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/process", methods=["POST"])
def process():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    creator_name       = data.get("creator_name", "unknown")
    job_id             = data.get("job_id") or str(uuid.uuid4())[:8].upper()
    output_folder_id   = data.get("output_folder_id") or PROCESSED_FOLDER_ID

    # ── Determine input source ────────────────────────────────────────────────
    gcs_uri        = data.get("gcs_uri")          # From Telegram bot
    video_file_id  = data.get("video_file_id")    # From Apps Script

    if not gcs_uri and not video_file_id:
        return jsonify({"error": "Provide either gcs_uri or video_file_id"}), 400

    logger.info(f"[{job_id}] Job started — creator={creator_name} source={'GCS' if gcs_uri else 'Drive'}")

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── Download source video ─────────────────────────────────────────────
        video_path = os.path.join(tmpdir, "source_video.mp4")
        try:
            if gcs_uri:
                _download_from_gcs(gcs_uri, video_path)
                logger.info(f"[{job_id}] Downloaded from GCS")
            else:
                download_file(video_file_id, video_path)
                logger.info(f"[{job_id}] Downloaded from Drive")
        except Exception as e:
            logger.error(f"[{job_id}] Download failed: {e}")
            return jsonify({"error": f"Download failed: {e}"}), 500

        # ── Download random sound ─────────────────────────────────────────────
        sound_path = None
        sound_info = get_random_sound(SOUNDS_FOLDER_ID)
        if sound_info:
            sound_id, sound_name = sound_info
            sound_path = os.path.join(tmpdir, sound_name)
            try:
                download_file(sound_id, sound_path)
                logger.info(f"[{job_id}] Sound: {sound_name}")
            except Exception as e:
                logger.warning(f"[{job_id}] Sound download failed: {e}")
                sound_path = None

        # ── Get rotating titles from Sheets ───────────────────────────────────
        try:
            from moviepy.editor import VideoFileClip
            probe = VideoFileClip(video_path)
            estimated_clips = int(probe.duration // 7)
            probe.close()
        except Exception:
            estimated_clips = 42  # Safe default

        try:
            titles = get_rotating_titles(SHEETS_ID, estimated_clips)
            logger.info(f"[{job_id}] Got {len(titles)} titles from Sheets")
        except Exception as e:
            logger.warning(f"[{job_id}] Sheets error: {e}")
            titles = ["Follow for more 🐰", "Link in bio 👇🔥", "She moves different 🔥"]

        # ── Process video ─────────────────────────────────────────────────────
        clip_output_dir = os.path.join(tmpdir, "clips")
        logger.info(f"[{job_id}] Processing video...")
        result = process_video(
            input_path=video_path,
            job_id=job_id,
            titles=titles,
            sound_local_path=sound_path,
            output_dir=clip_output_dir
        )

        if "error" in result:
            return jsonify({"error": result["error"]}), 500

        clip_count  = result["clip_count"]
        clip_paths  = result["clip_paths"]

        # ── Upload clips to Drive ─────────────────────────────────────────────
        logger.info(f"[{job_id}] Uploading {clip_count} clips to Drive...")
        creator_folder_id = get_or_create_creator_folder(creator_name, output_folder_id)

        from processor.drive_handler import get_drive_service
        drive = get_drive_service()
        job_folder_meta = {
            "name": f"job_{job_id}",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [creator_folder_id]
        }
        job_folder  = drive.files().create(
            body=job_folder_meta,
            fields="id, webViewLink"
        ).execute()
        job_folder_id   = job_folder["id"]
        folder_link     = job_folder.get("webViewLink", "")

        uploaded = 0
        for clip_path in clip_paths:
            try:
                upload_clip(clip_path, job_folder_id, os.path.basename(clip_path))
                uploaded += 1
            except Exception as e:
                logger.error(f"[{job_id}] Upload error: {e}")

        logger.info(f"[{job_id}] ✅ {uploaded}/{clip_count} clips uploaded to {folder_link}")

        # ── Send email notification (if configured) ───────────────────────────
        if NOTIFICATION_EMAIL:
            try:
                _send_notification(creator_name, clip_count, folder_link, job_id)
            except Exception as e:
                logger.warning(f"[{job_id}] Email failed: {e}")

        return jsonify({
            "job_id":          job_id,
            "creator":         creator_name,
            "clips_processed": clip_count,
            "clips_uploaded":  uploaded,
            "job_folder_id":   job_folder_id,  # Returned to bot for ZIP building
            "folder_link":     folder_link,
            "errors":          result.get("errors", [])
        })


def _download_from_gcs(gcs_uri: str, destination: str):
    """Download a file from GCS given a gs:// URI."""
    from google.cloud import storage as gcs_lib
    from processor.gcp_auth import get_credentials
    # Parse gs://bucket/path
    path = gcs_uri.replace("gs://", "")
    bucket_name, blob_name = path.split("/", 1)
    creds = get_credentials(scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
    client = gcs_lib.Client(credentials=creds, project=creds.project_id)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(destination)


def _send_notification(creator_name: str, clip_count: int, folder_link: str, job_id: str):
    """Send email via Resend if API key is set."""
    import resend
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return
    resend.api_key = api_key
    resend.Emails.send({
        "from": "Bunny Clip Tool <noreply@bink.bio>",
        "to": [NOTIFICATION_EMAIL],
        "subject": f"✅ {clip_count} Clips Ready — {creator_name}",
        "text": (
            f"{clip_count} clips for {creator_name} are ready.\n"
            f"Job ID: {job_id}\n"
            f"Drive folder: {folder_link}\n\n"
            f"— Bunny Clip Tool"
        ),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
