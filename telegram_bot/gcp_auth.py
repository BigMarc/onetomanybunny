"""
Shared Google credentials helper.

Handles the case where GOOGLE_APPLICATION_CREDENTIALS contains
either a file path OR the raw JSON content of the service account key
(as happens with Cloud Run --set-secrets as env var).
"""

import json
import os
import logging
import tempfile

from google.oauth2 import service_account

logger = logging.getLogger(__name__)

_temp_creds_path: str | None = None


def get_credentials(scopes: list[str]) -> service_account.Credentials:
    """
    Build Google service account credentials.
    Supports both file path and raw JSON string in GOOGLE_APPLICATION_CREDENTIALS.
    """
    global _temp_creds_path
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")

    # Check if the value looks like JSON content (starts with '{')
    stripped = raw.strip()
    if stripped.startswith("{"):
        # It's raw JSON — write to a temp file and load from there
        if _temp_creds_path is None or not os.path.exists(_temp_creds_path):
            fd, _temp_creds_path = tempfile.mkstemp(suffix=".json", prefix="gcp_creds_")
            with os.fdopen(fd, "w") as f:
                f.write(stripped)
            logger.info("Wrote credentials JSON to temp file")
        return service_account.Credentials.from_service_account_file(
            _temp_creds_path, scopes=scopes
        )
    else:
        # It's a file path — use directly
        return service_account.Credentials.from_service_account_file(
            raw, scopes=scopes
        )
