#!/bin/bash
# Bunny Clip Tool — Start (Mac)

source venv/bin/activate

echo ""
echo "  Bunny Clip Tool starting..."
echo "  Open http://localhost:5050 in your browser."
echo "  Press Ctrl+C to stop."
echo ""

# Open browser automatically
open http://localhost:5050 2>/dev/null &

python app.py
