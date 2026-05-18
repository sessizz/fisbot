import logging
import re

import gspread
from google.oauth2.service_account import Credentials

from fisbot.config import GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SPREADSHEET_ID
from fisbot.parser import ReceiptData

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            str(GOOGLE_SHEETS_CREDENTIALS), scopes=SCOPES
        )
        _client = gspread.authorize(creds)
    return _client


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
    client = _get_client()
    sheet = client.open_by_key(GOOGLE_SPREADSHEET_ID).sheet1

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

    if rows:
        sheet.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info("Appended %d rows to Google Sheet", len(rows))

    return len(rows)
