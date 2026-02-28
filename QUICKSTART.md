# Bunny Clip Tool — Local Quickstart

## One-time setup

### Step 1 — Run setup
**Mac:**
```bash
bash local_setup.sh
```
**Windows:**
```
double-click local_setup.bat
```

### Step 2 — Add sounds (optional)
Put your MP3 files into the `static/sounds/` folder.
If you don't add any, clips will have no background music.

## Start the tool

**Mac:**
```bash
bash start.sh
```
**Windows:**
```
double-click start.bat
```

Your browser opens automatically at http://localhost:5050

1. Type a creator name
2. Upload a video
3. Wait for processing
4. Click "Download All Clips"

## Stop
Press `Ctrl+C` in the terminal window.

## Troubleshooting

**"FFmpeg not found"**
Mac: `brew install ffmpeg`
Windows: `winget install Gyan.FFmpeg` then restart terminal

**Processing is slow**
Normal — each 7-second clip takes a few seconds to render.
A 5-minute video = ~42 clips = ~5-10 minutes.
