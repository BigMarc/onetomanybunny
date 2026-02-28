"""
Bunny Clip Tool — Centralized Settings
=======================================
All configuration pulled from environment variables.
"""

import os

SHEETS_ID = os.environ.get("SHEETS_ID", "")
SOUNDS_FOLDER_ID = os.environ.get("SOUNDS_FOLDER_ID", "")
PROCESSED_FOLDER_ID = os.environ.get("PROCESSED_FOLDER_ID", "")
NOTIFICATION_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "")
LOCAL_UPLOAD_DIR = os.environ.get("LOCAL_UPLOAD_DIR", "./tmp/uploads")
LOCAL_CLIPS_DIR = os.environ.get("LOCAL_CLIPS_DIR", "./tmp/clips")
LOCAL_ZIPS_DIR = os.environ.get("LOCAL_ZIPS_DIR", "./tmp/zips")
