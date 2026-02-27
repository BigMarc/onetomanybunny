# 🐰 Bunny Clip Tool

**Internal tool — Bunny Agency LLC**  
Automatically cuts 5-minute creator videos into 7-second clips with text overlays and background music.

---

## What It Does

1. Creator uploads a 5-minute dance video (per the SOP)
2. Staff uploads to this tool
3. Tool cuts every 7 seconds → individual clips
4. Each clip gets a text title + background music
5. Staff downloads a `.zip` of all clips and posts them

---

## Tech Stack

- **Backend:** Python / Flask
- **Video processing:** MoviePy (FFmpeg)
- **Frontend:** Vanilla HTML/CSS/JS (zero dependencies)
- **Config:** JSON (easily editable titles, sounds, settings)

---

## Setup (Local)

```bash
# 1. Clone repo
git clone https://github.com/YOUR_ORG/bunny-clip-tool.git
cd bunny-clip-tool

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add sound files
# Place .mp3 files into static/sounds/
# File names must match those in config/templates.json

# 5. Run the app
python app.py

# Open http://localhost:5050 in your browser
```

---

## Adding Sounds

1. Drop your `.mp3` files into `static/sounds/`
2. Edit `config/templates.json` → `sound_library` array
3. Add an entry like:
```json
{
  "id": "my_track",
  "name": "My Track Name",
  "file": "my_track.mp3",
  "bpm": 110,
  "mood": "chill"
}
```

---

## Editing Titles

**Option A — In the web UI:**  
Go to the Titles panel → edit/add/delete → hit "Save List"

**Option B — Directly in config:**  
Edit `config/templates.json` → `title_presets` array

---

## Folder Structure

```
bunny-clip-tool/
├── app.py                          # Flask server
├── requirements.txt
├── SOP_CREATOR_DANCE_VIDEO.md      # Creator SOP
├── config/
│   └── templates.json              # Titles, sounds, clip settings
├── processor/
│   └── video_processor.py          # Core video cutting logic
├── templates/
│   └── index.html                  # Web UI
└── static/
    ├── uploads/                    # Uploaded source videos (temp)
    ├── outputs/                    # Generated clips + zips
    ├── sounds/                     # MP3 files (you add these)
    └── thumbnails/                 # Future: clip thumbnails
```

---

## Configuration Reference (`config/templates.json`)

| Key | What it does |
|---|---|
| `title_presets` | Array of text titles shown on clips |
| `text_styles` | Font size, color, position presets |
| `sound_library` | Music tracks available in the tool |
| `clip_settings.clip_duration_seconds` | Default clip length (7) |
| `clip_settings.fade_in_seconds` | Fade in per clip |
| `clip_settings.fade_out_seconds` | Fade out per clip |
| `clip_settings.audio_volume` | Music volume (0.0–1.0) |
| `clip_settings.output_fps` | Output frame rate |

---

## Deployment (Production)

```bash
# Install gunicorn
pip install gunicorn

# Run with gunicorn
gunicorn -w 2 -b 0.0.0.0:5050 app:app
```

For production: put behind Nginx, use a job queue (Celery + Redis) instead of threading, store outputs in S3.

---

## Future Features (Roadmap)

- [ ] Thumbnail preview grid per clip
- [ ] Clip selection (pick which 7-sec moments to keep)
- [ ] Multiple text position options per clip
- [ ] Creator portal with login
- [ ] Direct S3/Cloudflare R2 upload
- [ ] Celery job queue for parallel processing
- [ ] Auto-post to Buffer/scheduling tool
- [ ] Analytics dashboard (which clips got best engagement)

---

## GitHub Setup for Your Team

```bash
# First time setup
git init
git add .
git commit -m "Initial commit — Bunny Clip Tool"
git remote add origin https://github.com/YOUR_ORG/bunny-clip-tool.git
git push -u origin main
```

Add to `.gitignore`:
```
venv/
static/uploads/*
static/outputs/*
*.pyc
__pycache__/
.env
```

---

*Bunny Agency LLC — Internal Tools*
