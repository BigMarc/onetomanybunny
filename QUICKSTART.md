# Bunny Clip Tool — Local Quickstart

## One-time setup (5 min)

### Step 1 — Download your Google credentials
1. Go to: https://console.cloud.google.com/iam-admin/serviceaccounts?project=bunny-clip-tool
2. Click "bunny-clip-runner@..." → Keys → Add Key → JSON
3. Rename the downloaded file to `service_account.json`
4. Put it in this project folder (next to main.py)

### Step 2 — Run setup
**Mac:**
```bash
bash local_setup.sh
```
**Windows:**
```
double-click local_setup.bat
```

### Step 3 — Start
**Mac:**
```bash
bash start.sh
```
**Windows:**
```
double-click start.bat
```

That's it. Two windows open. Bot is live. Send a video to Telegram.

## How to stop
Press `Ctrl+C` in both terminal windows.

## Troubleshooting

**"FFmpeg not found"**
Mac: `brew install ffmpeg`
Windows: `winget install Gyan.FFmpeg` then restart terminal

**"service_account.json not found"**
Download it from Google Cloud Console (Step 1 above)

**Bot doesn't respond**
Make sure both terminal windows are running (processor + bot)

**"Sheets tab not found"**
Run once: `python setup_sheets.py`
