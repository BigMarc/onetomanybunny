"""
Creator Registry
================
Maps Telegram user IDs ↔ Creator names.

Stored in Google Sheets tab "Registry" so staff can manage it without code changes.

Sheet structure (tab name: "Registry"):
| Column A      | Column B        | Column C        | Column D     |
| Telegram ID   | Creator Name    | Output Folder ID | Registered   |
| 123456789     | Sofia           | 1abc...          | 2024-01-15   |
| 987654321     | Lena            | 1def...          | 2024-01-16   |
"""

import os
import logging
from datetime import datetime
from functools import lru_cache
from googleapiclient.discovery import build
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

SHEETS_ID = os.environ.get("SHEETS_ID", "")
PROCESSED_FOLDER_ID = os.environ.get("PROCESSED_FOLDER_ID", "")


def _get_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json"),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)


def get_creator_by_telegram_id(telegram_id: int) -> dict | None:
    """
    Look up a creator's info by their Telegram user ID.
    Returns dict with 'name' and 'output_folder_id', or None if not registered.
    """
    try:
        service = _get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEETS_ID,
            range="Registry!A2:D500"
        ).execute()
        rows = result.get("values", [])
        for row in rows:
            if not row:
                continue
            try:
                row_telegram_id = int(row[0].strip())
            except (ValueError, IndexError):
                continue
            if row_telegram_id == telegram_id:
                return {
                    "telegram_id": telegram_id,
                    "name": row[1].strip() if len(row) > 1 else "Unknown",
                    "output_folder_id": row[2].strip() if len(row) > 2 else PROCESSED_FOLDER_ID,
                }
    except Exception as e:
        logger.error(f"Registry lookup error: {e}")
    return None


def register_creator(telegram_id: int, creator_name: str, output_folder_id: str = "") -> bool:
    """
    Register a new creator in the Registry sheet.
    Called by staff via the /register command.
    """
    try:
        service = _get_sheets_service()
        service.spreadsheets().values().append(
            spreadsheetId=SHEETS_ID,
            range="Registry!A:D",
            valueInputOption="RAW",
            body={
                "values": [[
                    str(telegram_id),
                    creator_name,
                    output_folder_id or PROCESSED_FOLDER_ID,
                    datetime.now().isoformat()
                ]]
            }
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return False


def is_admin(telegram_id: int) -> bool:
    """
    Check if a Telegram ID belongs to an admin (staff member).
    Admin IDs are stored in env var as comma-separated list.
    """
    admin_ids_raw = os.environ.get("ADMIN_TELEGRAM_IDS", "")
    if not admin_ids_raw:
        return False
    try:
        admin_ids = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip()]
        return telegram_id in admin_ids
    except ValueError:
        return False
