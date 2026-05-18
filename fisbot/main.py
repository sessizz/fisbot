import asyncio
import logging
import sys

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from fisbot.config import TELEGRAM_BOT_TOKEN
from fisbot.handlers import handle_help, handle_id, handle_photo, handle_start, handle_text
from fisbot.gemini_client import check_gemini

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def startup_checks() -> bool:
    """Run startup health checks."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Please set it in .env file or as an environment variable."
        )
        return False

    if not await check_gemini():
        return False

    return True


def main() -> None:
    """Entry point for the bot."""
    if not asyncio.run(startup_checks()):
        sys.exit(1)

    logger.info("Starting FişBot...")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("id", handle_id))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("FişBot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
