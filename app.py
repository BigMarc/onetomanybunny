"""
Bunny Clip Tool — Local Web App (single file)
==============================================
Run:  python app.py
Open: http://localhost:5050
Upload a video → get 7-second clips with text + music → download ZIP.
No Telegram. No Cloud Run. No Docker. Just your browser.
"""

import os
import json
import uuid
import random
import threading
import zipfile
import logging
from pathlib import Path
from flask import Flask, request, jsonify, send_file, Response
from dotenv import load_dotenv

load_dotenv()

# ── Setup ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
UPLOAD_FOLDER = BASE_DIR / "tmp" / "uploads"
OUTPUT_FOLDER = BASE_DIR / "tmp" / "clips"
ZIPS_FOLDER   = BASE_DIR / "tmp" / "zips"
SOUNDS_FOLDER = BASE_DIR / "static" / "sounds"
CONFIG_PATH   = BASE_DIR / "config" / "templates.json"

for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, ZIPS_FOLDER, SOUNDS_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB

ALLOWED_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm"}
JOBS: dict = {}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_local_sound():
    """Pick a random MP3 from the static/sounds/ folder, if any exist."""
    sounds = list(SOUNDS_FOLDER.glob("*.mp3")) + list(SOUNDS_FOLDER.glob("*.wav"))
    if sounds:
        chosen = random.choice(sounds)
        logger.info(f"Using local sound: {chosen.name}")
        return str(chosen)
    return None


# ── HTML (embedded — no templates needed) ─────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Bunny Clip Tool</title>
  <style>
    :root {
      --pink: #ff4fa0; --dark-pink: #d63b85;
      --bg: #0d0d0f; --surface: #18181b; --surface2: #232328;
      --border: #2e2e36; --text: #f0f0f5; --muted: #888;
      --green: #22c55e; --yellow: #f59e0b; --red: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: var(--bg); color: var(--text); min-height: 100vh;
    }
    header {
      background: var(--surface); border-bottom: 1px solid var(--border);
      padding: 16px 32px; display: flex; align-items: center; gap: 12px;
    }
    header h1 { font-size: 20px; font-weight: 700; }
    header .badge {
      background: var(--pink); color: white; font-size: 11px;
      padding: 2px 8px; border-radius: 99px; font-weight: 600;
    }
    .container {
      max-width: 700px; margin: 0 auto; padding: 32px 24px;
    }
    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 24px; margin-bottom: 24px;
    }
    .card h2 {
      font-size: 15px; font-weight: 600; margin-bottom: 18px;
      display: flex; align-items: center; gap: 8px;
    }
    label {
      display: block; font-size: 12px; font-weight: 600; color: var(--muted);
      margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em;
    }
    input[type="text"], input[type="number"], select {
      width: 100%; background: var(--surface2); border: 1px solid var(--border);
      color: var(--text); border-radius: 8px; padding: 10px 12px; font-size: 14px;
      margin-bottom: 16px; outline: none; font-family: inherit;
    }
    input:focus, select:focus { border-color: var(--pink); }
    .upload-zone {
      border: 2px dashed var(--border); border-radius: 10px; padding: 32px;
      text-align: center; cursor: pointer; margin-bottom: 16px; position: relative;
    }
    .upload-zone:hover { border-color: var(--pink); background: rgba(255,79,160,0.05); }
    .upload-zone input[type="file"] {
      position: absolute; inset: 0; opacity: 0; cursor: pointer; margin: 0;
    }
    .upload-zone .icon { font-size: 36px; margin-bottom: 8px; }
    .upload-zone p { font-size: 14px; color: var(--muted); }
    .file-name { color: var(--pink); font-weight: 600; margin-top: 8px; font-size: 13px; }
    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 8px;
      padding: 12px 24px; border-radius: 8px; font-size: 14px; font-weight: 600;
      border: none; cursor: pointer; width: 100%;
    }
    .btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .btn-pink { background: var(--pink); color: white; }
    .btn-pink:hover:not(:disabled) { background: var(--dark-pink); }
    .status-panel { display: none; }
    .status-panel.visible { display: block; }
    .job-status {
      display: flex; align-items: center; gap: 10px; padding: 14px 16px;
      background: var(--surface2); border-radius: 8px; margin-bottom: 14px;
      border: 1px solid var(--border);
    }
    .status-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
    .status-dot.queued { background: var(--yellow); }
    .status-dot.processing { background: var(--pink); animation: pulse 1s infinite; }
    .status-dot.done { background: var(--green); }
    .status-dot.error { background: var(--red); }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
    .result-info { font-size: 13px; color: var(--muted); margin-bottom: 14px; }
    .result-info strong { color: var(--text); }
  </style>
</head>
<body>

<header>
  <span style="font-size:24px">&#x1F430;</span>
  <h1>Bunny Clip Tool</h1>
  <span class="badge">Local</span>
</header>

<div class="container">

  <div class="card">
    <h2>Upload Video</h2>

    <label>Creator Name</label>
    <input type="text" id="creatorName" placeholder="e.g. Sofia, Lena, Maria..." />

    <label>Video File</label>
    <div class="upload-zone" id="uploadZone">
      <input type="file" id="videoFile" accept="video/*" />
      <div class="icon">&#x1F3AC;</div>
      <p>Drag & drop or click to select video</p>
      <p style="font-size:11px; margin-top:4px; color:#555">MP4, MOV, AVI, MKV &bull; Max 4 GB</p>
      <div class="file-name" id="fileName"></div>
    </div>

    <label>Clip Duration (seconds)</label>
    <input type="number" id="clipDuration" value="7" min="3" max="60" />

    <button class="btn btn-pink" id="processBtn" disabled onclick="startProcessing()">
      Cut & Process Video
    </button>
  </div>

  <div class="card status-panel" id="statusPanel">
    <h2>Processing Status</h2>
    <div class="job-status">
      <div class="status-dot queued" id="statusDot"></div>
      <div>
        <div style="font-weight:600; font-size:14px" id="statusText">Waiting...</div>
        <div style="font-size:12px; color:var(--muted)" id="statusSub">Job ID: &mdash;</div>
      </div>
    </div>
    <div class="result-info" id="resultInfo"></div>
    <button class="btn btn-pink" id="downloadBtn" style="display:none" onclick="downloadZip()">
      Download All Clips (.zip)
    </button>
  </div>

</div>

<script>
  let currentJobId = null;
  let pollInterval = null;

  document.getElementById("videoFile").addEventListener("change", function() {
    const file = this.files[0];
    if (file) {
      document.getElementById("fileName").textContent = file.name + " (" + (file.size/1e6).toFixed(1) + " MB)";
      document.getElementById("processBtn").disabled = false;
    }
  });

  async function startProcessing() {
    const file = document.getElementById("videoFile").files[0];
    if (!file) return alert("Please select a video file.");

    const btn = document.getElementById("processBtn");
    btn.disabled = true;
    btn.textContent = "Uploading...";

    const formData = new FormData();
    formData.append("video", file);
    formData.append("creator_name", document.getElementById("creatorName").value || "unknown");
    formData.append("clip_duration", document.getElementById("clipDuration").value);

    try {
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (data.error) throw new Error(data.error);

      currentJobId = data.job_id;
      showStatus(data.job_id);
      startPolling(data.job_id);
    } catch (err) {
      alert("Upload failed: " + err.message);
      btn.disabled = false;
      btn.textContent = "Cut & Process Video";
    }
  }

  function showStatus(jobId) {
    document.getElementById("statusPanel").classList.add("visible");
    document.getElementById("statusPanel").scrollIntoView({ behavior: "smooth" });
    document.getElementById("statusSub").textContent = "Job ID: " + jobId;
  }

  function startPolling(jobId) {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => pollJob(jobId), 2500);
  }

  async function pollJob(jobId) {
    try {
      const res = await fetch("/api/job/" + jobId);
      const data = await res.json();
      updateUI(data);
      if (["done", "partial", "error"].includes(data.status)) {
        clearInterval(pollInterval);
        document.getElementById("processBtn").disabled = false;
        document.getElementById("processBtn").textContent = "Cut & Process Video";
      }
    } catch (e) { console.error(e); }
  }

  function updateUI(job) {
    const dot = document.getElementById("statusDot");
    const txt = document.getElementById("statusText");
    const info = document.getElementById("resultInfo");
    const dlBtn = document.getElementById("downloadBtn");

    dot.className = "status-dot " + job.status;

    const labels = {
      queued: "Queued — waiting to start...",
      processing: "Processing clips...",
      done: "Done! " + job.clip_count + " clips ready",
      partial: "Partial — " + job.clip_count + " clips done (some errors)",
      error: "Error: " + (job.error_message || "Unknown error")
    };
    txt.textContent = labels[job.status] || job.status;

    if (job.clip_count > 0) {
      info.innerHTML = "<strong>" + job.clip_count + " clips</strong> generated";
    }

    if (["done", "partial"].includes(job.status) && job.clip_count > 0) {
      dlBtn.style.display = "flex";
    }
  }

  function downloadZip() {
    if (currentJobId) window.location.href = "/api/download/" + currentJobId;
  }
</script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/upload", methods=["POST"])
def upload_video():
    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    file = request.files["video"]
    if not file.filename or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Allowed: mp4, mov, avi, mkv, webm"}), 400

    creator_name = request.form.get("creator_name", "unknown")

    # Save upload
    job_id = str(uuid.uuid4())[:8].upper()
    ext = file.filename.rsplit(".", 1)[1].lower()
    save_path = UPLOAD_FOLDER / f"{job_id}.{ext}"
    file.save(str(save_path))

    logger.info(f"[{job_id}] Upload saved: {save_path} ({save_path.stat().st_size / 1e6:.1f} MB)")

    JOBS[job_id] = {
        "status": "queued",
        "creator": creator_name,
        "clip_count": 0,
        "errors": [],
    }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, str(save_path), creator_name),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id, "status": "queued"})


def _run_job(job_id: str, input_path: str, creator_name: str):
    """Background worker — processes video into clips."""
    from processor.video_processor import process_video

    JOBS[job_id]["status"] = "processing"

    try:
        # Get titles from config
        config = load_config()
        titles = config.get("title_presets", [])

        # Find a local sound file (if any MP3s in static/sounds/)
        sound_path = _find_local_sound()

        # Process
        result = process_video(
            input_path=input_path,
            job_id=job_id,
            titles=titles,
            sound_local_path=sound_path,
            output_dir=str(OUTPUT_FOLDER / job_id),
        )

        if "error" in result:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error_message"] = result["error"]
            return

        clip_paths = result.get("clip_paths", [])
        clip_count = result.get("clip_count", 0)

        # Build ZIP
        zip_path = ZIPS_FOLDER / f"{job_id}.zip"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            for cp in clip_paths:
                if os.path.exists(cp):
                    zf.write(cp, Path(cp).name)

        JOBS[job_id].update({
            "status": "done" if not result.get("errors") else "partial",
            "clip_count": clip_count,
            "clip_paths": clip_paths,
            "zip_path": str(zip_path),
            "errors": result.get("errors", []),
        })

        logger.info(f"[{job_id}] Done: {clip_count} clips, ZIP at {zip_path}")

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
    job = JOBS.get(job_id)
    if not job or job["status"] not in ("done", "partial"):
        return jsonify({"error": "Job not ready or not found"}), 404

    zip_path = job.get("zip_path")
    if not zip_path or not os.path.exists(zip_path):
        return jsonify({"error": "ZIP file not found"}), 404

    return send_file(zip_path, as_attachment=True, download_name=f"bunny_clips_{job_id}.zip")


if __name__ == "__main__":
    print()
    print("  Bunny Clip Tool running at: http://localhost:5050")
    print("  Open that URL in your browser.")
    print("  Press Ctrl+C to stop.")
    print()
    app.run(debug=False, host="0.0.0.0", port=5050)
