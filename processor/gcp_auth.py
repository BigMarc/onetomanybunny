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

_cached_info: dict | None = None


def get_credentials(scopes: list[str]) -> service_account.Credentials:
    """
    Build Google service account credentials.
    Supports both file path and raw JSON string in GOOGLE_APPLICATION_CREDENTIALS.
    """
    global _cached_info
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")

    stripped = raw.strip()
    if stripped.startswith("{"):
        # It's raw JSON content — parse and use from_service_account_info
        if _cached_info is None:
            _cached_info = json.loads(stripped)
            logger.info("Parsed credentials from JSON env var (project: %s)", _cached_info.get("project_id", "?"))
        return service_account.Credentials.from_service_account_info(
            _cached_info, scopes=scopes
        )
    else:
        # It's a file path — use directly
        return service_account.Credentials.from_service_account_file(
            stripped, scopes=scopes
        )
