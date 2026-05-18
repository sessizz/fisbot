import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fisbot.config import DATA_DIR
from fisbot.parser import ReceiptData, STOK_KODLARI

DB_PATH = DATA_DIR / "fisbot.db"

RECEIPT_STATUSES = {
    "received",
    "extracting",
    "verifying",
    "needs_review",
    "ready_to_sync",
    "synced",
    "sync_failed",
}


def set_db_path(path: Path) -> None:
    """Override the DB path for tests."""
    global DB_PATH
    DB_PATH = path


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                image_path TEXT NOT NULL,
                telegram_user_id INTEGER,
                telegram_user_name TEXT,
                receipt_date TEXT,
                receipt_no TEXT,
                store_name TEXT,
                payment_method TEXT,
                total_vat REAL,
                grand_total REAL NOT NULL DEFAULT 0,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                raw_extraction_json TEXT,
                raw_verification_json TEXT,
                sheet_appended_at TEXT,
                sheet_error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS receipt_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id TEXT,
                receipt_group_id TEXT,
                created_at TEXT,
                receipt_date TEXT,
                receipt_no TEXT,
                store_name TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                item_name TEXT NOT NULL DEFAULT '',
                stock_code TEXT NOT NULL DEFAULT '',
                stock_name TEXT NOT NULL DEFAULT '',
                vat_rate INTEGER,
                net_amount REAL NOT NULL DEFAULT 0,
                vat_amount REAL NOT NULL DEFAULT 0,
                total_amount REAL NOT NULL DEFAULT 0,
                needs_review INTEGER NOT NULL DEFAULT 0,
                review_reason TEXT,
                needs_stock_review INTEGER NOT NULL DEFAULT 0,
                sheet_appended INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                receipt_id TEXT,
                level TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS review_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                receipt_id TEXT NOT NULL,
                item_id INTEGER,
                field_name TEXT NOT NULL,
                label TEXT NOT NULL,
                current_value TEXT,
                status TEXT NOT NULL DEFAULT 'open'
            )
            """
        )

        # Columns for old DBs created by the first dashboard iteration.
        _ensure_column(conn, "receipt_items", "receipt_id", "TEXT")
        _ensure_column(conn, "receipt_items", "receipt_group_id", "TEXT")
        _ensure_column(conn, "receipt_items", "created_at", "TEXT")
        _ensure_column(conn, "receipt_items", "receipt_date", "TEXT")
        _ensure_column(conn, "receipt_items", "receipt_no", "TEXT")
        _ensure_column(conn, "receipt_items", "store_name", "TEXT")
        _ensure_column(conn, "receipt_items", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "receipt_items", "item_name", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "receipt_items", "stock_code", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "receipt_items", "stock_name", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "receipt_items", "vat_rate", "INTEGER")
        _ensure_column(conn, "receipt_items", "net_amount", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "receipt_items", "vat_amount", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "receipt_items", "total_amount", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "receipt_items", "needs_review", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "receipt_items", "review_reason", "TEXT")
        _ensure_column(
            conn, "receipt_items", "needs_stock_review", "INTEGER NOT NULL DEFAULT 0"
        )
        _ensure_column(conn, "receipt_items", "sheet_appended", "INTEGER NOT NULL DEFAULT 0")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_receipts_created_at
            ON receipts(created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt_id
            ON receipt_items(receipt_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_review_tasks_status
            ON review_tasks(status, receipt_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_processing_events_created_at
            ON processing_events(created_at DESC)
            """
        )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _bool_row(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("needs_review", "needs_stock_review", "sheet_appended"):
        if key in data:
            data[key] = bool(data[key])
    return data


def _receipt_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["warnings"] = _json_loads(data.pop("warnings_json", None), [])
    data["image_url"] = f"/api/receipts/{data['id']}/image"
    return data


def create_receipt(
    *,
    image_path: Path,
    telegram_user_id: int | None,
    telegram_user_name: str | None,
) -> dict[str, Any]:
    init_db()
    receipt_id = uuid4().hex
    timestamp = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO receipts (
                id,
                created_at,
                updated_at,
                status,
                image_path,
                telegram_user_id,
                telegram_user_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                timestamp,
                timestamp,
                "received",
                str(image_path),
                telegram_user_id,
                telegram_user_name,
            ),
        )
    return get_receipt(receipt_id)


def get_receipt(receipt_id: str) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM receipts WHERE id = ?",
            (receipt_id,),
        ).fetchone()
    receipt = _receipt_row(row)
    if receipt is None:
        raise ValueError("Receipt not found")
    return receipt


def update_receipt_status(
    receipt_id: str,
    status: str,
    *,
    sheet_error: str | None = None,
) -> dict[str, Any]:
    if status not in RECEIPT_STATUSES:
        raise ValueError(f"Unknown receipt status: {status}")
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE receipts
            SET status = ?, updated_at = ?, sheet_error = ?
            WHERE id = ?
            """,
            (status, now_iso(), sheet_error, receipt_id),
        )
    return get_receipt(receipt_id)


def add_event(
    receipt_id: str | None,
    title: str,
    message: str,
    *,
    level: str = "info",
) -> dict[str, Any]:
    init_db()
    timestamp = now_iso()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO processing_events (created_at, receipt_id, level, title, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (timestamp, receipt_id, level, title, message),
        )
    return {
        "id": cursor.lastrowid,
        "created_at": timestamp,
        "receipt_id": receipt_id,
        "level": level,
        "title": title,
        "message": message,
    }


def recent_events(limit: int = 25) -> list[dict[str, Any]]:
    init_db()
    safe_limit = max(1, min(limit, 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, receipt_id, level, title, message
            FROM processing_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _task(
    receipt_id: str,
    item_id: int | None,
    field_name: str,
    label: str,
    current_value: Any,
) -> tuple[str, str, int | None, str, str, str]:
    return (
        now_iso(),
        receipt_id,
        item_id,
        field_name,
        label,
        "" if current_value is None else str(current_value),
    )


def _receipt_tasks(receipt_id: str, receipt: ReceiptData) -> list[tuple]:
    tasks: list[tuple] = []
    if receipt.tarih_secim_gerekli:
        tasks.append(_task(receipt_id, None, "receipt_date", "Fiş tarihi", receipt.tarih))
    if receipt.fis_no_secim_gerekli:
        tasks.append(_task(receipt_id, None, "receipt_no", "Fiş no", receipt.fis_no))
    if receipt.genel_toplam_secim_gerekli or receipt.genel_toplam <= 0:
        tasks.append(
            _task(receipt_id, None, "grand_total", "Genel toplam", receipt.genel_toplam)
        )

    item_sum = round(sum(item.toplam for item in receipt.urunler), 2)
    if receipt.genel_toplam and item_sum and abs(item_sum - receipt.genel_toplam) > 0.05:
        tasks.append(
            _task(
                receipt_id,
                None,
                "grand_total",
                "Genel toplam tutarsız",
                receipt.genel_toplam,
            )
        )
    if not receipt.urunler:
        tasks.append(_task(receipt_id, None, "items", "Ürün satırları", ""))
    return tasks


def save_receipt_extraction(
    receipt_id: str,
    receipt: ReceiptData,
    *,
    raw_extraction: Any,
    raw_verification: Any,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    init_db()
    timestamp = now_iso()
    warning_list = list(warnings or [])
    with _connect() as conn:
        conn.execute("DELETE FROM receipt_items WHERE receipt_id = ?", (receipt_id,))
        conn.execute("DELETE FROM review_tasks WHERE receipt_id = ?", (receipt_id,))

        conn.execute(
            """
            UPDATE receipts
            SET updated_at = ?,
                receipt_date = ?,
                receipt_no = ?,
                store_name = ?,
                payment_method = ?,
                total_vat = ?,
                grand_total = ?,
                warnings_json = ?,
                raw_extraction_json = ?,
                raw_verification_json = ?
            WHERE id = ?
            """,
            (
                timestamp,
                receipt.tarih,
                receipt.fis_no,
                receipt.magaza_adi,
                receipt.odeme_yontemi,
                receipt.toplam_kdv,
                receipt.genel_toplam,
                _json_dumps(warning_list),
                _json_dumps(raw_extraction),
                _json_dumps(raw_verification),
                receipt_id,
            ),
        )

        task_rows = _receipt_tasks(receipt_id, receipt)
        for index, item in enumerate(receipt.urunler):
            stock_name = (
                "Seçim bekliyor"
                if item.stok_secim_gerekli
                else STOK_KODLARI.get(item.stok, item.stok)
            )
            item_review_reasons: list[str] = []
            if item.ad_secim_gerekli:
                item_review_reasons.append("Ürün adı okunamadı")
            if item.stok_secim_gerekli:
                item_review_reasons.append("Stok kodu seçilmeli")
            if item.toplam_secim_gerekli or item.toplam <= 0:
                item_review_reasons.append("Toplam tutar eksik")

            cursor = conn.execute(
                """
                INSERT INTO receipt_items (
                    receipt_id,
                    receipt_group_id,
                    created_at,
                    receipt_date,
                    receipt_no,
                    store_name,
                    sort_order,
                    item_name,
                    stock_code,
                    stock_name,
                    vat_rate,
                    net_amount,
                    vat_amount,
                    total_amount,
                    needs_review,
                    review_reason,
                    needs_stock_review,
                    sheet_appended
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    receipt_id,
                    timestamp,
                    receipt.tarih,
                    receipt.fis_no,
                    receipt.magaza_adi,
                    index,
                    item.ad,
                    item.stok,
                    stock_name,
                    item.kdv_oran,
                    item.net,
                    item.kdv,
                    item.toplam,
                    int(bool(item_review_reasons)),
                    "; ".join(item_review_reasons),
                    int(item.stok_secim_gerekli),
                    0,
                ),
            )
            item_id = cursor.lastrowid
            if item.ad_secim_gerekli:
                task_rows.append(
                    _task(receipt_id, item_id, "item_name", "Ürün adı", item.ad)
                )
            if item.stok_secim_gerekli:
                task_rows.append(
                    _task(receipt_id, item_id, "stock_code", "Stok kodu", item.stok)
                )
            if item.toplam_secim_gerekli or item.toplam <= 0:
                task_rows.append(
                    _task(receipt_id, item_id, "total_amount", "Toplam tutar", item.toplam)
                )

        if task_rows:
            conn.executemany(
                """
                INSERT INTO review_tasks (
                    created_at,
                    receipt_id,
                    item_id,
                    field_name,
                    label,
                    current_value
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                task_rows,
            )

    status = "needs_review" if task_rows else "ready_to_sync"
    return update_receipt_status(receipt_id, status)


def _item_row(row: sqlite3.Row) -> dict[str, Any]:
    return _bool_row(dict(row))


def receipt_items(receipt_id: str) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM receipt_items
            WHERE receipt_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (receipt_id,),
        ).fetchall()
    return [_item_row(row) for row in rows]


def review_tasks(receipt_id: str | None = None, *, open_only: bool = False) -> list[dict[str, Any]]:
    init_db()
    clauses: list[str] = []
    params: list[Any] = []
    if receipt_id:
        clauses.append("receipt_id = ?")
        params.append(receipt_id)
    if open_only:
        clauses.append("status = 'open'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM review_tasks
            {where}
            ORDER BY id ASC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def receipt_detail(receipt_id: str) -> dict[str, Any]:
    return {
        "receipt": get_receipt(receipt_id),
        "items": receipt_items(receipt_id),
        "tasks": review_tasks(receipt_id),
        "events": [
            event
            for event in recent_events(100)
            if event["receipt_id"] in {None, receipt_id}
        ],
        "stock_options": stock_code_options(),
    }


def recent_receipts(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    safe_limit = max(1, min(limit, 200))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                COUNT(DISTINCT CASE WHEN t.status = 'open' THEN t.id END)
                    AS open_task_count,
                COUNT(DISTINCT i.id) AS item_count
            FROM receipts r
            LEFT JOIN review_tasks t ON t.receipt_id = r.id
            LEFT JOIN receipt_items i ON i.receipt_id = r.id
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    data = []
    for row in rows:
        receipt = _receipt_row(row)
        receipt["open_task_count"] = row["open_task_count"]
        receipt["item_count"] = row["item_count"]
        data.append(receipt)
    return data


def review_receipts(limit: int = 50) -> list[dict[str, Any]]:
    return [
        receipt
        for receipt in recent_receipts(limit)
        if receipt["status"] in {"needs_review", "sync_failed"}
        or receipt["open_task_count"] > 0
    ]


def recent_receipt_items(limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    safe_limit = max(1, min(limit, 500))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                i.id,
                i.receipt_id,
                i.created_at,
                r.receipt_date,
                r.receipt_no,
                r.store_name,
                i.item_name,
                i.stock_code,
                i.stock_name,
                i.vat_rate,
                i.net_amount,
                i.vat_amount,
                i.total_amount,
                i.needs_review,
                i.needs_stock_review,
                i.sheet_appended,
                r.status AS receipt_status,
                r.sheet_appended_at
            FROM receipt_items i
            JOIN receipts r ON r.id = i.receipt_id
            ORDER BY i.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [_item_row(row) for row in rows]


def update_receipt_fields(receipt_id: str, values: dict[str, Any]) -> dict[str, Any]:
    values = {key: value for key, value in values.items() if value is not None}
    allowed = {
        "receipt_date": "receipt_date",
        "receipt_no": "receipt_no",
        "store_name": "store_name",
        "payment_method": "payment_method",
        "total_vat": "total_vat",
        "grand_total": "grand_total",
    }
    updates = {allowed[key]: value for key, value in values.items() if key in allowed}
    if not updates:
        return get_receipt(receipt_id)

    assignments = ", ".join(f"{column} = ?" for column in updates)
    params = list(updates.values())
    params.extend([now_iso(), receipt_id])
    with _connect() as conn:
        conn.execute(
            f"""
            UPDATE receipts
            SET {assignments}, updated_at = ?
            WHERE id = ?
            """,
            params,
        )
        for field_name in updates:
            conn.execute(
                """
                UPDATE review_tasks
                SET status = 'done', completed_at = ?
                WHERE receipt_id = ? AND item_id IS NULL AND field_name = ?
                """,
                (now_iso(), receipt_id, field_name),
            )
    _refresh_receipt_review_state(receipt_id)
    return get_receipt(receipt_id)


def recalculate_receipt_totals(receipt_id: str) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        totals = conn.execute(
            """
            SELECT
                COALESCE(SUM(vat_amount), 0) AS total_vat,
                COALESCE(SUM(total_amount), 0) AS grand_total,
                COUNT(*) AS item_count
            FROM receipt_items
            WHERE receipt_id = ?
            """,
            (receipt_id,),
        ).fetchone()
        conn.execute(
            """
            UPDATE receipts
            SET total_vat = ?,
                grand_total = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                round(float(totals["total_vat"] or 0), 2),
                round(float(totals["grand_total"] or 0), 2),
                now_iso(),
                receipt_id,
            ),
        )
        if totals["item_count"] == 0:
            conn.execute(
                """
                INSERT INTO review_tasks (
                    created_at,
                    receipt_id,
                    item_id,
                    field_name,
                    label,
                    current_value
                )
                SELECT ?, ?, NULL, 'items', 'Ürün satırları', ''
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM review_tasks
                    WHERE receipt_id = ? AND field_name = 'items' AND status = 'open'
                )
                """,
                (now_iso(), receipt_id, receipt_id),
            )
        else:
            conn.execute(
                """
                UPDATE review_tasks
                SET status = 'done', completed_at = ?
                WHERE receipt_id = ? AND field_name IN ('grand_total', 'total_vat')
                """,
                (now_iso(), receipt_id),
            )
    _refresh_receipt_review_state(receipt_id)
    return get_receipt(receipt_id)


def update_item_fields(item_id: int, values: dict[str, Any]) -> dict[str, Any]:
    values = {key: value for key, value in values.items() if value is not None}
    allowed = {
        "item_name": "item_name",
        "stock_code": "stock_code",
        "vat_rate": "vat_rate",
        "net_amount": "net_amount",
        "vat_amount": "vat_amount",
        "total_amount": "total_amount",
    }
    updates = {allowed[key]: value for key, value in values.items() if key in allowed}
    if "stock_code" in updates:
        if updates["stock_code"] not in STOK_KODLARI:
            raise ValueError("Unknown stock code")
        updates["stock_name"] = STOK_KODLARI[updates["stock_code"]]
        updates["needs_stock_review"] = 0
    if not updates:
        return get_item(item_id)

    assignments = ", ".join(f"{column} = ?" for column in updates)
    params = list(updates.values())
    params.append(item_id)
    timestamp = now_iso()
    with _connect() as conn:
        row = conn.execute(
            "SELECT receipt_id FROM receipt_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Receipt item not found")
        receipt_id = row["receipt_id"]
        conn.execute(
            f"""
            UPDATE receipt_items
            SET {assignments}
            WHERE id = ?
            """,
            params,
        )
        for field_name in updates:
            conn.execute(
                """
                UPDATE review_tasks
                SET status = 'done', completed_at = ?
                WHERE item_id = ? AND field_name = ?
                """,
                (timestamp, item_id, field_name),
            )
    _refresh_item_review_state(item_id)
    recalculate_receipt_totals(receipt_id)
    _refresh_receipt_review_state(receipt_id)
    return get_item(item_id)


def delete_item(item_id: int) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT receipt_id FROM receipt_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Receipt item not found")
        receipt_id = row["receipt_id"]
        conn.execute(
            """
            UPDATE review_tasks
            SET status = 'done', completed_at = ?
            WHERE item_id = ?
            """,
            (now_iso(), item_id),
        )
        conn.execute("DELETE FROM receipt_items WHERE id = ?", (item_id,))
    recalculate_receipt_totals(receipt_id)
    _refresh_receipt_review_state(receipt_id)
    return get_receipt(receipt_id)


def get_item(item_id: int) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM receipt_items WHERE id = ?",
            (item_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Receipt item not found")
    return _item_row(row)


def _refresh_item_review_state(item_id: int) -> None:
    with _connect() as conn:
        pending = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM review_tasks
            WHERE item_id = ? AND status = 'open'
            """,
            (item_id,),
        ).fetchone()["count"]
        conn.execute(
            """
            UPDATE receipt_items
            SET needs_review = ?,
                review_reason = CASE WHEN ? = 0 THEN NULL ELSE review_reason END
            WHERE id = ?
            """,
            (int(pending > 0), pending, item_id),
        )


def _refresh_receipt_review_state(receipt_id: str) -> None:
    with _connect() as conn:
        pending = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM review_tasks
            WHERE receipt_id = ? AND status = 'open'
            """,
            (receipt_id,),
        ).fetchone()["count"]
        current = conn.execute(
            "SELECT status FROM receipts WHERE id = ?",
            (receipt_id,),
        ).fetchone()
        if current is None:
            return
        status = current["status"]
        if pending and status != "needs_review":
            new_status = "needs_review"
        elif not pending and status == "needs_review":
            new_status = "ready_to_sync"
        else:
            return
        conn.execute(
            """
            UPDATE receipts
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, now_iso(), receipt_id),
        )


def open_tasks_count(receipt_id: str) -> int:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM review_tasks
            WHERE receipt_id = ? AND status = 'open'
            """,
            (receipt_id,),
        ).fetchone()["count"]


def rows_for_sheets(receipt_id: str) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                i.id,
                i.receipt_id,
                r.receipt_date,
                r.receipt_no,
                r.store_name,
                i.item_name,
                i.stock_code,
                i.stock_name,
                i.vat_rate,
                i.net_amount,
                i.vat_amount,
                i.total_amount
            FROM receipt_items i
            JOIN receipts r ON r.id = i.receipt_id
            WHERE i.receipt_id = ?
            ORDER BY i.sort_order ASC, i.id ASC
            """,
            (receipt_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_receipt_synced(receipt_id: str) -> dict[str, Any]:
    timestamp = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE receipts
            SET status = 'synced',
                updated_at = ?,
                sheet_appended_at = ?,
                sheet_error = NULL
            WHERE id = ?
            """,
            (timestamp, timestamp, receipt_id),
        )
        conn.execute(
            """
            UPDATE receipt_items
            SET sheet_appended = 1
            WHERE receipt_id = ?
            """,
            (receipt_id,),
        )
    return get_receipt(receipt_id)


def mark_receipt_sync_failed(receipt_id: str, error: str) -> dict[str, Any]:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE receipts
            SET status = 'sync_failed',
                updated_at = ?,
                sheet_error = ?
            WHERE id = ?
            """,
            (now_iso(), error[:1000], receipt_id),
        )
    return get_receipt(receipt_id)


def stock_code_options() -> list[dict[str, str]]:
    return [{"code": code, "name": name} for code, name in STOK_KODLARI.items()]
