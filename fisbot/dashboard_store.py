import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

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
                receipt_group_id TEXT,
                created_at TEXT NOT NULL,
                receipt_date TEXT,
                receipt_no TEXT,
                store_name TEXT,
                item_name TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                vat_rate INTEGER,
                net_amount REAL NOT NULL DEFAULT 0,
                vat_amount REAL NOT NULL,
                total_amount REAL NOT NULL,
                needs_stock_review INTEGER NOT NULL DEFAULT 0,
                sheet_appended INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        _ensure_column(conn, "receipt_group_id", "TEXT")
        _ensure_column(conn, "net_amount", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "needs_stock_review", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "sheet_appended", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_receipt_items_created_at
            ON receipt_items(created_at DESC)
            """
        )


def _ensure_column(conn: sqlite3.Connection, name: str, definition: str) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(receipt_items)").fetchall()
    }
    if name not in columns:
        conn.execute(f"ALTER TABLE receipt_items ADD COLUMN {name} {definition}")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["needs_stock_review"] = bool(data.get("needs_stock_review"))
    data["sheet_appended"] = bool(data.get("sheet_appended"))
    return data


def add_receipt_items(receipt: ReceiptData) -> list[dict[str, Any]]:
    init_db()
    created_at = datetime.now(UTC).isoformat()
    receipt_group_id = uuid4().hex
    rows: list[dict[str, Any]] = []

    with _connect() as conn:
        for item in receipt.urunler:
            stock_name = (
                "Secim bekliyor"
                if item.stok_secim_gerekli
                else STOK_KODLARI.get(item.stok, item.stok)
            )
            cursor = conn.execute(
                """
                INSERT INTO receipt_items (
                    receipt_group_id,
                    created_at,
                    receipt_date,
                    receipt_no,
                    store_name,
                    item_name,
                    stock_code,
                    stock_name,
                    vat_rate,
                    net_amount,
                    vat_amount,
                    total_amount,
                    needs_stock_review,
                    sheet_appended
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_group_id,
                    created_at,
                    receipt.tarih,
                    receipt.fis_no,
                    receipt.magaza_adi,
                    item.ad,
                    item.stok,
                    stock_name,
                    item.kdv_oran,
                    item.net,
                    item.kdv,
                    item.toplam,
                    int(item.stok_secim_gerekli),
                    0,
                ),
            )
            rows.append(
                {
                    "id": cursor.lastrowid,
                    "receipt_group_id": receipt_group_id,
                    "created_at": created_at,
                    "receipt_date": receipt.tarih,
                    "receipt_no": receipt.fis_no,
                    "store_name": receipt.magaza_adi,
                    "item_name": item.ad,
                    "stock_code": item.stok,
                    "stock_name": stock_name,
                    "vat_rate": item.kdv_oran,
                    "net_amount": item.net,
                    "vat_amount": item.kdv,
                    "total_amount": item.toplam,
                    "needs_stock_review": item.stok_secim_gerekli,
                    "sheet_appended": False,
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
                receipt_group_id,
                created_at,
                receipt_date,
                receipt_no,
                store_name,
                item_name,
                stock_code,
                stock_name,
                vat_rate,
                net_amount,
                vat_amount,
                total_amount,
                needs_stock_review,
                sheet_appended
            FROM receipt_items
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]


def pending_stock_items(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    safe_limit = max(1, min(limit, 200))
    with _connect() as conn:
        cursor = conn.execute(
            """
            SELECT
                id,
                receipt_group_id,
                created_at,
                receipt_date,
                receipt_no,
                store_name,
                item_name,
                stock_code,
                stock_name,
                vat_rate,
                net_amount,
                vat_amount,
                total_amount,
                needs_stock_review,
                sheet_appended
            FROM receipt_items
            WHERE needs_stock_review = 1
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]


def update_item_stock(item_id: int, stock_code: str) -> dict[str, Any]:
    init_db()
    if stock_code not in STOK_KODLARI:
        raise ValueError("Unknown stock code")

    with _connect() as conn:
        conn.execute(
            """
            UPDATE receipt_items
            SET stock_code = ?,
                stock_name = ?,
                needs_stock_review = 0
            WHERE id = ?
            """,
            (stock_code, STOK_KODLARI[stock_code], item_id),
        )
        cursor = conn.execute(
            """
            SELECT
                id,
                receipt_group_id,
                created_at,
                receipt_date,
                receipt_no,
                store_name,
                item_name,
                stock_code,
                stock_name,
                vat_rate,
                net_amount,
                vat_amount,
                total_amount,
                needs_stock_review,
                sheet_appended
            FROM receipt_items
            WHERE id = ?
            """,
            (item_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Receipt item not found")
        return _row_to_dict(row)


def receipt_group_ready_for_sheet(receipt_group_id: str) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        pending = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM receipt_items
            WHERE receipt_group_id = ? AND needs_stock_review = 1
            """,
            (receipt_group_id,),
        ).fetchone()["count"]
        if pending:
            return []

        already_appended = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM receipt_items
            WHERE receipt_group_id = ? AND sheet_appended = 1
            """,
            (receipt_group_id,),
        ).fetchone()["count"]
        if already_appended:
            return []

        cursor = conn.execute(
            """
            SELECT
                id,
                receipt_group_id,
                created_at,
                receipt_date,
                receipt_no,
                store_name,
                item_name,
                stock_code,
                stock_name,
                vat_rate,
                net_amount,
                vat_amount,
                total_amount,
                needs_stock_review,
                sheet_appended
            FROM receipt_items
            WHERE receipt_group_id = ?
            ORDER BY id ASC
            """,
            (receipt_group_id,),
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]


def mark_receipt_group_appended(receipt_group_id: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE receipt_items
            SET sheet_appended = 1
            WHERE receipt_group_id = ?
            """,
            (receipt_group_id,),
        )


def stock_code_options() -> list[dict[str, str]]:
    return [{"code": code, "name": name} for code, name in STOK_KODLARI.items()]
