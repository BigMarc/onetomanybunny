"""
🐰 Bunny Clip Tool — Telegram Bot
==================================

CREATOR FLOW:
  1. Creator sends a video to the bot
  2. Bot replies: "Got it! Processing ~42 clips. ETA: 15 min ⏳"
  3. Bot downloads video → uploads to GCS → triggers Cloud Run
  4. When done, bot sends:
     - Google Drive folder link (always)
     - ZIP download link (always)

ADMIN COMMANDS (staff only):
  /register <creator_name> — register the next person who messages as a creator
  /creators — list all registered creators
  /status <job_id> — check any job status
  /broadcast <message> — send message to all registered creators

CREATOR COMMANDS:
  /status — check your latest job status
  /help — show instructions

⚠️  BOT TOKEN IS SENSITIVE — store in env var or Secret Manager, never in code.
     Current token is in .env file only, loaded at startup.
"""

import os
import asyncio
import logging
import tempfile
import uuid
import httpx
from pathlib import Path
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

# ── Local modules ─────────────────────────────────────────────────────────────
from telegram_bot.creator_registry import (
    get_creator_by_telegram_id, register_creator, is_admin
)
from telegram_bot.job_tracker import (
    create_job, update_job, get_job, get_pending_jobs,
    STATUS_DONE, STATUS_FAILED, STATUS_PROCESSING, STATUS_QUEUED
)
from telegram_bot.zip_builder import build_and_upload_zip

# ── Config ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN          = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CLOUD_RUN_URL      = os.environ.get("CLOUD_RUN_URL", "")           # Your Cloud Run /process URL
WEBHOOK_URL        = os.environ.get("WEBHOOK_URL", "")             # Bot's own public URL (enables webhook mode)
GCS_BUCKET         = os.environ.get("GCS_BUCKET", "bunny-clip-tool-videos")
PROCESSED_FOLDER_ID = os.environ.get("PROCESSED_FOLDER_ID", "")

# Pending registrations: maps admin Telegram ID → waiting to register next user
_pending_registrations: dict[int, dict] = {}

# In-memory job map: job_id → telegram chat_id (for fast callback, backed by Sheets)
_active_jobs: dict[str, int] = {}


def _get_id_token(target_audience: str) -> str | None:
    """
    Get an OIDC ID token for authenticating to Cloud Run services.
    Works with: raw JSON env var, service account file, or metadata server (ADC).
    """
    import json
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    # Case 1: Raw JSON in env var (Cloud Run --set-secrets)
    if raw.startswith("{"):
        from google.oauth2 import service_account as sa
        from google.auth.transport.requests import Request
        info = json.loads(raw)
        creds = sa.IDTokenCredentials.from_service_account_info(
            info, target_audience=target_audience
        )
        creds.refresh(Request())
        return creds.token

    # Case 2: File path to service account key
    if raw and os.path.isfile(raw):
        from google.oauth2 import service_account as sa
        from google.auth.transport.requests import Request
        creds = sa.IDTokenCredentials.from_service_account_file(
            raw, target_audience=target_audience
        )
        creds.refresh(Request())
        return creds.token

    # Case 3: Metadata server (running on GCE/Cloud Run)
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
        return id_token.fetch_id_token(Request(), target_audience)
    except Exception:
        pass

    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _estimate_clips(file_size_bytes: int) -> int:
    """Rough estimate of clip count based on file size (assumes ~5-min video)."""
    mb = file_size_bytes / (1024 * 1024)
    # Rough: 1 MB ≈ 0.5 seconds of 1080p footage → 5 min ≈ 300s → ~42 clips
    duration_seconds = (mb / 150) * 60 * 5  # very rough
    clips = max(5, int(duration_seconds // 7))
    return min(clips, 80)  # cap display at 80


def _estimate_eta_minutes(file_size_bytes: int) -> int:
    """Estimate processing time in minutes."""
    mb = file_size_bytes / (1024 * 1024)
    # ~3 min per 100 MB on Cloud Run with 2 CPUs
    return max(5, int((mb / 100) * 3) + 3)


async def _upload_to_gcs_and_trigger(
    local_video_path: str,
    job_id: str,
    creator_name: str,
    output_folder_id: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE
):
    """
    Background task:
    1. Upload video to GCS
    2. Call Cloud Run /process
    3. Build ZIP from results
    4. Notify creator via Telegram
    """
    from google.cloud import storage as gcs
    from telegram_bot.gcp_auth import get_credentials

    try:
        # ── Step 1: Upload to GCS ─────────────────────────────────────────
        await context.bot.send_message(
            chat_id=chat_id,
            text="📤 Uploading to processing server..."
        )

        creds = get_credentials(scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
        gcs_client = gcs.Client(credentials=creds, project=creds.project_id)
        bucket = gcs_client.bucket(GCS_BUCKET)
        blob_name = f"uploads/{job_id}/source_video.mp4"
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(local_video_path)
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
        logger.info(f"[{job_id}] Uploaded to GCS: {gcs_uri}")

        update_job(job_id, STATUS_PROCESSING)

        # ── Step 2: Trigger Cloud Run ─────────────────────────────────────
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚙️ Processing started! I'll message you when clips are ready."
        )

        payload = {
            "gcs_uri": gcs_uri,
            "job_id": job_id,
            "creator_name": creator_name,
            "output_folder_id": output_folder_id or PROCESSED_FOLDER_ID,
        }

        # Get ID token for authenticated Cloud Run call
        headers = {"Content-Type": "application/json"}
        try:
            id_token_creds = _get_id_token(CLOUD_RUN_URL)
            if id_token_creds:
                headers["Authorization"] = f"Bearer {id_token_creds}"
        except Exception as e:
            logger.warning(f"[{job_id}] Could not get ID token (proceeding without): {e}")

        async with httpx.AsyncClient(timeout=3600) as client:
            response = await client.post(
                CLOUD_RUN_URL + "/process",
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            raise Exception(f"Cloud Run returned {response.status_code}: {response.text}")

        result = response.json()
        job_folder_id = result.get("job_folder_id", "")
        clip_count    = result.get("clips_processed", 0)
        folder_link   = result.get("folder_link", "")

        # ── Step 3: Build ZIP ─────────────────────────────────────────────
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ {clip_count} clips processed! Building ZIP download... 📦"
        )

        zip_result = build_and_upload_zip(
            job_folder_id=job_folder_id,
            creator_name=creator_name,
            job_id=job_id
        )

        update_job(
            job_id=job_id,
            status=STATUS_DONE,
            clip_count=clip_count,
            folder_link=folder_link
        )

        # ── Step 4: Notify creator ─────────────────────────────────────────
        zip_link    = zip_result.get("zip_drive_link", "")
        zip_size_mb = zip_result.get("zip_size_mb", 0)
        drive_link  = zip_result.get("folder_link", folder_link)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Download ZIP", url=zip_link)],
            [InlineKeyboardButton("📁 Open Drive Folder", url=drive_link)],
        ])

        await context.bot.send_message(
            chat_id=chat_id,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
            text=(
                f"🎉 *Your clips are ready!*\n\n"
                f"🎬 *{clip_count} clips* processed\n"
                f"📦 ZIP size: {zip_size_mb} MB\n"
                f"👤 Creator: {creator_name}\n"
                f"🔖 Job ID: `{job_id}`\n\n"
                f"Choose below to download ZIP or open the Drive folder:"
            )
        )

        logger.info(f"[{job_id}] ✅ All done. Notified {chat_id}")

    except Exception as e:
        logger.error(f"[{job_id}] Background task failed: {e}", exc_info=True)
        update_job(job_id, STATUS_FAILED)
        # Truncate error and strip characters that break Telegram Markdown
        safe_error = str(e)[:200].replace("`", "").replace("*", "").replace("_", "").replace("[", "").replace("]", "")
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"❌ Something went wrong processing your video.\n\n"
                    f"Job ID: `{job_id}`\n"
                    f"Error: {safe_error}\n\n"
                    f"Please contact your manager and share this Job ID."
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            # Fallback: send without any formatting
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"❌ Something went wrong processing your video.\n\n"
                    f"Job ID: {job_id}\n"
                    f"Error: {safe_error}\n\n"
                    f"Please contact your manager and share this Job ID."
                )
            )
    finally:
        # Clean up the temp directory created in handle_video
        import shutil
        tmpdir = os.path.dirname(local_video_path)
        shutil.rmtree(tmpdir, ignore_errors=True)
        logger.info(f"[{job_id}] Cleaned up temp dir {tmpdir}")


# ── Command Handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    creator = get_creator_by_telegram_id(user.id)

    if creator:
        await update.message.reply_text(
            f"Hey {creator['name']}! 🐰\n\n"
            f"Just send me your video and I'll take care of everything.\n"
            f"I'll cut it into clips, add text + music, and send you the download link.\n\n"
            f"📋 /help for instructions\n"
            f"📊 /status to check your latest job"
        )
    else:
        await update.message.reply_text(
            "Hey! 👋\n\n"
            "This is the Bunny Clip Tool.\n"
            "You're not registered yet — contact your manager to get set up."
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use this bot:*\n\n"
        "1️⃣ Film your 5-minute dance video (horizontal!)\n"
        "2️⃣ Send the video directly here in this chat\n"
        "3️⃣ I'll confirm receipt and give you an ETA\n"
        "4️⃣ When done, you get a ZIP download + Drive folder link\n\n"
        "⚠️ *Important:*\n"
        "• Film horizontal (landscape)\n"
        "• No background music playing in the room\n"
        "• One continuous video, don't stop/restart\n"
        "• Max file size: 2 GB\n\n"
        "📊 /status — check your latest job",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if args and is_admin(user.id):
        # Admin checking a specific job ID
        job = get_job(args[0])
        if not job:
            await update.message.reply_text(f"❌ Job `{args[0]}` not found.", parse_mode=ParseMode.MARKDOWN)
            return
    else:
        # Creator checking their own latest job
        # Find the most recent job for this chat_id in the Jobs sheet
        pending = get_pending_jobs()
        my_jobs = [j for j in pending if j.get("telegram_chat_id") == user.id]
        if not my_jobs:
            await update.message.reply_text("No active jobs found. Send me a video to start!")
            return
        job = my_jobs[-1]

    status_emoji = {
        STATUS_QUEUED:     "⏳",
        STATUS_PROCESSING: "⚙️",
        STATUS_DONE:       "✅",
        STATUS_FAILED:     "❌"
    }.get(job["status"], "❓")

    msg = (
        f"{status_emoji} *Job Status*\n\n"
        f"ID: `{job['job_id']}`\n"
        f"Creator: {job['creator_name']}\n"
        f"Status: *{job['status'].upper()}*\n"
    )
    if job.get("clip_count"):
        msg += f"Clips: {job['clip_count']}\n"
    if job.get("started_at"):
        msg += f"Started: {job['started_at'][:16]}\n"
    if job.get("folder_link"):
        msg += f"\n[📁 Open Drive Folder]({job['folder_link']})"

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /register Sofia — then the NEXT person to message becomes Sofia."""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/register <CreatorName>`\n\n"
            "Then ask the creator to send any message to the bot.\n"
            "They will be registered automatically.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    creator_name = " ".join(context.args)
    _pending_registrations[user.id] = {
        "creator_name": creator_name,
        "initiated_by": user.id,
        "at": datetime.now().isoformat()
    }

    await update.message.reply_text(
        f"✅ Ready to register *{creator_name}*.\n\n"
        f"Now ask them to send any message to this bot.\n"
        f"They will be registered automatically.",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_creators(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: list all registered creators."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    from googleapiclient.discovery import build
    from telegram_bot.gcp_auth import get_credentials

    creds = get_credentials(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    svc = build("sheets", "v4", credentials=creds)
    result = svc.spreadsheets().values().get(
        spreadsheetId=os.environ.get("SHEETS_ID", ""),
        range="Registry!A2:D500"
    ).execute()
    rows = result.get("values", [])

    if not rows:
        await update.message.reply_text("No creators registered yet.")
        return

    lines = ["👥 *Registered Creators:*\n"]
    for row in rows:
        if not row:
            continue
        tg_id  = row[0] if len(row) > 0 else "?"
        name   = row[1] if len(row) > 1 else "?"
        reg_at = row[3][:10] if len(row) > 3 else "?"
        lines.append(f"• *{name}* — ID `{tg_id}` — since {reg_at}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_addcreator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /addcreator <telegram_id> <name> — directly add a creator by ID."""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/addcreator <telegram_id> <CreatorName>`\n\n"
            "Example: `/addcreator 755651205 Marc`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ First argument must be a numeric Telegram ID.")
        return

    creator_name = " ".join(context.args[1:])
    success, err = register_creator(telegram_id, creator_name)
    if success:
        await update.message.reply_text(
            f"✅ Registered *{creator_name}* (ID: `{telegram_id}`) directly.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"❌ Failed to register.\n\nError: `{err[:300]}`",
            parse_mode=ParseMode.MARKDOWN
        )


# ── Video Message Handler ─────────────────────────────────────────────────────

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Main handler: triggered when someone sends a video or document (large video file).
    """
    user = update.effective_user
    message = update.message

    # ── Check registration ────────────────────────────────────────────────────
    # If an admin is waiting to register someone, register whoever messages next
    for admin_id, reg_data in list(_pending_registrations.items()):
        creator_name = reg_data["creator_name"]
        logger.info(f"Registering user {user.id} ({user.first_name}) as '{creator_name}' via video (initiated by admin {admin_id})")
        success, err = register_creator(user.id, creator_name)
        if success:
            del _pending_registrations[admin_id]
            # Notify admin (even if admin registered themselves)
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"✅ Registered {user.first_name} as *{creator_name}* (ID: `{user.id}`)",
                parse_mode=ParseMode.MARKDOWN
            )
            await message.reply_text(
                f"You're now registered as *{creator_name}*! 🎉\n\n"
                f"Processing your video now...",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            logger.error(f"register_creator failed for user {user.id} as '{creator_name}': {err}")
            await message.reply_text(
                f"⚠️ Registration failed — could not write to the registry.\n\n"
                f"Error: `{err[:300]}`",
                parse_mode=ParseMode.MARKDOWN
            )
        break

    creator = get_creator_by_telegram_id(user.id)
    if not creator:
        await message.reply_text(
            "You're not registered yet. Contact your manager to get set up. 🐰"
        )
        return

    # ── Get file info ─────────────────────────────────────────────────────────
    video = message.video or message.document
    if not video:
        await message.reply_text("Please send a video file.")
        return

    file_size = video.file_size or 0
    file_size_mb = file_size / (1024 * 1024)

    # Telegram bot limit: 20MB for getFile, 50MB for documents sent directly
    # For large files, we need the Telegram file ID and use a different approach
    if file_size_mb > 2000:
        await message.reply_text(
            "❌ File too large (max 2 GB).\n"
            "Try compressing the video first or use a lower resolution."
        )
        return

    # ── Estimate and acknowledge ──────────────────────────────────────────────
    estimated_clips = _estimate_clips(file_size)
    eta_minutes     = _estimate_eta_minutes(file_size)

    job_id = str(uuid.uuid4())[:8].upper()
    _active_jobs[job_id] = user.id

    create_job(
        job_id=job_id,
        telegram_chat_id=user.id,
        creator_name=creator["name"]
    )

    await message.reply_text(
        f"🐰 *Got it, {creator['name']}!*\n\n"
        f"📹 Video received ({file_size_mb:.0f} MB)\n"
        f"✂️ ~{estimated_clips} clips will be generated\n"
        f"⏱ ETA: ~{eta_minutes} minutes\n"
        f"🔖 Job ID: `{job_id}`\n\n"
        f"I'll send you the download link when everything is ready. "
        f"You can close this app — I'll notify you! 🔔",
        parse_mode=ParseMode.MARKDOWN
    )

    # ── Download video ────────────────────────────────────────────────────────
    try:
        tg_file = await context.bot.get_file(video.file_id)
    except Exception as e:
        await message.reply_text(
            "❌ Could not download your video. This usually means the file is too large for direct Telegram transfer.\n\n"
            "Please try sending it as a compressed file, or contact your manager."
        )
        logger.error(f"get_file failed: {e}")
        return

    # Use a persistent temp dir (not context-managed) so the background task
    # can access the file after this handler returns. The background task
    # cleans up when done.
    tmpdir = tempfile.mkdtemp(prefix=f"bunny_{job_id}_")
    local_path = os.path.join(tmpdir, f"{job_id}_source.mp4")
    try:
        await tg_file.download_to_drive(local_path)
        logger.info(f"[{job_id}] Downloaded to {local_path} ({file_size_mb:.0f} MB)")
    except Exception as e:
        logger.error(f"[{job_id}] Failed to download video from Telegram: {e}")
        await message.reply_text(
            "❌ Failed to download your video. Please try again."
        )
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
        return

    # Kick off background processing
    asyncio.create_task(
        _upload_to_gcs_and_trigger(
            local_video_path=local_path,
            job_id=job_id,
            creator_name=creator["name"],
            output_folder_id=creator.get("output_folder_id", PROCESSED_FOLDER_ID),
            chat_id=user.id,
            context=context
        )
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages — used to complete registration and general replies."""
    user = update.effective_user
    message = update.message

    # Complete pending registration — register the NEXT person who messages
    for admin_id, reg_data in list(_pending_registrations.items()):
        creator_name = reg_data["creator_name"]
        logger.info(f"Registering user {user.id} ({user.first_name}) as '{creator_name}' (initiated by admin {admin_id})")
        success, err = register_creator(user.id, creator_name)
        if success:
            del _pending_registrations[admin_id]
            # Notify the admin (even if admin registered themselves)
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"✅ Registered {user.first_name} as *{creator_name}*",
                parse_mode=ParseMode.MARKDOWN
            )
            await message.reply_text(
                f"You're now registered as *{creator_name}*! 🎉\n\n"
                f"Just send me your video whenever you're ready.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            logger.error(f"register_creator failed for user {user.id} as '{creator_name}': {err}")
            await message.reply_text(
                f"⚠️ Registration failed — could not write to the registry.\n\n"
                f"Error: `{err[:300]}`",
                parse_mode=ParseMode.MARKDOWN
            )
        return

    creator = get_creator_by_telegram_id(user.id)
    if creator:
        await message.reply_text(
            "Just send me your video directly in this chat! 🎬\n"
            "No need to type anything — just attach and send."
        )
    else:
        await message.reply_text(
            "You're not registered yet. Contact your manager. 🐰"
        )


# ── Health Check Server (for Cloud Run) ──────────────────────────────────────

def _start_health_server():
    """Start a minimal HTTP server so Cloud Run's startup probe succeeds."""
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass  # suppress request logs

    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health-check server listening on port {port}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    """Start the bot."""
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not CLOUD_RUN_URL:
        raise RuntimeError("CLOUD_RUN_URL not set")

    logger.info("Starting Bunny Clip Bot...")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("register",  cmd_register))
    app.add_handler(CommandHandler("creators",  cmd_creators))
    app.add_handler(CommandHandler("addcreator", cmd_addcreator))

    # Video and document messages (large files sent as documents)
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    # Text fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    port = int(os.environ.get("PORT", 8080))

    if WEBHOOK_URL:
        # Webhook mode — for Cloud Run deployment.
        # Telegram pushes updates via HTTP POST; no getUpdates polling,
        # so multiple revisions during rolling deploys don't conflict.
        import hashlib
        secret_token = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:32]
        logger.info("Starting in WEBHOOK mode → %s/webhook", WEBHOOK_URL)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="webhook",
            webhook_url=f"{WEBHOOK_URL}/webhook",
            secret_token=secret_token,
            drop_pending_updates=True,
        )
    else:
        # Polling mode — for local development only.
        _start_health_server()
        logger.info("Starting in POLLING mode (local dev)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
