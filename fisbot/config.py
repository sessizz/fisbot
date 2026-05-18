import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Gemini API
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODELS: list[str] = [
    m.strip()
    for m in os.getenv(
        "GEMINI_MODELS",
        "gemini-2.5-flash-lite,gemini-2.5-flash,gemini-3-flash,gemini-3.1-flash-lite",
    ).split(",")
    if m.strip()
]

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"

# Comma-separated Telegram user IDs that are allowed to use the bot.
# Leave empty to allow everyone (not recommended for production).
_allowed = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: list[int] = [int(uid.strip()) for uid in _allowed.split(",") if uid.strip()]

MAX_IMAGE_DIMENSION: int = 2048

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS: Path = Path(__file__).resolve().parent.parent / "credentials.json"
GOOGLE_SPREADSHEET_ID: str = os.getenv(
    "GOOGLE_SPREADSHEET_ID", "19ocBMWXsv3awOCaJLErqT-BVlCYYL1PvYIAfQflWFlk"
)
