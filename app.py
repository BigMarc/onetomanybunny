"""
Bunny Clip Tool — Flask Web App
Upload a video → get 7-second clips with text + music, ready to post.
"""

import os
import json
import uuid
import threading
import zipfile
import logging
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, url_for

# ── Setup ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
OUTPUT_FOLDER = BASE_DIR / "static" / "outputs"
SOUNDS_FOLDER = BASE_DIR / "static" / "sounds"
CONFIG_PATH   = BASE_DIR / "config" / "templates.json"

for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, SOUNDS_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB

ALLOWED_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm"}
JOBS: dict = {}  # In-memory job store (swap for Redis/DB in production)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    config = load_config()
    return render_template(
        "index.html",
        titles=config["title_presets"],
        sounds=config["sound_library"],
        text_styles=list(config["text_styles"].keys()),
    )


@app.route("/api/upload", methods=["POST"])
def upload_video():
    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    file = request.files["video"]
    if not file.filename or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Allowed: mp4, mov, avi, mkv, webm"}), 400

    # Parse custom titles from form
    raw_titles = request.form.get("custom_titles", "")
    custom_titles = [t.strip() for t in raw_titles.split("\n") if t.strip()] or None

    sound_id = request.form.get("sound_id") or None
    text_style = request.form.get("text_style", "default")
    clip_duration = int(request.form.get("clip_duration", 7))
    creator_name = request.form.get("creator_name", "unknown")

    # Save upload
    job_id = str(uuid.uuid4())[:8]
    ext = file.filename.rsplit(".", 1)[1].lower()
    save_path = UPLOAD_FOLDER / f"{job_id}.{ext}"
    file.save(str(save_path))

    logger.info(f"[{job_id}] Upload saved: {save_path} ({save_path.stat().st_size / 1e6:.1f} MB)")

    # Register job
    JOBS[job_id] = {
        "status": "queued",
        "creator": creator_name,
        "progress": 0,
        "clip_count": 0,
        "errors": [],
    }

    # Process in background thread
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, str(save_path), custom_titles, sound_id, text_style, clip_duration),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id, "status": "queued"})


def _run_job(job_id, input_path, custom_titles, sound_id, text_style, clip_duration):
    """Background worker — runs video processing."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from processor.video_processor import process_video

    JOBS[job_id]["status"] = "processing"
    try:
        result = process_video(
            input_path=input_path,
            job_id=job_id,
            custom_titles=custom_titles,
            sound_id=sound_id,
            text_style_key=text_style,
            clip_duration=clip_duration,
        )
        JOBS[job_id].update({
            "status": result["status"],
            "clip_count": result.get("clip_count", 0),
            "output_dir": result.get("output_dir", ""),
            "clip_paths": result.get("clip_paths", []),
            "errors": result.get("errors", []),
            "titles_used": result.get("titles_used", []),
        })
        if "error" in result:
            JOBS[job_id]["error_message"] = result["error"]

    except Exception as e:
        logger.error(f"[{job_id}] Job crashed: {e}", exc_info=True)
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error_message"] = str(e)


@app.route("/api/job/<job_id>")
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/download/<job_id>")
def download_clips(job_id):
    """Zip all clips for a job and serve as download."""
    job = JOBS.get(job_id)
    if not job or job["status"] not in ("done", "partial"):
        return jsonify({"error": "Job not ready or not found"}), 404

    output_dir = Path(job["output_dir"])
    zip_path = OUTPUT_FOLDER / f"{job_id}_clips.zip"

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for clip_path in job.get("clip_paths", []):
            zf.write(clip_path, Path(clip_path).name)

    return send_file(str(zip_path), as_attachment=True, download_name=f"bunny_clips_{job_id}.zip")


@app.route("/api/titles", methods=["GET"])
def get_titles():
    config = load_config()
    return jsonify(config["title_presets"])


@app.route("/api/titles", methods=["POST"])
def save_titles():
    """Save updated title list to config."""
    data = request.json
    if not data or "titles" not in data:
        return jsonify({"error": "No titles provided"}), 400

    config = load_config()
    config["title_presets"] = data["titles"]
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    return jsonify({"saved": len(data["titles"]), "titles": data["titles"]})


@app.route("/api/sounds")
def get_sounds():
    config = load_config()
    return jsonify(config["sound_library"])


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5050)
