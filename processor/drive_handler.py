"""
Bunny Clip Tool — Google Drive Handler
=======================================
Handles all Drive operations: download, upload, folder management, sound selection.
"""

import io
import os
import random
import logging
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build, Resource
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service() -> Resource:
    """Build and return an authenticated Google Drive service."""
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
    try:
        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to create Drive service: {e}")
        raise


def download_file(file_id: str, destination_path: str) -> str:
    """
    Download a file from Google Drive to a local path.

    Args:
        file_id: The Drive file ID to download.
        destination_path: Local file path to save to.

    Returns:
        The destination_path on success.
    """
    try:
        service = get_drive_service()
        request = service.files().get_media(fileId=file_id)
        with open(destination_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.info(f"Download progress: {int(status.progress() * 100)}%")
        logger.info(f"Downloaded {file_id} -> {destination_path}")
        return destination_path
    except Exception as e:
        logger.error(f"Failed to download file {file_id}: {e}")
        raise


def get_random_sound(sounds_folder_id: str) -> Optional[tuple[str, str]]:
    """
    Pick a random MP3/audio file from the sounds folder in Drive.

    Args:
        sounds_folder_id: Drive folder ID containing sound files.

    Returns:
        Tuple of (file_id, file_name) or None if no sounds found.
    """
    if not sounds_folder_id:
        logger.warning("No sounds_folder_id provided — skipping sound selection")
        return None

    try:
        service = get_drive_service()
        results = service.files().list(
            q=(
                f"'{sounds_folder_id}' in parents "
                f"and (mimeType='audio/mpeg' or mimeType='audio/mp3' or mimeType='audio/wav') "
                f"and trashed=false"
            ),
            fields="files(id, name)",
            pageSize=100,
        ).execute()
        files = results.get("files", [])

        if not files:
            logger.warning(f"No sound files found in folder {sounds_folder_id}")
            return None

        chosen = random.choice(files)
        logger.info(f"Selected sound: {chosen['name']} ({chosen['id']})")
        return (chosen["id"], chosen["name"])
    except Exception as e:
        logger.error(f"Failed to list sounds from {sounds_folder_id}: {e}")
        return None


def upload_clip(local_path: str, folder_id: str, filename: str) -> str:
    """
    Upload a clip to a Drive folder.

    Args:
        local_path: Local file path of the clip.
        folder_id: Destination Drive folder ID.
        filename: Name for the file in Drive.

    Returns:
        The webViewLink of the uploaded file.
    """
    try:
        service = get_drive_service()
        file_metadata = {
            "name": filename,
            "parents": [folder_id],
        }
        media = MediaFileUpload(local_path, mimetype="video/mp4", resumable=True)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
        ).execute()
        link = uploaded.get("webViewLink", "")
        logger.info(f"Uploaded {filename} -> {link}")
        return link
    except Exception as e:
        logger.error(f"Failed to upload {filename} to folder {folder_id}: {e}")
        raise


def get_or_create_creator_folder(creator_name: str, parent_folder_id: str) -> str:
    """
    Find or create a folder for a specific creator under the parent folder.

    Args:
        creator_name: The creator's name (used as folder name).
        parent_folder_id: The parent Drive folder ID.

    Returns:
        The folder ID for the creator's folder.
    """
    try:
        service = get_drive_service()

        # Check if folder already exists
        query = (
            f"name='{creator_name}' "
            f"and '{parent_folder_id}' in parents "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and trashed=false"
        )
        results = service.files().list(
            q=query,
            fields="files(id, name)",
            pageSize=1,
        ).execute()
        existing = results.get("files", [])

        if existing:
            folder_id = existing[0]["id"]
            logger.info(f"Found existing folder for {creator_name}: {folder_id}")
            return folder_id

        # Create new folder
        folder_metadata = {
            "name": creator_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_folder_id],
        }
        folder = service.files().create(
            body=folder_metadata,
            fields="id",
        ).execute()
        folder_id = folder["id"]
        logger.info(f"Created new folder for {creator_name}: {folder_id}")
        return folder_id
    except Exception as e:
        logger.error(f"Failed to get/create folder for {creator_name}: {e}")
        raise
