"""
bot/main.py — Telegram Bot for Bunny Clip Tool

Flow:
1. User sends video
2. Bot replies with job confirmation (job_id, ETA)
3. Background task:
   a. Download video from Telegram to /tmp
   b. Upload to GCS: gs://bunny-clip-tool-videos/uploads/{job_id}/source_video.mp4
   c. POST to processor: {job_id, gcs_uri, creator_name}
   d. Processor returns: {status, zip_gcs_uri}
   e. Download ZIP from GCS to /tmp
   f. Send ZIP to user via Telegram
   g. Clean up /tmp
4. On error: send user-friendly error message (plain text, no markdown)
"""

import os
import uuid
import asyncio
import logging
import tempfile
import shutil

from google.cloud import storage as gcs
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
import google.auth
import google.auth.transport.requests
import google.oauth2.id_token
import httpx

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
PROCESSOR_URL = os.environ["PROCESSOR_URL"]  # e.g. https://bunny-clip-processor-xxx.run.app
GCS_BUCKET = os.environ.get("GCS_BUCKET", "bunny-clip-tool-videos")

# GCS client — uses Cloud Run's built-in service account, no key file needed
gcs_client = gcs.Client()
bucket = gcs_client.bucket(GCS_BUCKET)


def generate_job_id() -> str:
    return uuid.uuid4().hex[:8].upper()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me a video (up to 5 min) and I'll create short clips for you."
    )


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming video message."""
    video = update.message.video or update.message.document
    if not video:
        return

    job_id = generate_job_id()
    chat_id = update.effective_chat.id
    file_size_mb = (video.file_size or 0) / (1024 * 1024)

    logger.info(f"[{job_id}] Video received ({file_size_mb:.0f} MB) from chat {chat_id}")

    # Send confirmation
    await update.message.reply_text(
        f"Got it!\n\n"
        f"Video received ({file_size_mb:.0f} MB)\n"
        f"~5 clips will be generated\n"
        f"ETA: ~3-5 minutes\n"
        f"Job ID: {job_id}\n\n"
        f"I'll send you the clips when ready!"
    )

    # Process in background
    asyncio.create_task(_process_video(update, context, video, job_id, chat_id))


async def _process_video(update, context, video, job_id, chat_id):
    """Background task: download -> upload to GCS -> call processor -> send ZIP."""
    tmp_dir = tempfile.mkdtemp(prefix=f"bunny_{job_id}_")

    try:
        # 1. Download from Telegram
        tg_file = await context.bot.get_file(video.file_id)
        source_path = os.path.join(tmp_dir, f"{job_id}_source.mp4")
        await tg_file.download_to_drive(source_path)
        file_size_mb = os.path.getsize(source_path) / (1024 * 1024)
        logger.info(f"[{job_id}] Downloaded to {source_path} ({file_size_mb:.0f} MB)")

        # 2. Upload to GCS
        gcs_key = f"uploads/{job_id}/source_video.mp4"
        blob = bucket.blob(gcs_key)
        blob.upload_from_filename(source_path)
        gcs_uri = f"gs://{GCS_BUCKET}/{gcs_key}"
        logger.info(f"[{job_id}] Uploaded to GCS: {gcs_uri}")

        await context.bot.send_message(
            chat_id=chat_id, text="Uploaded! Processing started..."
        )

        # 3. Call processor (authenticated with ID token)
        id_token = _get_id_token(PROCESSOR_URL)

        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(
                f"{PROCESSOR_URL}/process",
                json={
                    "job_id": job_id,
                    "gcs_uri": gcs_uri,
                    "creator_name": "Creator",
                },
                headers={"Authorization": f"Bearer {id_token}"},
            )

        if response.status_code != 200:
            raise Exception(
                f"Processor returned {response.status_code}: {response.text[:300]}"
            )

        result = response.json()
        zip_gcs_uri = result["zip_gcs_uri"]
        clip_count = result.get("clip_count", 0)
        logger.info(
            f"[{job_id}] Processor done: {clip_count} clips, ZIP at {zip_gcs_uri}"
        )

        # 4. Download ZIP from GCS
        zip_path = os.path.join(tmp_dir, f"{job_id}_clips.zip")
        zip_blob_key = zip_gcs_uri.replace(f"gs://{GCS_BUCKET}/", "")
        bucket.blob(zip_blob_key).download_to_filename(zip_path)
        logger.info(
            f"[{job_id}] Downloaded ZIP ({os.path.getsize(zip_path) / (1024 * 1024):.1f} MB)"
        )

        # 5. Send ZIP to user via Telegram
        with open(zip_path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=f"{job_id}_clips.zip",
                caption=f"Done! {clip_count} clips generated.\nJob ID: {job_id}",
            )
        logger.info(f"[{job_id}] ZIP sent to user")

    except Exception as e:
        logger.error(f"[{job_id}] Failed: {e}", exc_info=True)
        safe_error = (
            str(e)[:200].replace("`", "").replace("*", "").replace("_", "")
        )
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Something went wrong.\n\nJob ID: {job_id}\nError: {safe_error}",
            )
        except Exception:
            pass  # If even the error message fails, just log it

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.info(f"[{job_id}] Cleaned up {tmp_dir}")


def _get_id_token(target_url: str) -> str:
    """Get an ID token for authenticating to the processor Cloud Run service.
    Uses the built-in service account — no key file needed."""
    request = google.auth.transport.requests.Request()
    token = google.oauth2.id_token.fetch_id_token(request, target_url)
    return token


def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(
        MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video)
    )

    logger.info("Bot starting (polling mode)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
