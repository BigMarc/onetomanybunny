@echo off
echo 🐰 Setting up Bunny Clip Tool locally...

:: Check Python
python --version 2>NUL || (
  echo ❌ Python 3.11+ required.
  echo Download: https://www.python.org/downloads/
  pause & exit /b 1
)

:: Check FFmpeg
ffmpeg -version >NUL 2>&1 || (
  echo 📦 FFmpeg not found.
  echo Install via: winget install Gyan.FFmpeg
  echo Or download: https://ffmpeg.org/download.html
  echo After installing, restart this script.
  pause & exit /b 1
)

:: Create venv
python -m venv venv
call venv\Scripts\activate.bat

:: Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

:: Create local temp folders
if not exist tmp\uploads mkdir tmp\uploads
if not exist tmp\clips mkdir tmp\clips
if not exist tmp\zips mkdir tmp\zips

:: Copy env if not exists
if not exist .env copy .env.example .env

echo.
echo ✅ Setup complete!
echo.
echo Next: fill in your .env file, then run:
echo   start.bat
pause
