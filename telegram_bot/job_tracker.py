"""
Job Tracker
===========
Persists job state in Google Sheets tab "Jobs" so the bot can:
- Know which Telegram chat to notify when a job finishes
- Show status when creator asks
- Handle bot restarts without losing job state

Sheet structure (tab name: "Jobs"):
| A: job_id | B: telegram_chat_id | C: creator_name | D: status | E: clip_count | F: folder_link | G: started_at | H: finished_at |
"""

import os
import logging
from datetime import datetime
from googleapiclient.discovery import build
from google.oauth2 import service_account

logger = logging.getLogger(__name__)
SHEETS_ID = os.environ.get("SHEETS_ID", "")

STATUS_QUEUED      = "queued"
STATUS_PROCESSING  = "processing"
STATUS_DONE        = "done"
STATUS_FAILED      = "failed"


def _svc():
    creds = service_account.Credentials.from_service_account_file(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json"),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)


def create_job(job_id: str, telegram_chat_id: int, creator_name: str) -> bool:
    """Write a new job row to the Jobs sheet."""
    try:
        _svc().spreadsheets().values().append(
            spreadsheetId=SHEETS_ID,
            range="Jobs!A:H",
            valueInputOption="RAW",
            body={"values": [[
                job_id,
                str(telegram_chat_id),
                creator_name,
                STATUS_QUEUED,
                "",   # clip_count
                "",   # folder_link
                datetime.now().isoformat(),
                ""    # finished_at
            ]]}
        ).execute()
        return True
    except Exception as e:
        logger.error(f"create_job error: {e}")
        return False


def update_job(job_id: str, status: str, clip_count: int = 0, folder_link: str = "") -> bool:
    """Find job row by job_id and update its status/result columns."""
    try:
        svc = _svc()
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_ID,
            range="Jobs!A:H"
        ).execute()
        rows = result.get("values", [])

        row_number = None
        for i, row in enumerate(rows):
            if row and row[0] == job_id:
                row_number = i + 1  # Sheets is 1-indexed
                break

        if not row_number:
            logger.warning(f"Job {job_id} not found in sheet")
            return False

        finished = datetime.now().isoformat() if status in (STATUS_DONE, STATUS_FAILED) else ""

        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=SHEETS_ID,
            body={
                "valueInputOption": "RAW",
                "data": [
                    {"range": f"Jobs!D{row_number}", "values": [[status]]},
                    {"range": f"Jobs!E{row_number}", "values": [[str(clip_count)]]},
                    {"range": f"Jobs!F{row_number}", "values": [[folder_link]]},
                    {"range": f"Jobs!H{row_number}", "values": [[finished]]},
                ]
            }
        ).execute()
        return True
    except Exception as e:
        logger.error(f"update_job error: {e}")
        return False


def get_job(job_id: str) -> dict | None:
    """Fetch a single job's data by job_id."""
    try:
        result = _svc().spreadsheets().values().get(
            spreadsheetId=SHEETS_ID,
            range="Jobs!A:H"
        ).execute()
        rows = result.get("values", [])
        for row in rows:
            if row and row[0] == job_id:
                return {
                    "job_id":          row[0] if len(row) > 0 else "",
                    "telegram_chat_id": int(row[1]) if len(row) > 1 and row[1] else 0,
                    "creator_name":    row[2] if len(row) > 2 else "",
                    "status":          row[3] if len(row) > 3 else "",
                    "clip_count":      int(row[4]) if len(row) > 4 and row[4] else 0,
                    "folder_link":     row[5] if len(row) > 5 else "",
                    "started_at":      row[6] if len(row) > 6 else "",
                    "finished_at":     row[7] if len(row) > 7 else "",
                }
    except Exception as e:
        logger.error(f"get_job error: {e}")
    return None


def get_pending_jobs() -> list[dict]:
    """Return all jobs that are queued or processing (for polling on bot restart)."""
    try:
        result = _svc().spreadsheets().values().get(
            spreadsheetId=SHEETS_ID,
            range="Jobs!A:H"
        ).execute()
        rows = result.get("values", [])
        pending = []
        for row in rows:
            if not row or len(row) < 4:
                continue
            if row[3] in (STATUS_QUEUED, STATUS_PROCESSING):
                pending.append({
                    "job_id":           row[0],
                    "telegram_chat_id": int(row[1]) if row[1] else 0,
                    "creator_name":     row[2] if len(row) > 2 else "",
                    "status":           row[3],
                    "clip_count":       int(row[4]) if len(row) > 4 and row[4] else 0,
                    "folder_link":      row[5] if len(row) > 5 else "",
                })
        return pending
    except Exception as e:
        logger.error(f"get_pending_jobs error: {e}")
        return []
