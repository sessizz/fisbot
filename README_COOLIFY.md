# FisBot Coolify Deploy

Bu repo Coolify'da Dockerfile ile deploy edilecek şekilde paketlendi.

## Coolify ayarları

1. Coolify'da yeni bir **Application** oluşturun.
2. Kaynak olarak bu Git reposunu seçin.
3. Build Pack / Deployment Type olarak **Dockerfile** seçin.
4. Public port olarak `3000` kullanın. Bot Telegram polling ile çalışır, aynı process içinde web paneli de açar.
5. Persistent storage ekleyin:
   - Container path: `/app/data`
   - Bu klasöre fiş görselleri, SQLite veritabanı ve işlem geçmişi yazılır.

## Environment variables

Zorunlu değişkenler:

```env
TELEGRAM_BOT_TOKEN=123456:telegram-token
GEMINI_API_KEY=google-gemini-api-key
SPREADSHEET_ID=google-sheet-id
GOOGLE_SHEETS_CREDENTIALS_JSON={"type":"service_account",...}
```

Önerilen değişkenler:

```env
GEMINI_MODELS=gemini-2.5-flash-lite,gemini-2.5-flash
ALLOWED_USERS=123456789,987654321
DATA_DIR=/app/data
PORT=3000
```

`ALLOWED_USERS` boş kalırsa bot herkese açıktır. Production'da Telegram kullanıcı ID'lerini virgülle ayırarak vermek daha güvenlidir.

## Google Sheets credentials

En kolay yöntem `GOOGLE_SHEETS_CREDENTIALS_JSON` değişkenine service account JSON içeriğinin tamamını koymaktır.

Alternatif olarak JSON dosyasını Coolify volume/secret olarak mount edip şu değişkeni kullanabilirsiniz:

```env
GOOGLE_SHEETS_CREDENTIALS_PATH=/app/credentials.json
```

Service account e-posta adresine hedef Google Sheet üzerinde edit yetkisi vermeyi unutmayın.

## Local Docker test

```bash
docker build -t fisbot .
docker run --rm --env-file .env -p 3000:3000 -v "$(pwd)/data:/app/data" fisbot
```

Bot başlarken Telegram token ve Gemini API bağlantısını kontrol eder. Eksik veya hatalı secret varsa container hata vererek durur. Web paneli `http://localhost:3000` adresindedir ve şifresizdir.
