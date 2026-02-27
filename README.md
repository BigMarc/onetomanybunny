# Bunny Clip Tool

**Bunny Agency LLC — Automated Video Clip Pipeline**

Creators send a 5-minute dance video via Telegram. The bot cuts it into 7-second clips, adds rotating on-screen text (from Google Sheets) and licensed background music (from Google Drive), uploads clips to the creator's Drive folder, builds a ZIP, and sends the creator two buttons: **[Download ZIP]** and **[Open Drive Folder]**. Zero staff involvement after initial setup.

---

## Architecture

```
Creator sends video via Telegram
        |
        v
  [Telegram Bot]  (Cloud Run: bunny-clip-bot)
        |
        |  1. Downloads video from Telegram
        |  2. Uploads to Google Cloud Storage
        |  3. POSTs to processor /process endpoint
        v
  [Video Processor]  (Cloud Run: bunny-clip-processor)
        |
        |  1. Downloads video from GCS (or Drive)
        |  2. Gets rotating titles from Google Sheets
        |  3. Picks random MP3 from Drive sounds folder
        |  4. Cuts video into 7-sec clips (MoviePy/FFmpeg)
        |  5. Adds text overlay + background music per clip
        |  6. Uploads all clips to creator's Drive folder
        v
  [Bot receives result]
        |
        |  1. Downloads all clips from Drive
        |  2. Builds ZIP archive
        |  3. Uploads ZIP to Drive (public link)
        |  4. Sends Telegram message with buttons:
        |     [Download ZIP]  [Open Drive Folder]
        v
  Creator gets their clips!
```

There are **two input modes**:
- **Telegram Bot** (primary): creators send videos directly to the bot
- **Google Apps Script** (automated): monitors Drive folders every 5 minutes for new uploads

All state is persisted in Google Sheets (3 tabs: Titles, Registry, Jobs) — no separate database needed.

---

## File Structure

```
bunny-clip-tool/
├── main.py                        # Flask app: /health + /process endpoints (Cloud Run)
├── run_bot.py                     # Bot entry point (loads .env, starts bot)
├── app.py                         # Local web UI (for manual testing, not deployed)
├── setup_sheets.py                # One-time Google Sheets tab/header setup
├── deploy.sh                      # Full Cloud Run deployment script
├── apps_script.js                 # Google Apps Script for Drive folder monitoring
├── Dockerfile                     # Video processor service (FFmpeg + Python)
├── Dockerfile.bot                 # Telegram bot service (lightweight)
├── requirements.txt               # All Python dependencies
├── .env.example                   # Environment variable template
├── .gitignore                     # Excludes .env, service_account.json, etc.
├── SETUP_CHECKLIST.md             # Quick-reference setup steps
│
├── config/
│   ├── __init__.py
│   ├── settings.py                # Centralized env var config
│   └── templates.json             # 30 title presets, sound library, clip settings
│
├── processor/
│   ├── __init__.py
│   ├── video_processor.py         # MoviePy: cuts video, adds text + music
│   ├── drive_handler.py           # Drive: download, upload, folder management
│   └── sheets_handler.py          # Sheets: rotating title logic + Last Used tracking
│
└── telegram_bot/
    ├── __init__.py
    ├── bot.py                     # Telegram bot: all handlers, flow, notifications
    ├── creator_registry.py        # Maps Telegram user IDs <-> creator names (via Sheets)
    ├── job_tracker.py             # Job state persistence in Sheets "Jobs" tab
    └── zip_builder.py             # Downloads clips from Drive, builds ZIP, re-uploads
```

---

## Getting Started (Step by Step)

### 1. Google Cloud Project Setup

```bash
# Create project (or use existing one)
gcloud projects create bunny-clip-tool --name="Bunny Clip Tool"
gcloud config set project bunny-clip-tool

# Enable billing (required — do this in console.cloud.google.com)

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  sheets.googleapis.com \
  drive.googleapis.com
```

### 2. Service Account

```bash
# Create service account
gcloud iam service-accounts create bunny-clip-runner \
  --display-name="Bunny Clip Tool Runner"

# Grant roles
PROJECT_ID="bunny-clip-tool"
SA_EMAIL="bunny-clip-runner@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/run.invoker"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/secretmanager.secretAccessor"

# Download key file
gcloud iam service-accounts keys create service_account.json \
  --iam-account=$SA_EMAIL
```

### 3. Google Cloud Storage Bucket

```bash
# Create bucket for temporary video uploads
gsutil mb -l us-central1 gs://bunny-clip-tool-videos

# Set 7-day lifecycle (auto-delete old uploads)
cat > /tmp/lifecycle.json << 'EOF'
{
  "rule": [{
    "action": {"type": "Delete"},
    "condition": {"age": 7}
  }]
}
EOF
gsutil lifecycle set /tmp/lifecycle.json gs://bunny-clip-tool-videos
```

### 4. Google Drive Setup

Create this folder structure in Google Drive:

```
Bunny Clip Tool/
├── _SOUNDS LIBRARY/         # Upload MP3 files here (5+ tracks)
├── _PROCESSED/               # Output clips go here automatically
└── CREATORS/
    ├── Sofia/
    │   └── UPLOAD HERE/      # Share with creator's Google account
    ├── Lena/
    │   └── UPLOAD HERE/
    └── (one per creator)
```

**Important sharing steps:**
1. Share the **root folder** (`Bunny Clip Tool/`) with your service account email (`bunny-clip-runner@bunny-clip-tool.iam.gserviceaccount.com`) as **Editor**
2. Share each creator's `UPLOAD HERE` folder with the creator's personal Google account as **Editor**

**How to find folder IDs:** Open the folder in Google Drive. The URL looks like:
```
https://drive.google.com/drive/folders/1ABCxyz123...
                                        ↑ This is the folder ID
```

You need the folder IDs for:
- `_SOUNDS LIBRARY` → goes in `SOUNDS_FOLDER_ID`
- `_PROCESSED` → goes in `PROCESSED_FOLDER_ID`

### 5. Google Sheet

1. Create a new Google Sheet (any name, e.g., "Bunny Clip Tool Data")
2. Share it with your service account email as **Editor**
3. Copy the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/1ABCxyz123.../edit
                                           ↑ This is the Sheet ID
   ```

### 6. Telegram Bot

1. Message **@BotFather** on Telegram
2. Send `/newbot`
3. Follow the prompts to name your bot
4. Copy the bot token (looks like `1234567890:AABCD...`)

### 7. Get Your Telegram User ID

1. Message **@userinfobot** on Telegram
2. It replies with your user ID (a number like `123456789`)
3. This goes in `ADMIN_TELEGRAM_IDS`

### 8. SendGrid (for email notifications)

1. Sign up at [sendgrid.com](https://sendgrid.com)
2. Verify your sender domain
3. Create an API key (Settings > API Keys > Create API Key)
4. Copy the key for `SENDGRID_API_KEY`

### 9. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and fill in every value:

| Variable | Where to find it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather (step 6) |
| `ADMIN_TELEGRAM_IDS` | From @userinfobot (step 7). Comma-separated for multiple admins |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to `service_account.json` (step 2) |
| `GCS_BUCKET` | `bunny-clip-tool-videos` (step 3) |
| `CLOUD_RUN_URL` | Leave blank — auto-filled by deploy.sh |
| `SHEETS_ID` | From Google Sheet URL (step 5) |
| `SOUNDS_FOLDER_ID` | Drive folder ID of `_SOUNDS LIBRARY` (step 4) |
| `PROCESSED_FOLDER_ID` | Drive folder ID of `_PROCESSED` (step 4) |
| `NOTIFICATION_EMAIL` | Your email for job notifications |
| `SENDGRID_API_KEY` | From SendGrid dashboard (step 8) |
| `CLIP_DURATION` | `7` (seconds per clip) |
| `TEXT_FONT_SIZE` | `52` |
| `TEXT_POSITION` | `bottom` |

### 10. Initialize Google Sheet

```bash
python setup_sheets.py
```

This creates 3 tabs (Titles, Registry, Jobs) with headers and 30 sample titles.

### 11. Upload Sound Files

Upload at least 5 MP3 files to your `_SOUNDS LIBRARY` folder in Google Drive. These are the background music tracks that get randomly applied to clips.

### 12. Deploy

```bash
bash deploy.sh
```

This deploys both Cloud Run services and auto-updates `CLOUD_RUN_URL` in your `.env`.

For subsequent code-only deploys (no secrets changes):
```bash
bash deploy.sh --update
```

### 13. Set Up Apps Script (Optional — Drive Folder Monitor)

1. Go to [script.google.com](https://script.google.com)
2. Create a new project
3. Paste the contents of `apps_script.js`
4. Fill in `CLOUD_RUN_URL`, `CREATOR_FOLDERS`, and `NOTIFY_EMAIL`
5. Select `installTrigger` from the function dropdown and click Run
6. Approve OAuth permissions when prompted

This monitors each creator's `UPLOAD HERE` folder every 5 minutes and automatically triggers processing.

---

## How It Works — End to End

### Telegram Flow (Primary)

1. **Admin registers a creator:** `/register Sofia` in Telegram, then Sofia sends any message to the bot
2. **Creator sends a video** to the bot
3. **Bot acknowledges** with clip estimate and ETA
4. **Bot downloads** video from Telegram, uploads to GCS
5. **Bot triggers** Cloud Run processor via POST `/process`
6. **Processor** downloads video, gets titles from Sheets, picks random sound from Drive, cuts clips, uploads to Drive
7. **Bot builds ZIP** from clips in Drive, makes it publicly accessible
8. **Bot sends** two buttons to creator: [Download ZIP] and [Open Drive Folder]

### Apps Script Flow (Automated)

1. Creator drops a video into their `UPLOAD HERE` Drive folder
2. Apps Script (running every 5 min) detects the new file
3. Renames file to `[PROCESSING] original_name.mp4`
4. POSTs to Cloud Run `/process` with the Drive file ID
5. On success: renames to `[DONE] original_name.mp4`, sends email
6. On failure: renames to `[FAILED] original_name.mp4`, sends email

### Google Sheets Structure

**Titles tab** — rotating text overlays
| Title Text | Category | Active (TRUE/FALSE) | Last Used |
|---|---|---|---|
| She moves different | hype | TRUE | 2024-01-15T10:30:00 |

**Registry tab** — creator Telegram ID mapping
| Telegram ID | Creator Name | Output Folder ID | Registered At |
|---|---|---|---|
| 123456789 | Sofia | 1abc... | 2024-01-15 |

**Jobs tab** — job tracking
| Job ID | Telegram Chat ID | Creator Name | Status | Clip Count | Folder Link | Started At | Finished At |
|---|---|---|---|---|---|---|---|

---

## Admin Commands (Telegram)

| Command | What it does |
|---|---|
| `/register <name>` | Register the next person who messages as a creator |
| `/creators` | List all registered creators |
| `/status <job_id>` | Check any job's status |
| `/help` | Show creator instructions |

---

## Local Development

### Run the Web UI (for manual testing)

```bash
# Install dependencies
pip install -r requirements.txt

# Run local web app
python app.py
# Open http://localhost:5050
```

The web UI at `app.py` lets you upload videos and test clip generation locally without Telegram or Cloud Run. It uses local file storage instead of Drive/GCS.

### Run the Bot Locally

```bash
# Fill in .env first
python run_bot.py
```

Note: the bot needs `CLOUD_RUN_URL` pointing to a deployed processor, or you can run the processor locally too:

```bash
# Terminal 1: Run processor
python -c "from main import app; app.run(port=8080)"

# Terminal 2: Run bot (set CLOUD_RUN_URL=http://localhost:8080 in .env)
python run_bot.py
```

---

## Configuration Reference (`config/templates.json`)

| Key | What it does |
|---|---|
| `title_presets` | Array of text titles shown on clips |
| `text_styles` | Font size, color, position presets |
| `sound_library` | Music tracks (for local web UI mode) |
| `clip_settings.clip_duration_seconds` | Default clip length (7) |
| `clip_settings.fade_in_seconds` | Fade in per clip (0.3) |
| `clip_settings.fade_out_seconds` | Fade out per clip (0.3) |
| `clip_settings.audio_volume` | Music volume 0.0-1.0 (0.85) |
| `clip_settings.output_fps` | Output frame rate (30) |

---

## Troubleshooting

### Bot doesn't respond to /start
- Check `TELEGRAM_BOT_TOKEN` is correct
- Make sure the bot is running: `gcloud run services describe bunny-clip-bot --region us-central1`
- Check logs: `gcloud run services logs read bunny-clip-bot --region us-central1`

### "You're not registered" error
- An admin needs to run `/register CreatorName` first
- Then the creator sends any message to complete registration

### Video processing fails
- Check Cloud Run logs: `gcloud run services logs read bunny-clip-processor --region us-central1`
- Ensure the service account has access to the Drive folders
- Check that the GCS bucket exists and is accessible

### No sound on clips
- Upload MP3 files to the `_SOUNDS LIBRARY` Drive folder
- Ensure `SOUNDS_FOLDER_ID` in `.env` matches the folder ID
- The service account must have access to the folder

### ZIP download link doesn't work
- The ZIP is shared as "anyone with link" — this should work automatically
- Check Drive permissions on the output folder

---

*Bunny Agency LLC — Internal Tools*
