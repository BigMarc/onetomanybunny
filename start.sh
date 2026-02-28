#!/bin/bash
# Starts both services in separate Terminal tabs

# Activate venv
source venv/bin/activate

echo "🐰 Starting Bunny Clip Tool..."
echo "   Processor → http://localhost:8080"
echo "   Bot       → polling Telegram"
echo ""
echo "Press Ctrl+C in each window to stop."
echo ""

# Start processor in background
osascript -e 'tell application "Terminal" to do script "cd '"$(pwd)"' && source venv/bin/activate && python main.py"'

# Start bot in this window
sleep 1
python run_bot.py
