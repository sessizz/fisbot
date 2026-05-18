import sqlite3
from datetime import UTC, datetime
from typing import Any

from fisbot.config import DATA_DIR
from fisbot.parser import ReceiptData, STOK_KODLARI

DB_PATH = DATA_DIR / "fisbot.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS receipt_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                receipt_date TEXT,
                receipt_no TEXT,
                store_name TEXT,
                item_name TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                vat_rate INTEGER,
                vat_amount REAL NOT NULL,
                total_amount REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_receipt_items_created_at
            ON receipt_items(created_at DESC)
            """
        )


def add_receipt_items(receipt: ReceiptData) -> list[dict[str, Any]]:
    init_db()
    created_at = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []

    with _connect() as conn:
        for item in receipt.urunler:
            stock_name = STOK_KODLARI.get(item.stok, item.stok)
            cursor = conn.execute(
                """
                INSERT INTO receipt_items (
                    created_at,
                    receipt_date,
                    receipt_no,
                    store_name,
                    item_name,
                    stock_code,
                    stock_name,
                    vat_rate,
                    vat_amount,
                    total_amount
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    receipt.tarih,
                    receipt.fis_no,
                    receipt.magaza_adi,
                    item.ad,
                    item.stok,
                    stock_name,
                    item.kdv_oran,
                    item.kdv,
                    item.toplam,
                ),
            )
            rows.append(
                {
                    "id": cursor.lastrowid,
                    "created_at": created_at,
                    "receipt_date": receipt.tarih,
                    "receipt_no": receipt.fis_no,
                    "store_name": receipt.magaza_adi,
                    "item_name": item.ad,
                    "stock_code": item.stok,
                    "stock_name": stock_name,
                    "vat_rate": item.kdv_oran,
                    "vat_amount": item.kdv,
                    "total_amount": item.toplam,
                }
            )

    return rows


def recent_receipt_items(limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    safe_limit = max(1, min(limit, 500))
    with _connect() as conn:
        cursor = conn.execute(
            """
            SELECT
                id,
                created_at,
                receipt_date,
                receipt_no,
                store_name,
                item_name,
                stock_code,
                stock_name,
                vat_rate,
                vat_amount,
                total_amount
            FROM receipt_items
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
