"""Maç takvimi (maclar) uygulamasına haftalık Excel programı aktarımı.

Telegram botunu fisbot dinliyor; aynı bot token'ı iki uygulama polling ile paylaşamadığı için
maç takvimi Telegram'ı dinlemez. Bota gönderilen .xlsx dosyası buradan maç takviminin
POST /api/program adresine iletilir, dönen özet (Telegram HTML) sohbete yazılır.
"""

from dataclasses import dataclass

import httpx

from fisbot.config import MACLAR_UPLOAD_TOKEN, MACLAR_UPLOAD_URL


@dataclass
class ProgramUploadResult:
    ok: bool
    message: str


def is_configured() -> bool:
    return bool(MACLAR_UPLOAD_URL and MACLAR_UPLOAD_TOKEN)


async def forward_program(
    file_bytes: bytes,
    file_name: str,
    chat_id: int,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProgramUploadResult:
    """Excel dosyasını maç takvimine gönderir. Hata fırlatmaz; sonucu mesajla döner."""
    try:
        async with httpx.AsyncClient(timeout=120, transport=transport) as client:
            response = await client.post(
                MACLAR_UPLOAD_URL,
                headers={"Authorization": f"Bearer {MACLAR_UPLOAD_TOKEN}"},
                data={"chat_id": str(chat_id)},
                files={
                    "file": (
                        file_name,
                        file_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
    except httpx.HTTPError as exc:
        return ProgramUploadResult(False, f"⚠️ Maç takvimine ulaşılamadı: {type(exc).__name__}")

    try:
        body = response.json()
    except ValueError:
        body = {}

    message = body.get("message") if isinstance(body, dict) else None
    if response.status_code == 401:
        return ProgramUploadResult(False, "⚠️ Maç takvimi anahtarı kabul etmedi (MACLAR_UPLOAD_TOKEN).")
    if response.status_code == 404:
        return ProgramUploadResult(False, "⚠️ Maç takviminde yükleme kapalı (Program__UploadToken tanımlı değil).")
    if not message:
        return ProgramUploadResult(False, f"⚠️ Maç takvimi beklenmeyen yanıt verdi (HTTP {response.status_code}).")

    return ProgramUploadResult(bool(body.get("ok")) and response.is_success, message)
