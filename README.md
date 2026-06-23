# FisBot

FisBot, Turkce perakende fislerini Telegram uzerinden okuyup yapilandirilmis muhasebe satirlarina donusturen bir bottur. Kullanici Telegram'a fis fotografi gonderir; FisBot fotografi Gemini ile analiz eder, sonucu yerel veritabanina kaydeder, gerekiyorsa web panelinde kontrol/revizyon bekletir ve tamamlanan fisleri Google Sheets'e yazar.

Bot, ayni process icinde iki arayuz calistirir:

- Telegram botu: fis fotografi alma, durum bildirme ve sonucu kullaniciya donme
- Web paneli: fisleri inceleme, stok kodu tamamlama, manuel fis girme ve Google Sheets senkronunu takip etme

## Ozellikler

- Telegram'dan fis fotografi alma
- Google Gemini ile fis okuma ve JSON'a donusturme
- Tek fotograf icinde birden fazla fis destegi
- Turkce para formatlarini okuma (`1.250,50` gibi)
- KDV oranlarini 1%, 10% ve 20% icin matematiksel olarak dogrulama
- Fis ve kalem verilerini yerel SQLite veritabaninda saklama
- Yuklenen fis gorsellerini `DATA_DIR/uploads/` altinda tutma
- Web panelinden stok kodu kontrolu ve duzeltme
- Manuel fis girisi
- Benzin modu ile ozel dagitim satirlari olusturma
- Google Sheets'e 19 kolonlu muhasebe satiri olarak yazma
- Sheets yazimi basarisiz olursa fisi kaybetmeden panelde `sync_failed` durumunda tutma
- Coolify/Docker deploy destegi

## Mimari

Temel akis:

```text
Telegram fotografi
  -> fisbot.handlers
  -> fisbot.pipeline
  -> fisbot.image_utils
  -> fisbot.gemini_client
  -> fisbot.parser
  -> fisbot.dashboard_store
  -> fisbot.sheets
  -> Telegram yaniti + web panel
```

Onemli moduller:

- `fisbot/main.py`: Telegram polling ve FastAPI web sunucusunu beraber baslatir.
- `fisbot/config.py`: Ortam degiskenlerini okur; bot, Gemini, veri dizini, web portu ve Sheets ayarlarini merkezilestirir.
- `fisbot/handlers.py`: Telegram komutlarini ve fotograf mesajlarini isler.
- `fisbot/pipeline.py`: Fis fotografi isleme hattini yonetir.
- `fisbot/gemini_client.py`: Gemini model fallback ve rate limit mantigini uygular.
- `fisbot/prompt.py`: Gemini'ye gonderilen Turkce fis okuma talimatlarini icerir.
- `fisbot/parser.py`: Gemini cevabini Pydantic modellerine donusturur ve tutarlilik kontrolleri yapar.
- `fisbot/dashboard_store.py`: SQLite veritabanini, fis durumlarini, manuel fisleri ve panel verilerini yonetir.
- `fisbot/web.py`: FastAPI uygulamasi, web paneli, manuel fis sayfasi ve JSON API endpoint'lerini icerir.
- `fisbot/sheets.py`: Google Sheets'e satir ekler.
- `fisbot/storage.py`: Markdown fis arsivi olusturur.
- `fisbot/ollama_client.py`: Yerel LLM denemeleri icin alternatif istemci; ana akisa varsayilan olarak bagli degildir.

## Gereksinimler

- Python 3.11 veya ustu
- Telegram bot tokeni
- Google Gemini API key
- Google Sheets service account bilgisi
- Hedef Google Sheet ID'si

## Kurulum

```bash
pip install -e .
```

Ardindan proje kokunde `.env` dosyasi olusturun.

```env
TELEGRAM_BOT_TOKEN=123456:telegram-token
GEMINI_API_KEY=google-gemini-api-key
GEMINI_MODELS=gemini-2.5-flash-lite,gemini-2.5-flash
ALLOWED_USERS=123456789,987654321
SPREADSHEET_ID=google-sheet-id
GOOGLE_SHEETS_CREDENTIALS_PATH=credentials.json
DATA_DIR=data
WEB_HOST=0.0.0.0
WEB_PORT=3000
```

Service account JSON dosyasi kullanmak yerine JSON icerigini dogrudan ortam degiskeni olarak da verebilirsiniz:

```env
GOOGLE_SHEETS_CREDENTIALS_JSON={"type":"service_account",...}
```

Google Sheet'in service account e-posta adresiyle paylasilmis ve duzenleme yetkisi verilmis olmasi gerekir.

## Ortam Degiskenleri

| Degisken | Aciklama |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram bot tokeni. Zorunlu. |
| `GEMINI_API_KEY` | Google Gemini API anahtari. Zorunlu. |
| `GEMINI_MODELS` | Virgulle ayrilmis Gemini model listesi. Modeller sirasiyla denenir. |
| `ALLOWED_USERS` | Virgulle ayrilmis Telegram kullanici ID'leri. Bos ise herkes kullanabilir. |
| `DATA_DIR` | SQLite veritabani, yuklenen gorseller ve yerel veriler icin ana klasor. Varsayilan `data/`. |
| `WEB_HOST` | Web panel bind host'u. Varsayilan `0.0.0.0`. |
| `WEB_PORT` / `PORT` | Web panel portu. Varsayilan `3000`. `PORT` onceliklidir. |
| `GOOGLE_SHEETS_CREDENTIALS_PATH` | Service account JSON dosya yolu. |
| `GOOGLE_SHEETS_CREDENTIALS_JSON` | Service account JSON icerigi. Varsa dosya yoluna gore onceliklidir. |
| `SPREADSHEET_ID` | Hedef Google Sheets dosyasinin ID'si. |

## Calistirma

Paket entrypoint'i ile:

```bash
fisbot
```

Modul olarak:

```bash
python -m fisbot.main
```

Basarili acilista:

- Telegram bot polling baslar.
- Web panel `http://localhost:3000` adresinden acilir.
- SQLite veritabani `DATA_DIR` altinda hazirlanir.

## Telegram Kullanimi

Telegram'da desteklenen temel komutlar:

- `/start`: Kisa tanitim ve komut listesi
- `/help`: Kullanim ozeti
- `/id`: Telegram kullanici ID'sini gosterir

Fis islemek icin bota fis fotografi gondermeniz yeterlidir. Bot once islemin basladigini bildirir, ardindan her fis icin ozet cevap doner:

- Magaza adi
- Tarih
- Fis no
- Kalem sayisi
- Toplam tutar
- Sheets senkron durumu

`ALLOWED_USERS` doluysa yalnizca listedeki kullanicilar botu kullanabilir.

## Web Panel

Web panel varsayilan olarak `http://localhost:3000` adresindedir.

Panelde:

- Islenen fisler listelenir.
- Eksik veya belirsiz stok kodlari tamamlanir.
- Fis kalemleri duzenlenir.
- Tamamlanan fisler Google Sheets'e yazilir.
- Sheets yazimi basarisiz olan fisler tekrar kontrol edilebilir.
- Manuel fis giris sayfasina gecilebilir.

Not: Web panelde ayrica bir sifre/oturum acma katmani yoktur. Production ortaminda paneli sadece guvenli agdan erisilebilir yapmaniz veya ters proxy uzerinden korumaniz onerilir.

## Manuel Fis Girisi

Manuel fis girisi `/manual` sayfasindadir.

Bu ekranda:

- Tarih, fis no, toplam KDV ve toplam tutar girilir.
- Kalem satirlari stok kodu, KDV orani ve toplam tutar ile olusturulur.
- Net ve KDV tutarlari otomatik hesaplanir.
- Girilen toplam ve KDV hedef toplamlarla karsilastirilir.
- Fis tamamlandiginda hem yerel veritabanina kaydedilir hem Google Sheets'e yazilir.

Klavye kisa yollari:

- `Alt + K`: Manuel fisi kaydet ve Google Sheets'e yaz.
- Ust bilgi alanlarinda `Enter`: Sonraki alana gec.
- Toplam tutar alaninda `Enter`: Girilen toplamdan satir olustur.
- Kalem tutari alaninda `12,50+7,50`, `20-5`, `3*4`, `100/4` gibi ifade yazip `Enter` veya `Tab`: Ifadeyi hesaplayip satira uygula.

Benzin modu aciksa sistem toplam tutari proje icindeki ozel stok kodlariyla birden fazla satira dagitir.

## Google Sheets Ciktisi

Fis kalemleri Google Sheets'e satir satir eklenir. Her kalem 19 kolonluk formatta yazilir. Ana kolonlar:

- Fis turu
- Tarih
- Fis no
- Stok kodu
- Miktar
- Net tutar
- KDV orani
- KDV tutari
- Toplam tutar

`fisbot/sheets.py` hem dogrudan parser'dan gelen fisleri hem panel/manual girisinden gelen dashboard satirlarini ayni hedef formata donusturur.

## Veri Saklama

`DATA_DIR` altinda uygulama verileri tutulur. Docker/Coolify gibi ortamlarda bu dizin persistent volume olarak baglanmalidir.

Tipik icerik:

- SQLite veritabani
- Yuklenen fis gorselleri
- Islem kayitlari
- Yerel fis arsivi

Eski Markdown fis kaydi akisi `fisbot/storage.py` icinde `data/YYYY/MM/` formatinda dosya uretebilir.

## Docker

Lokal Docker testi:

```bash
docker build -t fisbot .
docker run --rm --env-file .env -p 3000:3000 -v "$(pwd)/data:/app/data" fisbot
```

Container icinde:

- Uygulama `/app` altinda calisir.
- `DATA_DIR=/app/data` olarak ayarlanir.
- Web panel portu `3000` olarak expose edilir.

Coolify notlari icin `README_COOLIFY.md` dosyasina bakin.

## Testler

Repo `unittest` tabanli testler icerir. Calistirmak icin:

```bash
python -m unittest
```

Belirli test dosyasi:

```bash
python -m unittest tests/test_v2.py
```

## Gelistirme Notlari

- Yeni konfig degerleri icin `fisbot/config.py` tek kaynak olarak tutulmalidir.
- Google Sheets kolon sirasini degistirmeden once `fisbot/sheets.py` ve testler beraber guncellenmelidir.
- Gemini prompt degisiklikleri `fisbot/prompt.py` icinde yapilmalidir.
- Stok kodu, KDV ve tutar tutarliligi panel akisini etkiledigi icin `fisbot/dashboard_store.py` degisiklikleri test edilmelidir.
- Manuel giris UI'si `fisbot/web.py` icindeki `/manual` HTML/JavaScript blogunda yer alir.

## Sorun Giderme

`TELEGRAM_BOT_TOKEN is not set`:

- `.env` dosyasinda `TELEGRAM_BOT_TOKEN` degerini kontrol edin.

Gemini baslangic kontrolu basarisiz:

- `GEMINI_API_KEY` degerini ve model listesini kontrol edin.

Google Sheets'e yazilamiyor:

- `SPREADSHEET_ID` dogru mu kontrol edin.
- Service account JSON gecerliligini kontrol edin.
- Sheet'in service account e-posta adresiyle paylasildigindan emin olun.
- Panelde `sync_failed` durumundaki fislerin hata mesajini inceleyin.

Panel acilmiyor:

- Uygulamanin calistigini ve `WEB_PORT`/`PORT` degerini kontrol edin.
- Docker kullaniliyorsa port mapping'i (`-p 3000:3000`) dogrulayin.
