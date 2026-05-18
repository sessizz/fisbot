import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from fisbot.config import ALLOWED_USERS
from fisbot.dashboard_store import receipt_detail
from fisbot.pipeline import process_receipt_photo
from fisbot.storage import _format_price

logger = logging.getLogger(__name__)


def is_user_allowed(user_id: int) -> bool:
    """Check if user is in the allowed list. Empty list means everyone is allowed."""
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def _receipt_result_message(receipt: dict) -> str:
    detail = receipt_detail(receipt["id"])
    items = detail["items"]
    lines = []

    store = receipt.get("store_name") or "Bilinmeyen Mağaza"
    lines.append(f"🧾 {store}")
    if receipt.get("receipt_date"):
        lines.append(f"📅 {receipt['receipt_date']}")
    if receipt.get("receipt_no"):
        lines.append(f"🔢 Fiş No: {receipt['receipt_no']}")
    lines.append(f"🛒 Kalem: {len(items)}")
    lines.append(f"💰 Toplam: {_format_price(receipt.get('grand_total'))}")
    lines.append("")

    if receipt["status"] == "synced":
        lines.append("✅ Google Sheets'e yazıldı.")
    elif receipt["status"] == "needs_review":
        lines.append("⏸ Panelde kontrol bekliyor. Eksik alanları tamamlayınca Sheets'e yazılacak.")
    elif receipt["status"] == "sync_failed":
        lines.append("⚠️ Google Sheets'e yazılamadı. Panelden tekrar deneyebilirsiniz.")
    else:
        lines.append(f"ℹ️ Durum: {receipt['status']}")

    return "\n".join(lines)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and not is_user_allowed(update.effective_user.id):
        return

    await update.message.reply_text(
        "Merhaba! Ben FişBot 🧾\n\n"
        "Bana alışveriş fişinin fotoğrafını gönder, "
        "ben de fişi okuyup panelde ve Google Sheets'te işleyeyim.\n\n"
        "Komutlar:\n"
        "/start — Bu mesaj\n"
        "/help — Yardım\n"
        f"/id — Telegram kullanıcı ID'n: {update.effective_user.id}"
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and not is_user_allowed(update.effective_user.id):
        return

    await update.message.reply_text(
        "📋 *FişBot Kullanım*\n\n"
        "1\\. Fiş fotoğrafını gönder\n"
        "2\\. Bot fişi okuyup panelde canlı gösterir\n"
        "3\\. Belirsiz alan varsa panelde tamamla\n"
        "4\\. Tamamlanan fiş Google Sheets'e yazılır",
        parse_mode="MarkdownV2",
    )


async def handle_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Telegram ID'niz: `{update.effective_user.id}`",
        parse_mode="MarkdownV2",
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user and not is_user_allowed(user.id):
        await update.message.reply_text("Bu botu kullanma yetkiniz yok.")
        return

    status_msg = await update.message.reply_text("⏳ Fiş alındı, işleniyor...")
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    async def _set_status(text: str) -> None:
        await status_msg.edit_text(text)

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await file.download_as_bytearray())

        receipts = await process_receipt_photo(
            image_bytes,
            telegram_user_id=user.id if user else None,
            telegram_user_name=user.full_name if user else None,
            status_callback=_set_status,
        )

        await status_msg.delete()
        for receipt in receipts:
            await update.message.reply_text(
                _receipt_result_message(receipt)
            )

    except Exception:
        logger.exception("Unexpected error processing receipt")
        await status_msg.edit_text(
            "❌ Beklenmeyen bir hata oluştu. Fiş panelde de görünmüyorsa tekrar deneyin."
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and not is_user_allowed(update.effective_user.id):
        return

    await update.message.reply_text("Bana bir fiş fotoğrafı gönder, ben de okuyayım! 📸")
