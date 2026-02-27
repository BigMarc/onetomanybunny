"""
Bunny Clip Tool — Google Sheets Handler
========================================
Manages rotating title selection from the "Titles" tab in Google Sheets.

Sheet structure (tab: "Titles"):
| A: Title Text | B: Category | C: Active (TRUE/FALSE) | D: Last Used |
"""

import os
import logging
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


def _get_sheets_service():
    """Build and return an authenticated Google Sheets service."""
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
    try:
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to create Sheets service: {e}")
        raise


def get_rotating_titles(sheet_id: str, n_clips: int) -> list[str]:
    """
    Get rotating titles from the Titles tab in Google Sheets.

    Rotation logic:
    - Read all rows from the "Titles" tab
    - Filter to Active == "TRUE" only
    - Sort by Last Used ascending (empty/never used = highest priority)
    - Cycle through titles if n_clips > available titles
    - Write current timestamp back to Last Used column for each used title

    Args:
        sheet_id: The Google Sheets spreadsheet ID.
        n_clips: Number of titles needed (one per clip).

    Returns:
        List of title strings, length = n_clips.
    """
    if not sheet_id:
        logger.warning("No sheet_id provided — returning empty titles")
        return []

    try:
        service = _get_sheets_service()

        # Read all titles (columns A-D, starting from row 2 to skip header)
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range="Titles!A2:D500",
        ).execute()
        rows = result.get("values", [])

        if not rows:
            logger.warning("No titles found in Sheets")
            return []

        # Parse rows into structured data with original row numbers
        titles_data = []
        for i, row in enumerate(rows):
            if not row or len(row) < 1:
                continue

            title_text = row[0].strip() if len(row) > 0 else ""
            active = row[2].strip().upper() if len(row) > 2 else "TRUE"
            last_used = row[3].strip() if len(row) > 3 else ""

            if not title_text:
                continue
            if active != "TRUE":
                continue

            titles_data.append({
                "text": title_text,
                "last_used": last_used,
                "row_number": i + 2,  # +2 because row 1 is header, index is 0-based
            })

        if not titles_data:
            logger.warning("No active titles found in Sheets")
            return []

        # Sort by Last Used ascending — empty (never used) comes first
        def sort_key(item: dict) -> str:
            return item["last_used"] if item["last_used"] else ""

        titles_data.sort(key=sort_key)

        # Select titles for n_clips, cycling if needed
        selected = []
        for i in range(n_clips):
            selected.append(titles_data[i % len(titles_data)])

        # Update Last Used timestamps for all used titles
        now = datetime.now().isoformat()
        used_rows = set()
        batch_data = []
        for item in selected:
            if item["row_number"] not in used_rows:
                used_rows.add(item["row_number"])
                batch_data.append({
                    "range": f"Titles!D{item['row_number']}",
                    "values": [[now]],
                })

        if batch_data:
            try:
                service.spreadsheets().values().batchUpdate(
                    spreadsheetId=sheet_id,
                    body={
                        "valueInputOption": "RAW",
                        "data": batch_data,
                    },
                ).execute()
                logger.info(f"Updated Last Used for {len(batch_data)} titles")
            except Exception as e:
                logger.warning(f"Failed to update Last Used timestamps: {e}")

        result_titles = [item["text"] for item in selected]
        logger.info(f"Selected {len(result_titles)} titles ({len(titles_data)} active available)")
        return result_titles

    except Exception as e:
        logger.error(f"Failed to get rotating titles: {e}")
        raise
