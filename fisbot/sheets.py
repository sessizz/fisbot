import json
import logging
import random
import re
import time

import gspread
import requests
from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

from fisbot.config import (
    GOOGLE_SHEETS_CREDENTIALS_JSON,
    GOOGLE_SHEETS_CREDENTIALS_PATH,
    SPREADSHEET_ID,
)
from fisbot.parser import ReceiptData

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None
MAX_SYNC_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 30
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        if GOOGLE_SHEETS_CREDENTIALS_JSON:
            service_account_info = json.loads(GOOGLE_SHEETS_CREDENTIALS_JSON)
            creds = Credentials.from_service_account_info(
                service_account_info, scopes=SCOPES
            )
        else:
            creds = Credentials.from_service_account_file(
                str(GOOGLE_SHEETS_CREDENTIALS_PATH), scopes=SCOPES
            )
        _client = gspread.authorize(creds)
        _client.set_timeout(REQUEST_TIMEOUT_SECONDS)
    return _client


def _reset_client() -> None:
    global _client
    _client = None


def _is_retryable_sheets_error(exc: Exception) -> bool:
    if isinstance(exc, APIError):
        return exc.code in RETRYABLE_STATUS_CODES
    return isinstance(
        exc,
        (
            ConnectionError,
            TimeoutError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
            TransportError,
            RefreshError,
        ),
    )


def _sleep_before_retry(attempt: int) -> None:
    delay = min(2 ** (attempt - 1), 8)
    time.sleep(delay + random.uniform(0, 0.4))


def _append_rows_with_retry(rows: list[list[object]]) -> int:
    if not rows:
        return 0

    last_error: Exception | None = None
    for attempt in range(1, MAX_SYNC_ATTEMPTS + 1):
        try:
            client = _get_client()
            sheet = client.open_by_key(SPREADSHEET_ID).sheet1
            sheet.append_rows(rows, value_input_option="USER_ENTERED")
            if attempt > 1:
                logger.info(
                    "Google Sheets sync succeeded on attempt %d after retry",
                    attempt,
                )
            return len(rows)
        except Exception as exc:
            last_error = exc
            retryable = _is_retryable_sheets_error(exc)
            if isinstance(exc, GoogleAuthError):
                _reset_client()
            elif retryable:
                _reset_client()

            if not retryable or attempt >= MAX_SYNC_ATTEMPTS:
                break

            logger.warning(
                "Google Sheets sync attempt %d/%d failed; retrying: %s",
                attempt,
                MAX_SYNC_ATTEMPTS,
                exc,
            )
            _sleep_before_retry(attempt)

    if last_error is not None:
        raise last_error
    return 0


def _normalize_date(date_str: str | None) -> str:
    """Normalize date to dd.mm.yyyy format."""
    if not date_str:
        return ""
    # Replace slashes and dashes with dots
    normalized = date_str.strip().replace("/", ".").replace("-", ".")
    # Validate dd.mm.yyyy pattern
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", normalized)
    if m:
        return f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.{m.group(3)}"
    return normalized


def append_receipt_to_sheet(receipt: ReceiptData) -> int:
    """Append receipt rows to Google Spreadsheet. Returns number of rows added."""
    tarih = _normalize_date(receipt.tarih)

    rows = []
    for item in receipt.urunler:
        row = [
            "Perakende Satış Fişi",       # A
            tarih,                          # B
            "A",                            # C
            receipt.fis_no or "",           # D
            100,                            # E - number
            "",                             # F
            item.stok,                      # G
            1,                              # H - number
            item.net,                       # I - number
            item.net,                       # J - number
            item.kdv_oran,                  # K - number
            item.kdv,                       # L - number
            "",                             # M
            "",                             # N
            item.toplam,                    # O - number
            "PERAKENDE SATIŞ FİŞİ",        # P
            "",                             # Q
            "",                             # R
            item.toplam,                    # S - number
        ]
        rows.append(row)

    row_count = _append_rows_with_retry(rows)
    if row_count:
        logger.info("Appended %d rows to Google Sheet", row_count)
    return row_count


def append_dashboard_rows_to_sheet(rows_data: list[dict]) -> int:
    """Append dashboard DB rows to Google Spreadsheet after manual stock review."""
    rows = []
    for item in rows_data:
        row = [
            "Perakende Satış Fişi",       # A
            _normalize_date(item.get("receipt_date")),  # B
            "A",                            # C
            item.get("receipt_no") or "",   # D
            100,                            # E - number
            "",                             # F
            item["stock_code"],             # G
            1,                              # H - number
            item.get("net_amount"),         # I - number
            item.get("net_amount"),         # J - number
            item.get("vat_rate"),           # K - number
            item.get("vat_amount"),         # L - number
            "",                             # M
            "",                             # N
            item.get("total_amount"),       # O - number
            "PERAKENDE SATIŞ FİŞİ",        # P
            "",                             # Q
            "",                             # R
            item.get("total_amount"),       # S - number
        ]
        rows.append(row)

    row_count = _append_rows_with_retry(rows)
    if row_count:
        logger.info("Appended %d reviewed rows to Google Sheet", row_count)
    return row_count
