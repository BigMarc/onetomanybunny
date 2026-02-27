"""
Drive ZIP Builder
=================
After clips are processed and uploaded to Drive, this module:
1. Lists all clips in the job's Drive folder
2. Downloads them
3. Creates a ZIP archive
4. Uploads the ZIP back to Drive
5. Returns a shareable link

Used by the Telegram bot to send a single download link.
"""

import os
import logging
import zipfile
import tempfile
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from telegram_bot.gcp_auth import get_credentials

logger = logging.getLogger(__name__)


def _drive():
    try:
        creds = get_credentials(scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to create Drive service: {e}")
        raise


def build_and_upload_zip(job_folder_id: str, creator_name: str, job_id: str) -> dict:
    """
    Download all clips from a Drive folder, zip them, re-upload.

    Returns:
        {
          "zip_drive_link": "https://drive.google.com/...",
          "zip_file_id": "1abc...",
          "clip_count": 42,
          "zip_size_mb": 120.5
        }
    """
    try:
        svc = _drive()
    except Exception as e:
        logger.error(f"[{job_id}] Drive service creation failed: {e}")
        return {"error": f"Drive auth failed: {e}"}

    # List all MP4 files in the job folder
    try:
        results = svc.files().list(
            q=f"'{job_folder_id}' in parents and mimeType='video/mp4' and trashed=false",
            fields="files(id, name)",
            orderBy="name"
        ).execute()
        clip_files = results.get("files", [])
    except Exception as e:
        logger.error(f"[{job_id}] Failed to list clips in folder {job_folder_id}: {e}")
        return {"error": f"Failed to list clips: {e}"}

    if not clip_files:
        logger.warning(f"[{job_id}] No clips found in folder {job_folder_id}")
        return {"error": "No clips found in folder"}

    logger.info(f"[{job_id}] Building ZIP from {len(clip_files)} clips...")

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, f"bunny_clips_{creator_name}_{job_id}.zip")
        skipped = 0

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, file_info in enumerate(clip_files):
                file_id = file_info["id"]
                file_name = file_info["name"]

                try:
                    local_clip = os.path.join(tmpdir, file_name)
                    request = svc.files().get_media(fileId=file_id)
                    with open(local_clip, "wb") as f:
                        downloader = MediaIoBaseDownload(f, request)
                        done = False
                        while not done:
                            _, done = downloader.next_chunk()

                    zf.write(local_clip, file_name)
                    logger.info(f"[{job_id}] Zipped {i+1}/{len(clip_files)}: {file_name}")
                except Exception as e:
                    skipped += 1
                    logger.error(f"[{job_id}] Failed to download clip {file_name}: {e}")

        if skipped == len(clip_files):
            logger.error(f"[{job_id}] All clip downloads failed")
            return {"error": "All clip downloads failed during ZIP build"}

        zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        logger.info(f"[{job_id}] ZIP size: {zip_size_mb:.1f} MB ({skipped} skipped)")

        # Upload ZIP to same folder in Drive
        try:
            zip_filename = f"ALL_CLIPS_{creator_name}_{job_id}.zip"
            file_metadata = {
                "name": zip_filename,
                "parents": [job_folder_id]
            }
            media = MediaFileUpload(zip_path, mimetype="application/zip", resumable=True)
            uploaded = svc.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, webViewLink, webContentLink"
            ).execute()
        except Exception as e:
            logger.error(f"[{job_id}] Failed to upload ZIP to Drive: {e}")
            return {"error": f"ZIP upload failed: {e}"}

        # Make ZIP publicly accessible (anyone with link can download)
        try:
            svc.permissions().create(
                fileId=uploaded["id"],
                body={"type": "anyone", "role": "reader"}
            ).execute()
        except Exception as e:
            logger.warning(f"[{job_id}] Failed to set ZIP permissions: {e}")

        # Also make the folder shareable
        try:
            svc.permissions().create(
                fileId=job_folder_id,
                body={"type": "anyone", "role": "reader"}
            ).execute()
        except Exception as e:
            logger.warning(f"[{job_id}] Failed to set folder permissions: {e}")

        try:
            folder_info = svc.files().get(
                fileId=job_folder_id,
                fields="webViewLink"
            ).execute()
            folder_link = folder_info.get("webViewLink", "")
        except Exception as e:
            logger.warning(f"[{job_id}] Failed to get folder link: {e}")
            folder_link = ""

        return {
            "zip_drive_link": uploaded.get("webContentLink") or uploaded.get("webViewLink"),
            "folder_link": folder_link,
            "zip_file_id": uploaded["id"],
            "clip_count": len(clip_files) - skipped,
            "zip_size_mb": round(zip_size_mb, 1)
        }
