"""
Shared Google credentials helper.

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


def get_credentials(scopes: list[str]):
    """
    Build Google credentials.
    Supports: raw JSON env var, file path, or Application Default Credentials (ADC).
    """
    global _cached_info
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

    stripped = raw.strip()
    if stripped.startswith("{"):
        # Raw JSON content (Cloud Run --set-secrets)
        if _cached_info is None:
            _cached_info = json.loads(stripped)
            logger.info("Parsed credentials from JSON env var (project: %s)", _cached_info.get("project_id", "?"))
        return service_account.Credentials.from_service_account_info(
            _cached_info, scopes=scopes
        )
    elif stripped and os.path.isfile(stripped):
        # File path to service account key
        return service_account.Credentials.from_service_account_file(
            stripped, scopes=scopes
        )
    else:
        # Fallback: Application Default Credentials (Cloud Shell, GCE, etc.)
        # Temporarily unset GOOGLE_APPLICATION_CREDENTIALS so ADC doesn't
        # pick up the same bad key file.
        import google.auth
        saved = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        try:
            creds, _project = google.auth.default(scopes=scopes)
        finally:
            if saved is not None:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = saved
        logger.info("Using Application Default Credentials (project: %s)", _project)
        return creds
