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
