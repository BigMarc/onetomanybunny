"""
🐰 Bunny Clip Tool — Telegram Bot (Local Mode)
================================================

CREATOR FLOW:
  1. Creator sends a video to the bot
  2. Bot replies: "Got it! Processing ~42 clips. ETA: 15 min ⏳"
  3. Bot downloads video → saves locally → calls local processor
  4. When done, bot sends:
     - ZIP file directly in Telegram
     - Google Drive folder link

ADMIN COMMANDS (staff only):
  /register <creator_name> — register the next person who messages as a creator
  /creators — list all registered creators
  /status <job_id> — check any job status
  /broadcast <message> — send message to all registered creators

CREATOR COMMANDS:
  /status — check your latest job status
  /help — show instructions
"""

import os
import asyncio
import logging
import uuid
import httpx
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
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

# ── Config ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN           = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CLOUD_RUN_URL       = os.environ.get("CLOUD_RUN_URL", "http://localhost:8080")
PROCESSED_FOLDER_ID = os.environ.get("PROCESSED_FOLDER_ID", "")
LOCAL_UPLOAD_DIR     = os.environ.get("LOCAL_UPLOAD_DIR", "./tmp/uploads")
LOCAL_ZIPS_DIR       = os.environ.get("LOCAL_ZIPS_DIR", "./tmp/zips")

os.makedirs(LOCAL_UPLOAD_DIR, exist_ok=True)
os.makedirs(LOCAL_ZIPS_DIR, exist_ok=True)

# Pending registrations: maps admin Telegram ID → waiting to register next user
_pending_registrations: dict[int, dict] = {}

# In-memory job map: job_id → telegram chat_id (for fast callback, backed by Sheets)
_active_jobs: dict[str, int] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _estimate_clips(file_size_bytes: int) -> int:
    """Rough estimate of clip count based on file size (assumes ~5-min video)."""
    mb = file_size_bytes / (1024 * 1024)
    duration_seconds = (mb / 150) * 60 * 5
    clips = max(5, int(duration_seconds // 7))
    return min(clips, 80)


def _estimate_eta_minutes(file_size_bytes: int) -> int:
    """Estimate processing time in minutes."""
    mb = file_size_bytes / (1024 * 1024)
    return max(5, int((mb / 100) * 3) + 3)


async def _process_locally(
    local_video_path: str,
    job_id: str,
    creator_name: str,
    output_folder_id: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE
):
    """
    Background task:
    1. Call local processor via HTTP
    2. Send ZIP file directly in Telegram
    3. Send Drive folder link
    """
    try:
        # ── Step 1: Trigger local processor ────────────────────────────────
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚙️ Processing started! I'll message you when clips are ready."
        )

        update_job(job_id, STATUS_PROCESSING)

        payload = {
            "local_path": os.path.abspath(local_video_path),
            "job_id": job_id,
            "creator_name": creator_name,
            "output_folder_id": output_folder_id or PROCESSED_FOLDER_ID,
        }

        async with httpx.AsyncClient(timeout=3600) as client:
            response = await client.post(
                CLOUD_RUN_URL.rstrip("/") + "/process",
                json=payload,
            )

        if response.status_code != 200:
            raise Exception(f"Processor returned {response.status_code}: {response.text}")

        result = response.json()
        clip_count    = result.get("clips_processed", 0)
        folder_link   = result.get("folder_link", "")
        zip_path      = result.get("zip_path", "")
        zip_size_mb   = result.get("zip_size_mb", 0)

        update_job(
            job_id=job_id,
            status=STATUS_DONE,
            clip_count=clip_count,
            folder_link=folder_link
        )

        # ── Step 2: Send ZIP directly via Telegram ─────────────────────────
        if zip_path and os.path.exists(zip_path):
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ {clip_count} clips processed! Sending ZIP... 📦"
            )

            with open(zip_path, "rb") as zf:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=zf,
                    filename=f"{creator_name}_clips_{job_id}.zip",
                    caption=f"🎬 {clip_count} clips ready!"
                )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ {clip_count} clips processed! (ZIP not available locally)"
            )

        # ── Step 3: Send Drive folder link ─────────────────────────────────
        if folder_link:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📁 Open Drive Folder", url=folder_link)],
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
                    f"Clips are also in your Google Drive folder:"
                )
            )

        logger.info(f"[{job_id}] ✅ All done. Notified {chat_id}")

    except Exception as e:
        logger.error(f"[{job_id}] Background task failed: {e}", exc_info=True)
        update_job(job_id, STATUS_FAILED)
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
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"❌ Something went wrong processing your video.\n\n"
                    f"Job ID: {job_id}\n"
                    f"Error: {safe_error}\n\n"
                    f"Please contact your manager and share this Job ID."
                )
            )


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
        "4️⃣ When done, you get a ZIP file + Drive folder link\n\n"
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
        job = get_job(args[0])
        if not job:
            await update.message.reply_text(f"❌ Job `{args[0]}` not found.", parse_mode=ParseMode.MARKDOWN)
            return
    else:
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
    for admin_id, reg_data in list(_pending_registrations.items()):
        creator_name = reg_data["creator_name"]
        logger.info(f"Registering user {user.id} ({user.first_name}) as '{creator_name}' via video (initiated by admin {admin_id})")
        success, err = register_creator(user.id, creator_name)
        if success:
            del _pending_registrations[admin_id]
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

    # ── Download video to local folder ────────────────────────────────────────
    try:
        tg_file = await context.bot.get_file(video.file_id)
    except Exception as e:
        await message.reply_text(
            "❌ Could not download your video. This usually means the file is too large for direct Telegram transfer.\n\n"
            "Please try sending it as a compressed file, or contact your manager."
        )
        logger.error(f"get_file failed: {e}")
        return

    local_path = os.path.join(LOCAL_UPLOAD_DIR, f"{job_id}_source.mp4")
    try:
        await tg_file.download_to_drive(local_path)
        logger.info(f"[{job_id}] Downloaded to {local_path} ({file_size_mb:.0f} MB)")
    except Exception as e:
        logger.error(f"[{job_id}] Failed to download video from Telegram: {e}")
        await message.reply_text(
            "❌ Failed to download your video. Please try again."
        )
        return

    # Kick off background processing
    asyncio.create_task(
        _process_locally(
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

    # Complete pending registration
    for admin_id, reg_data in list(_pending_registrations.items()):
        creator_name = reg_data["creator_name"]
        logger.info(f"Registering user {user.id} ({user.first_name}) as '{creator_name}' (initiated by admin {admin_id})")
        success, err = register_creator(user.id, creator_name)
        if success:
            del _pending_registrations[admin_id]
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    """Start the bot."""
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not CLOUD_RUN_URL:
        raise RuntimeError("CLOUD_RUN_URL not set (default: http://localhost:8080)")

    logger.info("Starting Bunny Clip Bot (local mode)...")
    logger.info(f"Processor URL: {CLOUD_RUN_URL}")

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

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
