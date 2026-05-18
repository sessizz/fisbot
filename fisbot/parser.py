import json
import logging
import re

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

DEFAULT_STOK_KODU = "GY3.31.318"
DEFAULT_URUN_ADI = "Ürün adı okunamadı"

STOK_KODLARI = {
    "GY3.30.303": "Gıda/İçecek",
    "GÜ03": "Bakım/Onarım",
    "HZ0.06.069.692": "Temizlik",
    "GY3.39.300": "Kırtasiye",
    "GY1.15.150": "İlaç/Tedavi",
    "GY3.32.322": "Araç/Yakıt",
    "67899009": "Benzin KDV harici",
    "6899008": "Benzin kalan",
    "GY1.13.138": "Giyim",
    "GY4.49.501": "KKEG",
}


VALID_KDV_RATES = [1, 10, 20]


def _guess_kdv_rate(toplam: float, kdv: float, net: float) -> int:
    """Guess KDV rate from available amounts. Returns closest valid rate."""
    for rate in VALID_KDV_RATES:
        expected_net = toplam / (1 + rate / 100)
        expected_kdv = toplam - expected_net
        if abs(kdv - expected_kdv) < 0.05 or abs(net - expected_net) < 0.05:
            return rate
    # Fallback: calculate from kdv/net ratio
    if net > 0 and kdv > 0:
        ratio = round(kdv / net * 100)
        closest = min(VALID_KDV_RATES, key=lambda r: abs(r - ratio))
        return closest
    return 10  # default


class ReceiptItem(BaseModel):
    ad: str
    stok: str = DEFAULT_STOK_KODU
    ad_secim_gerekli: bool = False
    stok_secim_gerekli: bool = False
    toplam_secim_gerekli: bool = False
    kdv_oran: int | None = None
    toplam: float = 0.0
    kdv: float = 0.0
    net: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def mark_missing_stok(cls, data: object) -> object:
        if isinstance(data, dict):
            missing: dict[str, bool] = {}
            ad = data.get("ad")
            if ad is None or (isinstance(ad, str) and not ad.strip()):
                missing["ad_secim_gerekli"] = True
            stok = data.get("stok")
            if stok is None or (isinstance(stok, str) and not stok.strip()):
                missing["stok_secim_gerekli"] = True
            elif isinstance(stok, str) and stok.strip() not in STOK_KODLARI:
                missing["stok_secim_gerekli"] = True
            toplam = data.get("toplam")
            if toplam is None or (isinstance(toplam, str) and not toplam.strip()):
                missing["toplam_secim_gerekli"] = True
            if missing:
                data = {**data, **missing}
        return data

    @field_validator("ad", mode="before")
    @classmethod
    def parse_ad(cls, v: object) -> str:
        if v is None:
            return DEFAULT_URUN_ADI
        if isinstance(v, str):
            ad = v.strip()
            return ad or DEFAULT_URUN_ADI
        return str(v)

    @field_validator("stok", mode="before")
    @classmethod
    def parse_stok(cls, v: object) -> str:
        if v is None:
            return DEFAULT_STOK_KODU
        if isinstance(v, str):
            stok = v.strip()
            return stok or DEFAULT_STOK_KODU
        return str(v)

    @field_validator("kdv_oran", mode="before")
    @classmethod
    def parse_kdv_oran(cls, v: object) -> int | None:
        if v is None:
            return None
        return int(v)

    @field_validator("toplam", "kdv", "net", mode="before")
    @classmethod
    def parse_price(cls, v: object) -> float:
        if isinstance(v, str):
            return parse_turkish_price(v)
        return float(v) if v is not None else 0.0

    @model_validator(mode="after")
    def verify_kdv_math(self):
        """Fix KDV rate if null, then recalculate net and kdv from toplam."""
        # Guess KDV rate if missing
        if self.kdv_oran is None:
            self.kdv_oran = _guess_kdv_rate(self.toplam, self.kdv, self.net)

        if self.toplam > 0:
            expected_net = self.toplam / (1 + self.kdv_oran / 100)
            expected_kdv = self.toplam - expected_net
            if abs(self.net - expected_net) > 0.02 or abs(self.kdv - expected_kdv) > 0.02:
                self.net = round(expected_net, 2)
                self.kdv = round(expected_kdv, 2)
        return self


class ReceiptData(BaseModel):
    tarih: str | None = None
    fis_no: str | None = None
    urunler: list[ReceiptItem] = Field(default_factory=list)
    tarih_secim_gerekli: bool = False
    fis_no_secim_gerekli: bool = False
    genel_toplam_secim_gerekli: bool = False

    # Extra fields — accepted from JSON but not required
    magaza_adi: str | None = None
    saat: str | None = None
    toplam_kdv: float | None = None
    genel_toplam: float = 0.0
    odeme_yontemi: str | None = None

    @model_validator(mode="before")
    @classmethod
    def mark_missing_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            missing: dict[str, bool] = {}
            tarih = data.get("tarih")
            if tarih is None or (isinstance(tarih, str) and not tarih.strip()):
                missing["tarih_secim_gerekli"] = True
            fis_no = data.get("fis_no")
            if fis_no is None or (isinstance(fis_no, str) and not fis_no.strip()):
                missing["fis_no_secim_gerekli"] = True
            genel_toplam = data.get("genel_toplam")
            if genel_toplam is None or (
                isinstance(genel_toplam, str) and not genel_toplam.strip()
            ):
                missing["genel_toplam_secim_gerekli"] = True
            if missing:
                data = {**data, **missing}
        return data

    @field_validator("tarih", "fis_no", "magaza_adi", "saat", "odeme_yontemi", mode="before")
    @classmethod
    def parse_optional_text(cls, v: object) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        return text or None

    @field_validator("toplam_kdv", mode="before")
    @classmethod
    def parse_optional_total(cls, v: object) -> float | None:
        if v is None:
            return None
        if isinstance(v, str):
            return parse_turkish_price(v)
        return float(v)

    @field_validator("genel_toplam", mode="before")
    @classmethod
    def parse_grand_total(cls, v: object) -> float:
        if v is None:
            return 0.0
        if isinstance(v, str):
            return parse_turkish_price(v)
        return float(v)


def parse_turkish_price(text: str) -> float:
    """Parse Turkish formatted price string to float.

    Turkish format: 1.250,50 → 1250.50
    """
    text = text.strip().replace(" ", "").replace("TL", "").replace("₺", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "." in text:
        parts = text.split(".")
        if len(parts) > 2 or len(parts[-1]) == 3:
            text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def extract_json_from_text(text: str) -> str:
    """Extract JSON from model response, stripping markdown fences or extra text."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    # Find the first occurrence of [ and {
    # If [ comes before { (or at same position), it's an array — parse that
    # Otherwise parse the object
    bracket_pos = text.find("[")
    brace_pos = text.find("{")
    if bracket_pos != -1 and (brace_pos == -1 or bracket_pos <= brace_pos):
        order = [("[", "]"), ("{", "}")]
    else:
        order = [("{", "}"), ("[", "]")]
    for start_char, end_char in order:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text


def parse_receipt_response(raw_text: str) -> list[ReceiptData]:
    """Parse model's raw text response into ReceiptData objects."""
    json_str = extract_json_from_text(raw_text)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON: %s\nRaw text: %s", e, raw_text[:500])
        raise ValueError(f"Model returned invalid JSON: {e}") from e

    if isinstance(data, dict) and isinstance(data.get("receipts"), list):
        return [ReceiptData.model_validate(item) for item in data["receipts"]]
    if isinstance(data, dict) and isinstance(data.get("receipt"), dict):
        return [ReceiptData.model_validate(data["receipt"])]
    if isinstance(data, list):
        return [ReceiptData.model_validate(item) for item in data]
    return [ReceiptData.model_validate(data)]
