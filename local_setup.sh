#!/bin/bash
# Bunny Clip Tool — Local Setup for Mac
# Run once: bash local_setup.sh

set -e
echo "🐰 Setting up Bunny Clip Tool locally..."

# Check Python
python3 --version || { echo "❌ Python 3.11+ required. Install: brew install python@3.11"; exit 1; }

# Check FFmpeg
ffmpeg -version > /dev/null 2>&1 || {
  echo "📦 Installing FFmpeg..."
  brew install ffmpeg || { echo "❌ Install Homebrew first: https://brew.sh"; exit 1; }
}

# Create venv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create local temp folders
mkdir -p tmp/uploads tmp/clips tmp/zips

# Copy env if not exists
[ -f .env ] || cp .env.example .env

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next: fill in your .env file, then run:"
echo "  bash start.sh"
