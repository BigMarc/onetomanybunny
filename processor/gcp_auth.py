"""
Shared Google credentials helper for the processor container.

Handles the case where GOOGLE_APPLICATION_CREDENTIALS contains
either a file path OR the raw JSON content of the service account key
(as happens with Cloud Run --set-secrets as env var).
"""

import json
import os
import logging

from google.oauth2 import service_account

logger = logging.getLogger(__name__)


def get_credentials(scopes: list[str]) -> service_account.Credentials:
    """
    Build Google service account credentials.

    - If GOOGLE_APPLICATION_CREDENTIALS starts with '{' -> raw JSON, use from_service_account_info()
    - If it looks like a file path -> use from_service_account_file()
    - If the env var is missing -> raise RuntimeError
    """
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

    if not raw:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS is not set. "
            "Set it to a file path or the raw JSON content of a service account key."
        )

    stripped = raw.strip()

    if stripped.startswith("{"):
        # Raw JSON content — parse and load directly (no temp file needed)
        logger.info("Loading credentials from raw JSON (Cloud Run secret)")
        info = json.loads(stripped)
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    else:
        # File path — load from file
        logger.info("Loading credentials from file: %s", stripped)
        return service_account.Credentials.from_service_account_file(stripped, scopes=scopes)
