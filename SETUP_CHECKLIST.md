# Bunny Clip Tool — Setup Checklist

## Prerequisites (do manually, ~30 min)
- [ ] Google Cloud project `bunny-clip-tool` created with billing enabled
- [ ] APIs enabled:
  ```bash
  gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    secretmanager.googleapis.com \
    storage.googleapis.com \
    sheets.googleapis.com \
    drive.googleapis.com
  ```
- [ ] Service account `bunny-clip-runner` created with roles: Storage Admin, Run Invoker, Secret Manager Accessor
- [ ] `service_account.json` downloaded to project root
- [ ] GCS bucket `bunny-clip-tool-videos` created (set 7-day lifecycle rule)
- [ ] Drive folders created: `_SOUNDS LIBRARY`, `_PROCESSED`, `CREATORS/[Name]/UPLOAD HERE`
- [ ] Root Drive folder shared with service account email (Editor)
- [ ] Creator `UPLOAD HERE` folders shared with each creator's Google account (Editor)
- [ ] Google Sheet created with 3 tabs, shared with service account (Editor)
- [ ] SendGrid account created, domain verified, API key copied

## Run These Commands (in order)
1. `cp .env.example .env` → fill in ALL values
2. `python setup_sheets.py` → creates Titles/Registry/Jobs tabs with headers
3. `bash deploy.sh` → deploys both Cloud Run services
4. Copy processor URL → paste into `.env` as `CLOUD_RUN_URL` → redeploy bot
5. Paste `apps_script.js` code into script.google.com → run `installTrigger()`
6. Upload 5+ MP3s to `_SOUNDS LIBRARY` Drive folder

## Test Before Going Live
- [ ] `/start` in Telegram bot responds
- [ ] Register one creator: `/register TestName` → they send any message
- [ ] Send a 30-second test video to bot
- [ ] Clips appear in Drive `_PROCESSED` folder
- [ ] ZIP download link works
- [ ] Email notification received
- [ ] Google Sheet Jobs tab shows completed job
