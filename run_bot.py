"""
Bunny Clip Tool — Bot Entry Point
===================================
Loads environment variables and starts the Telegram bot.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("Starting Bunny Clip Bot...")
    from telegram_bot.bot import main
    main()
