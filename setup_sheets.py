"""
Google Sheets Setup Script
===========================
Run this ONCE to create all required tabs and headers in your Google Sheet.

Usage:
  pip install google-auth google-api-python-client python-dotenv
  python setup_sheets.py

Requires:
  - GOOGLE_APPLICATION_CREDENTIALS env var (file path or raw JSON)
  - SHEETS_ID env var with your Google Sheet ID
  - Service account must have Editor access on the Google Sheet
"""

import json
import os
from googleapiclient.discovery import build
from google.oauth2 import service_account

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # running without dotenv — env vars must already be set

SHEETS_ID = os.environ.get("SHEETS_ID", "")
if not SHEETS_ID:
    raise RuntimeError("SHEETS_ID env var is not set. Set it in .env or export it.")


def get_service():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    stripped = raw.strip()

    if stripped.startswith("{"):
        # Raw JSON content (Cloud Run --set-secrets)
        info = json.loads(stripped)
        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    elif stripped and os.path.isfile(stripped):
        # File path to service account key
        creds = service_account.Credentials.from_service_account_file(stripped, scopes=scopes)
    else:
        # Fallback: Application Default Credentials (works in Cloud Shell, GCE, etc.)
        import google.auth
        creds, _project = google.auth.default(scopes=scopes)
        print("  Using Application Default Credentials (ADC)")
    return build("sheets", "v4", credentials=creds)


def create_tab_if_missing(service, sheet_id: str, tab_name: str):
    """Add a new tab to the sheet if it doesn't already exist."""
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    existing = [s["properties"]["title"] for s in meta["sheets"]]
    if tab_name in existing:
        print(f"  Tab '{tab_name}' already exists — skipping")
        return
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
    ).execute()
    print(f"  ✅ Created tab '{tab_name}'")


def write_headers(service, sheet_id: str, tab_name: str, headers: list[str]):
    """Write header row to a tab."""
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A1",
        valueInputOption="RAW",
        body={"values": [headers]}
    ).execute()
    print(f"  ✅ Headers written to '{tab_name}'")


def write_sample_data(service, sheet_id: str):
    """Write sample titles to the Titles tab."""
    sample_titles = [
        ["She moves different 🔥",           "hype",       "TRUE", ""],
        ["POV: You can't look away",          "pov",        "TRUE", ""],
        ["This energy >>> 😮‍💨",              "vibe",       "TRUE", ""],
        ["Main character energy 👑",           "confidence", "TRUE", ""],
        ["Not the way she just did that 😭",  "reaction",   "TRUE", ""],
        ["Link in bio 👇🔥",                  "cta",        "TRUE", ""],
        ["She eats every time, no crumbs",    "confidence", "TRUE", ""],
        ["Follow for more 🐰",                "cta",        "TRUE", ""],
        ["The vibe is immaculate ✨",          "vibe",       "TRUE", ""],
        ["Don't scroll past this",            "cta",        "TRUE", ""],
        ["She's built different 💅",          "confidence", "TRUE", ""],
        ["Obsessed and I won't apologize",    "reaction",   "TRUE", ""],
        ["This is the content we needed",     "vibe",       "TRUE", ""],
        ["No one does it like her",           "confidence", "TRUE", ""],
        ["She came to show out today 💥",     "hype",       "TRUE", ""],
        ["POV: You found her ❤️",             "pov",        "TRUE", ""],
        ["Daily reminder that she exists 🙏", "vibe",       "TRUE", ""],
        ["She said what she said 💁",         "confidence", "TRUE", ""],
        ["Energy check: ✅✅✅",              "hype",       "TRUE", ""],
        ["Drop a ❤️ if you agree",            "cta",        "TRUE", ""],
        ["The girls that get it, get it",     "vibe",       "TRUE", ""],
        ["She's that girl and she knows it",  "confidence", "TRUE", ""],
        ["Living rent free in my head",       "reaction",   "TRUE", ""],
        ["Not a single flaw detected 🤌",     "reaction",   "TRUE", ""],
        ["Waking up like this hits diff 🌙",  "vibe",       "TRUE", ""],
        ["She's aware of what she's doing 👀","confidence", "TRUE", ""],
        ["This one goes hard 🔥",             "hype",       "TRUE", ""],
        ["You need to see the full video 👀", "cta",        "TRUE", ""],
        ["POV: She chose violence today 💀",  "pov",        "TRUE", ""],
        ["The confidence is contagious",      "confidence", "TRUE", ""],
    ]
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="Titles!A2",
        valueInputOption="RAW",
        body={"values": sample_titles}
    ).execute()
    print(f"  ✅ {len(sample_titles)} sample titles added to 'Titles'")


def main():
    print(f"\n🐰 Setting up Google Sheet: {SHEETS_ID}\n")
    service = get_service()

    # ── Create tabs ───────────────────────────────────────────
    print("Creating tabs...")
    for tab in ["Titles", "Registry", "Jobs"]:
        create_tab_if_missing(service, SHEETS_ID, tab)

    # ── Write headers ─────────────────────────────────────────
    print("\nWriting headers...")
    write_headers(service, SHEETS_ID, "Titles", [
        "Title Text", "Category", "Active (TRUE/FALSE)", "Last Used"
    ])
    write_headers(service, SHEETS_ID, "Registry", [
        "Telegram ID", "Creator Name", "Output Folder ID", "Registered At"
    ])
    write_headers(service, SHEETS_ID, "Jobs", [
        "Job ID", "Telegram Chat ID", "Creator Name", "Status",
        "Clip Count", "Folder Link", "Started At", "Finished At"
    ])

    # ── Add sample titles ─────────────────────────────────────
    print("\nAdding sample titles...")
    write_sample_data(service, SHEETS_ID)

    print("\n✅ Sheet setup complete!")
    print(f"\nOpen your sheet: https://docs.google.com/spreadsheets/d/{SHEETS_ID}/edit")
    print("\nNext steps:")
    print("  1. In the 'Registry' tab: add your first creator manually or use /register in the bot")
    print("  2. In the 'Titles' tab: edit/add titles as needed (Active = TRUE to use)")
    print("  3. Add MP3 files to your Sounds Library folder in Drive")


if __name__ == "__main__":
    main()
