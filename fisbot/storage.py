import logging
from datetime import datetime
from pathlib import Path

from fisbot.config import DATA_DIR
from fisbot.parser import ReceiptData, STOK_KODLARI

logger = logging.getLogger(__name__)


def _format_price(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def receipt_to_markdown(receipt: ReceiptData) -> str:
    """Convert a ReceiptData object to formatted Markdown."""
    lines: list[str] = []

    store = receipt.magaza_adi or "Bilinmeyen Mağaza"
    date = receipt.tarih or "Tarih yok"

    lines.append(f"# Fiş: {store} — {date}")
    lines.append("")

    lines.append(f"- **Tarih:** {date}")
    if receipt.saat:
        lines[-1] += f" {receipt.saat}"
    if receipt.fis_no:
        lines.append(f"- **Fiş No:** {receipt.fis_no}")
    lines.append(f"- **Mağaza:** {store}")
    if receipt.odeme_yontemi:
        lines.append(f"- **Ödeme:** {receipt.odeme_yontemi}")
    lines.append("")

    # Products table
    if receipt.urunler:
        lines.append("## Ürünler")
        lines.append("")
        lines.append("| Ürün | Stok | KDV % | Net | KDV | Toplam |")
        lines.append("|------|------|-------|-----|-----|--------|")
        for item in receipt.urunler:
            stok_label = STOK_KODLARI.get(item.stok, item.stok)
            lines.append(
                f"| {item.ad} "
                f"| {item.stok} ({stok_label}) "
                f"| %{item.kdv_oran} "
                f"| {_format_price(item.net)} "
                f"| {_format_price(item.kdv)} "
                f"| {_format_price(item.toplam)} |"
            )
        lines.append("")

    # Summary
    lines.append("## Özet")
    lines.append("")
    if receipt.toplam_kdv is not None:
        lines.append(f"- **Toplam KDV:** {_format_price(receipt.toplam_kdv)}")
    lines.append(f"- **Genel Toplam:** {_format_price(receipt.genel_toplam)}")
    lines.append("")

    return "\n".join(lines)


def save_receipt(receipt: ReceiptData) -> Path:
    """Save a receipt as a Markdown file and return the file path."""
    if receipt.tarih:
        try:
            dt = datetime.strptime(receipt.tarih, "%d.%m.%Y")
        except ValueError:
            dt = datetime.now()
    else:
        dt = datetime.now()

    folder = DATA_DIR / f"{dt.year}" / f"{dt.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)

    base_name = f"{dt.strftime('%Y-%m-%d')}_fis"
    if receipt.fis_no:
        safe_no = "".join(c for c in receipt.fis_no if c.isalnum() or c in "-_")
        base_name += f"_{safe_no}"

    filepath = folder / f"{base_name}.md"
    counter = 1
    while filepath.exists():
        filepath = folder / f"{base_name}_{counter}.md"
        counter += 1

    content = receipt_to_markdown(receipt)
    filepath.write_text(content, encoding="utf-8")
    logger.info("Receipt saved to %s", filepath)
    return filepath
