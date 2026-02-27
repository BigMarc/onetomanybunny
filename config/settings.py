"""
Bunny Clip Tool — Centralized Settings
=======================================
All configuration pulled from environment variables.
"""

import os

GCS_BUCKET = os.environ.get("GCS_BUCKET", "bunny-clip-tool-videos")
SHEETS_ID = os.environ.get("SHEETS_ID", "")
SOUNDS_FOLDER_ID = os.environ.get("SOUNDS_FOLDER_ID", "")
PROCESSED_FOLDER_ID = os.environ.get("PROCESSED_FOLDER_ID", "")
NOTIFICATION_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "")
CLIP_DURATION = int(os.environ.get("CLIP_DURATION", "7"))
TEXT_FONT_SIZE = int(os.environ.get("TEXT_FONT_SIZE", "52"))
TEXT_POSITION = os.environ.get("TEXT_POSITION", "bottom")
