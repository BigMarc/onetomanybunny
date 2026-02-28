"""
Bunny Clip Tool — Local Processor Entry Point
===============================================

Accepts two input modes:

Mode A — FROM TELEGRAM BOT (local):
  POST /process
  { "local_path": "/abs/path/to/video.mp4",
    "job_id": "JOB123",
    "creator_name": "Sofia",
    "output_folder_id": "1abc..." }

Mode B — FROM APPS SCRIPT (Google Drive monitor):
  POST /process
  { "video_file_id": "1abc...",
    "creator_name": "Sofia" }

Both modes produce the same output: clips in Drive + local ZIP + JSON response.
"""

import os
import uuid
import logging
import zipfile
import tempfile
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

from config.settings import (
    SHEETS_ID, SOUNDS_FOLDER_ID,
    PROCESSED_FOLDER_ID, NOTIFICATION_EMAIL
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

# Local temp directories
LOCAL_ZIPS_DIR = os.environ.get("LOCAL_ZIPS_DIR", "./tmp/zips")
os.makedirs(LOCAL_ZIPS_DIR, exist_ok=True)


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
    local_path     = data.get("local_path")        # From Telegram bot (local)
    video_file_id  = data.get("video_file_id")      # From Apps Script

    if not local_path and not video_file_id:
        return jsonify({"error": "Provide local_path or video_file_id"}), 400

    logger.info(f"[{job_id}] Job started — creator={creator_name} source={'Local' if local_path else 'Drive'}")

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── Get source video path ──────────────────────────────────────────────
        if local_path:
            if not os.path.exists(local_path):
                return jsonify({"error": f"Local file not found: {local_path}"}), 400
            video_path = local_path
            logger.info(f"[{job_id}] Using local file: {video_path}")
        else:
            video_path = os.path.join(tmpdir, "source_video.mp4")
            try:
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

        # ── Build local ZIP ───────────────────────────────────────────────────
        zip_path = os.path.join(LOCAL_ZIPS_DIR, f"{job_id}.zip")
        zip_size_mb = 0
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for clip_path in clip_paths:
                    if os.path.exists(clip_path):
                        zf.write(clip_path, os.path.basename(clip_path))
            zip_size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 1)
            logger.info(f"[{job_id}] Local ZIP saved: {zip_path} ({zip_size_mb} MB)")
        except Exception as e:
            logger.warning(f"[{job_id}] Failed to build local ZIP: {e}")
            zip_path = ""

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
            "job_folder_id":   job_folder_id,
            "folder_link":     folder_link,
            "zip_path":        os.path.abspath(zip_path) if zip_path else "",
            "zip_size_mb":     zip_size_mb,
            "errors":          result.get("errors", [])
        })


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
