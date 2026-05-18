import asyncio
import logging
import sys

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
import uvicorn

from fisbot.config import TELEGRAM_BOT_TOKEN, WEB_HOST, WEB_PORT
from fisbot.dashboard_store import init_db
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


def build_telegram_app():
    logger.info("Starting FişBot...")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("id", handle_id))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    return app


async def run_telegram_bot(stop_event: asyncio.Event) -> None:
    app = build_telegram_app()

    async with app:
        if app.updater is None:
            raise RuntimeError("Telegram updater is not available")
        await app.updater.start_polling()
        await app.start()

        logger.info("FişBot Telegram polling is running.")
        await stop_event.wait()

        await app.updater.stop()
        await app.stop()


async def run_web_server() -> None:
    config = uvicorn.Config(
        "fisbot.web:app",
        host=WEB_HOST,
        port=WEB_PORT,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info("FisBot dashboard is running on http://%s:%s", WEB_HOST, WEB_PORT)
    await server.serve()


async def async_main() -> int:
    """Run Telegram polling and the web dashboard in the same process."""
    if not await startup_checks():
        return 1

    init_db()
    stop_event = asyncio.Event()
    tasks = [
        asyncio.create_task(run_telegram_bot(stop_event)),
        asyncio.create_task(run_web_server()),
    ]

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except (KeyboardInterrupt, asyncio.CancelledError):
        stop_event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return 0


def main() -> None:
    """Entry point for the bot and dashboard."""
    sys.exit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
