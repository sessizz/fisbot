import asyncio
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from fisbot.config import DATA_DIR
from fisbot.dashboard_events import publish_event
from fisbot.dashboard_store import (
    add_event,
    create_receipt,
    get_receipt,
    mark_receipt_sync_failed,
    mark_receipt_synced,
    open_tasks_count,
    receipt_detail,
    rows_for_sheets,
    save_receipt_extraction,
    update_receipt_status,
)
from fisbot.gemini_client import (
    extract_receipts_json,
    receipts_from_structured_payload,
    verify_receipts_json,
)
from fisbot.image_utils import preprocess_image
from fisbot.parser import ReceiptData
from fisbot.sheets import append_dashboard_rows_to_sheet

StatusCallback = Callable[[str], Awaitable[None]]


def save_upload_image(image_bytes: bytes) -> Path:
    folder = DATA_DIR / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    image_path = folder / f"{uuid4().hex}.jpg"
    image_path.write_bytes(image_bytes)
    return image_path


async def emit_status(
    title: str,
    message: str,
    *,
    receipt_id: str | None = None,
    level: str = "info",
) -> None:
    event = await asyncio.to_thread(
        add_event,
        receipt_id,
        title,
        message,
        level=level,
    )
    await publish_event({"type": "status", **event})


async def publish_receipt_update(receipt_id: str) -> None:
    detail = await asyncio.to_thread(receipt_detail, receipt_id)
    await publish_event({"type": "receipt_updated", "receipt": detail["receipt"]})
    await publish_event({"type": "receipt_detail", "detail": detail})


async def sync_receipt_if_ready(receipt_id: str) -> dict:
    receipt = await asyncio.to_thread(get_receipt, receipt_id)
    if receipt["sheet_appended_at"]:
        return receipt
    if receipt["status"] not in {"ready_to_sync", "sync_failed"}:
        return receipt
    if await asyncio.to_thread(open_tasks_count, receipt_id):
        return receipt

    rows = await asyncio.to_thread(rows_for_sheets, receipt_id)
    if not rows:
        return await asyncio.to_thread(
            mark_receipt_sync_failed, receipt_id, "No receipt rows to sync"
        )

    try:
        row_count = await asyncio.to_thread(append_dashboard_rows_to_sheet, rows)
    except Exception as exc:
        receipt = await asyncio.to_thread(mark_receipt_sync_failed, receipt_id, str(exc))
        await emit_status(
            "Sheets hatasi",
            "Google Sheets'e yazilamadi; panelden tekrar denenebilir.",
            receipt_id=receipt_id,
            level="error",
        )
        await publish_receipt_update(receipt_id)
        return receipt

    receipt = await asyncio.to_thread(mark_receipt_synced, receipt_id)
    await emit_status(
        "Sheets'e yazildi",
        f"{row_count} satir Google Sheets'e eklendi.",
        receipt_id=receipt_id,
    )
    await publish_receipt_update(receipt_id)
    return receipt


def _blank_review_receipt() -> ReceiptData:
    return ReceiptData.model_validate({})


async def process_receipt_photo(
    image_bytes: bytes,
    *,
    telegram_user_id: int | None,
    telegram_user_name: str | None,
    status_callback: StatusCallback | None = None,
) -> list[dict]:
    image_path = await asyncio.to_thread(save_upload_image, image_bytes)
    first_receipt = await asyncio.to_thread(
        create_receipt,
        image_path=image_path,
        telegram_user_id=telegram_user_id,
        telegram_user_name=telegram_user_name,
    )
    first_receipt_id = first_receipt["id"]

    await emit_status(
        "Fis geldi",
        f"{telegram_user_name or 'Bilinmeyen kullanici'} fotograf gonderdi.",
        receipt_id=first_receipt_id,
    )
    if status_callback:
        await status_callback("⏳ Fiş okunuyor...")

    try:
        ai_image_bytes = await asyncio.to_thread(preprocess_image, image_bytes)
        await asyncio.to_thread(update_receipt_status, first_receipt_id, "extracting")
        await emit_status(
            "AI okuyor",
            "Gemini structured extraction asamasi basladi.",
            receipt_id=first_receipt_id,
        )
        extraction = await extract_receipts_json(ai_image_bytes)

        await asyncio.to_thread(update_receipt_status, first_receipt_id, "verifying")
        await emit_status(
            "AI dogruluyor",
            "Gemini verification asamasi basladi.",
            receipt_id=first_receipt_id,
        )
        if status_callback:
            await status_callback("⏳ Fiş doğrulanıyor...")
        try:
            verification = await verify_receipts_json(ai_image_bytes, extraction)
        except Exception as exc:
            verification = extraction
            verification.setdefault("warnings", []).append(
                f"Verification failed, extraction used: {exc}"
            )

        parsed_receipts, warnings = receipts_from_structured_payload(verification)
        if not parsed_receipts:
            parsed_receipts = [_blank_review_receipt()]
            warnings.append("AI hic fis satiri cikaramadi")

    except Exception as exc:
        parsed_receipts = [_blank_review_receipt()]
        extraction = {"error": str(exc)}
        verification = {"error": str(exc)}
        warnings = [f"AI okuma hatasi: {exc}"]

    saved_receipts: list[dict] = []
    for index, parsed in enumerate(parsed_receipts):
        if index == 0:
            receipt_id = first_receipt_id
        else:
            receipt_record = await asyncio.to_thread(
                create_receipt,
                image_path=image_path,
                telegram_user_id=telegram_user_id,
                telegram_user_name=telegram_user_name,
            )
            receipt_id = receipt_record["id"]

        receipt = await asyncio.to_thread(
            save_receipt_extraction,
            receipt_id,
            parsed,
            raw_extraction=extraction,
            raw_verification=verification,
            warnings=warnings,
        )
        await emit_status(
            "Fis kaydedildi",
            f"{parsed.fis_no or 'Fis no yok'} durumu: {receipt['status']}.",
            receipt_id=receipt_id,
        )
        await publish_receipt_update(receipt_id)
        await publish_event(
            {
                "type": "receipt_rows",
                "rows": (await asyncio.to_thread(rows_for_sheets, receipt_id)),
            }
        )

        if receipt["status"] == "ready_to_sync":
            receipt = await sync_receipt_if_ready(receipt_id)
        elif receipt["status"] == "needs_review":
            await emit_status(
                "Review gerekiyor",
                "Eksik veya belirsiz alanlar panelde bekliyor.",
                receipt_id=receipt_id,
            )

        saved_receipts.append(receipt)

    return saved_receipts
