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

from telegram_bot.gcp_auth import get_credentials

logger = logging.getLogger(__name__)

SHEETS_ID = os.environ.get("SHEETS_ID", "")
PROCESSED_FOLDER_ID = os.environ.get("PROCESSED_FOLDER_ID", "")


def _get_sheets_service():
    creds = get_credentials(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return build("sheets", "v4", credentials=creds)


def get_creator_by_telegram_id(telegram_id: int) -> dict | None:
    """
    Look up a creator's info by their Telegram user ID.
    Returns dict with 'name' and 'output_folder_id', or None if not registered.
    """
    try:
        if not SHEETS_ID:
            logger.error("SHEETS_ID env var is empty — cannot look up creators")
            return None
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
        logger.error(f"Registry lookup error: {type(e).__name__}: {e}", exc_info=True)
    return None


def register_creator(telegram_id: int, creator_name: str, output_folder_id: str = "") -> tuple[bool, str]:
    """
    Register a new creator in the Registry sheet.
    Returns (success, error_detail) so the caller can show a useful message.
    """
    if not SHEETS_ID:
        msg = "SHEETS_ID env var is empty — cannot write to registry"
        logger.error(msg)
        return False, msg
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
        logger.info(f"Registered creator '{creator_name}' (telegram_id={telegram_id}) in sheet {SHEETS_ID}")
        return True, ""
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        logger.error(f"Registration error: {msg}", exc_info=True)
        return False, msg


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
