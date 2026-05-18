import asyncio
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from fisbot.config import ALLOWED_USERS
from fisbot.dashboard_events import publish_event
from fisbot.dashboard_store import add_receipt_items, mark_receipt_group_appended
from fisbot.image_utils import preprocess_image
from fisbot.gemini_client import extract_receipt, queue_position_info
from fisbot.parser import ReceiptData, STOK_KODLARI, parse_receipt_response
from fisbot.storage import save_receipt, _format_price
from fisbot.sheets import append_receipt_to_sheet

logger = logging.getLogger(__name__)


def is_user_allowed(user_id: int) -> bool:
    """Check if user is in the allowed list. Empty list means everyone is allowed."""
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def format_telegram_summary(receipt: ReceiptData) -> str:
    """Format a short summary for the Telegram reply."""
    lines: list[str] = []

    store = receipt.magaza_adi or "Bilinmeyen Mağaza"
    lines.append(f"🧾 *{store}*")

    if receipt.tarih:
        lines.append(f"📅 {receipt.tarih}")
    if receipt.fis_no:
        lines.append(f"🔢 Fiş No: {receipt.fis_no}")

    lines.append("")

    for item in receipt.urunler:
        stok_label = STOK_KODLARI.get(item.stok, item.stok)
        lines.append(
            f"  • {item.ad}\n"
            f"    {item.stok} ({stok_label})\n"
            f"    Net: {_format_price(item.net)} | "
            f"KDV %{item.kdv_oran}: {_format_price(item.kdv)} | "
            f"Toplam: {_format_price(item.toplam)}"
        )

    lines.append("")
    if receipt.toplam_kdv is not None:
        lines.append(f"🧮 Toplam KDV: {_format_price(receipt.toplam_kdv)}")
    lines.append(f"💰 *Genel Toplam: {_format_price(receipt.genel_toplam)}*")

    if receipt.odeme_yontemi:
        lines.append(f"💳 Ödeme: {receipt.odeme_yontemi}")

    return "\n".join(lines)


async def publish_status(title: str, message: str) -> None:
    await publish_event({"type": "status", "title": title, "message": message})


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if update.effective_user and not is_user_allowed(update.effective_user.id):
        return

    await update.message.reply_text(
        "Merhaba! Ben FişBot 🧾\n\n"
        "Bana alışveriş fişinin fotoğrafını gönder, "
        "ben de fişi okuyup bilgilerini çıkarayım.\n\n"
        "Komutlar:\n"
        "/start — Bu mesaj\n"
        "/help — Yardım\n"
        f"/id — Telegram kullanıcı ID'n: {update.effective_user.id}"
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if update.effective_user and not is_user_allowed(update.effective_user.id):
        return

    await update.message.reply_text(
        "📋 *FişBot Kullanım*\n\n"
        "1\\. Alışveriş fişinin fotoğrafını çek\n"
        "2\\. Fotoğrafı bu sohbete gönder\n"
        "3\\. Bot fişi okuyup bilgilerini çıkaracak\n\n"
        "⏱ İşlem birkaç saniye sürer\\.\n"
        "📁 Fişler otomatik olarak kaydedilir\\.",
        parse_mode="MarkdownV2",
    )


async def handle_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /id command — show user's Telegram ID."""
    await update.message.reply_text(
        f"Telegram ID'niz: `{update.effective_user.id}`",
        parse_mode="MarkdownV2",
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photo messages — the core receipt processing pipeline."""
    user = update.effective_user
    if user and not is_user_allowed(user.id):
        await update.message.reply_text("Bu botu kullanma yetkiniz yok.")
        return

    user_label = user.full_name if user else "Bilinmeyen kullanici"
    await publish_status("Fis geldi", f"{user_label} Telegram'dan fotograf gonderdi.")

    # Send processing indicator
    status_msg = await update.message.reply_text("⏳ Fiş işleniyor, lütfen bekleyin...")
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        # Download the highest resolution photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()

        await publish_status("Gorsel hazirlaniyor", "Fis fotografi indirildi ve isleniyor.")

        # Preprocess image
        image_bytes = preprocess_image(bytes(image_bytes))

        # Queue notification callback
        async def _on_queue(wait_seconds: float):
            await status_msg.edit_text(
                f"⏳ Sırada bekleniyor... (yaklaşık {int(wait_seconds)} saniye)"
            )

        # Check queue status and inform user
        slots, wait = queue_position_info()
        if slots == 0:
            await publish_status(
                "Sirada bekliyor",
                f"Gemini istek limiti dolu. Yaklasik {int(wait)} saniye beklenecek.",
            )
            await status_msg.edit_text(
                f"⏳ Dakikalık istek limiti doldu, sırada bekleniyor... "
                f"(yaklaşık {int(wait)} saniye)"
            )

        await publish_status("Gemini isliyor", "Fis Gemini modeline gonderildi.")

        # Send to Gemini (rate-limited, always with multi-receipt support)
        raw_response = await extract_receipt(
            image_bytes, multi=True, on_queue=_on_queue
        )

        # Update status
        await publish_status("Analiz ediliyor", "Model yaniti yapisal veriye cevriliyor.")
        await status_msg.edit_text("⏳ Fiş analiz ediliyor...")

        # Parse response
        receipts = parse_receipt_response(raw_response)

        # Save and respond for each receipt
        for receipt in receipts:
            filepath = save_receipt(receipt)
            dashboard_rows = await asyncio.to_thread(add_receipt_items, receipt)
            await publish_event({"type": "receipt_rows", "rows": dashboard_rows})
            await publish_status(
                "Fis kaydedildi",
                f"{receipt.fis_no or 'Fis no yok'} icin {len(dashboard_rows)} kalem eklendi.",
            )
            pending_stock_rows = [
                row for row in dashboard_rows if row["needs_stock_review"]
            ]
            if pending_stock_rows:
                await publish_event(
                    {"type": "stock_review", "rows": pending_stock_rows}
                )
                await publish_status(
                    "Stok secimi gerekiyor",
                    f"{len(pending_stock_rows)} satir icin panelden stok kodu secin.",
                )
                sheet_info = (
                    "⏸ Google Sheets bekliyor: panelden stok kodu seçimi gerekiyor"
                )
                summary = format_telegram_summary(receipt)
                await update.message.reply_text(
                    summary + f"\n\n✅ Kaydedildi: `{filepath.name}`\n{sheet_info}",
                    parse_mode="Markdown",
                )
                continue

            # Append to Google Sheets
            try:
                row_count = await asyncio.to_thread(append_receipt_to_sheet, receipt)
                await asyncio.to_thread(
                    mark_receipt_group_appended,
                    dashboard_rows[0]["receipt_group_id"],
                )
                sheet_info = f"📊 Google Sheets'e {row_count} satır eklendi"
            except Exception as sheets_err:
                logger.error("Google Sheets error: %s", sheets_err)
                sheet_info = "⚠️ Google Sheets'e yazılamadı"

            summary = format_telegram_summary(receipt)
            await update.message.reply_text(
                summary + f"\n\n✅ Kaydedildi: `{filepath.name}`\n{sheet_info}",
                parse_mode="Markdown",
            )

        await status_msg.delete()

    except ValueError as e:
        logger.error("Parse error: %s", e)
        await publish_status("Fis okunamadi", str(e))
        await status_msg.edit_text(
            f"❌ Fiş okunamadı: {e}\n\nLütfen daha net bir fotoğraf göndermeyi deneyin."
        )
    except Exception:
        logger.exception("Unexpected error processing receipt")
        await publish_status("Hata", "Fis islenirken beklenmeyen bir hata olustu.")
        await status_msg.edit_text(
            "❌ Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin."
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text messages."""
    if update.effective_user and not is_user_allowed(update.effective_user.id):
        return

    await update.message.reply_text(
        "Bana bir fiş fotoğrafı gönder, ben de okuyayım! 📸"
    )
