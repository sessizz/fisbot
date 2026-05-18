# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

FişBot is a Telegram bot that extracts structured data from Turkish receipt (fiş) photos using Google Gemini AI and saves the results to local Markdown files and Google Sheets.

## Commands

```bash
# Install dependencies (Python 3.11+ required)
pip install -e .

# Run the bot
fisbot

# Run with environment variables loaded from .env
python -m fisbot.main
```

No test framework or linter is configured. The project has an empty `tests/` directory.

## Required Environment Variables (`.env`)

- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `GEMINI_API_KEY` — Google AI API key
- `GEMINI_MODELS` — Comma-separated list of Gemini model IDs (tried in order as fallback)
- `ALLOWED_USERS` — Comma-separated Telegram user IDs for access control (empty = allow all)
- `GOOGLE_SHEETS_CREDENTIALS_PATH` — Path to Google OAuth2 service account JSON
- `SPREADSHEET_ID` — Target Google Sheets spreadsheet ID

## Architecture

**Data flow:** User sends photo via Telegram → `handlers.py` receives it → `image_utils.py` resizes/preprocesses → `gemini_client.py` sends to Gemini with the prompt from `prompt.py` → `parser.py` validates JSON response into Pydantic models → `storage.py` saves Markdown to `data/YYYY/MM/` → `sheets.py` appends 19-column row to Google Sheets → bot replies with summary.

**Key modules:**

- `config.py` — Loads all env vars with defaults; single source of truth for configuration
- `gemini_client.py` — Gemini API wrapper with rate limiting (15 req/60s rolling window via `deque`) and model fallback across `GEMINI_MODELS`
- `parser.py` — Pydantic models (`ReceiptItem`, `ReceiptData`) and Turkish number format parsing (e.g., `1.250,50` → `1250.50`). Also handles KDV (VAT) rate guessing (1%, 10%, 20%) with mathematical verification.
- `prompt.py` — System prompt in Turkish that instructs Gemini on receipt format, stock code categorization (8 Turkish expense categories), and multi-receipt support (single photo may contain multiple receipts)
- `sheets.py` — Google Sheets via `gspread`; appends rows with one row per receipt item (19 columns)
- `ollama_client.py` — Alternative local LLM path (Ollama), not wired into main flow by default

**Multi-receipt:** A single photo can contain multiple receipts; `parser.py` handles a list of `ReceiptData` objects and `handlers.py` iterates over them.

**Access control:** `handlers.py` checks `ALLOWED_USERS` on every message; if the list is non-empty and the sender is not in it, the request is rejected silently.
