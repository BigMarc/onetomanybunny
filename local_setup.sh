#!/bin/bash
# Bunny Clip Tool — Local Setup for Mac
# Run once: bash local_setup.sh

set -e
echo "Setting up Bunny Clip Tool..."

# Check Python
python3 --version || { echo "Python 3.11+ required. Install: brew install python@3.11"; exit 1; }

# Check FFmpeg
ffmpeg -version > /dev/null 2>&1 || {
  echo "Installing FFmpeg..."
  brew install ffmpeg || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
}

# Create venv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create local temp folders
mkdir -p tmp/uploads tmp/clips tmp/zips
mkdir -p static/sounds

echo ""
echo "Setup complete!"
echo ""
echo "Optional: put MP3 files into static/sounds/ for background music."
echo ""
echo "To start: bash start.sh"
