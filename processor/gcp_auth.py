"""
Shared Google credentials helper for the processor.

Handles both:
- File path to service_account.json (local development)
- Raw JSON content in env var (Cloud Run / Secret Manager injection)
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
    Supports: raw JSON env var or file path.
    """
    global _cached_info
    val = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")

    stripped = val.strip()
    if stripped.startswith("{"):
        # Raw JSON content (Cloud Run --set-secrets)
        if _cached_info is None:
            _cached_info = json.loads(stripped)
            logger.info("Parsed credentials from JSON env var (project: %s)", _cached_info.get("project_id", "?"))
        return service_account.Credentials.from_service_account_info(
            _cached_info, scopes=scopes
        )
    else:
        # File path to service account key (local development)
        if not os.path.exists(stripped):
            raise RuntimeError(
                f"service_account.json not found at '{stripped}'.\n"
                f"Download it from: Google Cloud Console → IAM → Service Accounts → Keys"
            )
        return service_account.Credentials.from_service_account_file(
            stripped, scopes=scopes
        )
