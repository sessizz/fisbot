import asyncio
import json
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from fisbot.dashboard_events import subscribe
from fisbot.dashboard_store import recent_receipt_items

app = FastAPI(title="FisBot Dashboard")


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return """
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FisBot Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            ink: "#17201b",
            leaf: "#2f6f4e",
            mint: "#dff4e8",
            paper: "#fbfaf6",
            line: "#e3e0d6"
          }
        }
      }
    }
  </script>
</head>
<body class="min-h-screen bg-paper text-ink antialiased">
  <main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-4 py-5 sm:px-6 lg:px-8">
    <header class="flex flex-col gap-4 border-b border-line pb-5 md:flex-row md:items-end md:justify-between">
      <div>
        <p class="text-sm font-medium uppercase tracking-[0.18em] text-leaf">Canli panel</p>
        <h1 class="mt-2 text-3xl font-semibold tracking-normal sm:text-4xl">FisBot</h1>
      </div>
      <div class="flex items-center gap-3">
        <span id="connectionDot" class="h-3 w-3 rounded-full bg-zinc-300"></span>
        <span id="connectionText" class="text-sm font-medium text-zinc-600">Baglaniyor</span>
      </div>
    </header>

    <section class="grid gap-4 py-5 lg:grid-cols-[360px_1fr]">
      <aside class="space-y-4">
        <div class="rounded-lg border border-line bg-white p-4 shadow-sm">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-semibold">Anlik durum</h2>
            <span id="eventCount" class="rounded-full bg-mint px-3 py-1 text-xs font-semibold text-leaf">0 olay</span>
          </div>
          <ol id="events" class="mt-4 space-y-3"></ol>
        </div>

        <div class="rounded-lg border border-line bg-white p-4 shadow-sm">
          <h2 class="text-base font-semibold">Ozet</h2>
          <dl class="mt-4 grid grid-cols-2 gap-3">
            <div class="rounded-md bg-zinc-50 p-3">
              <dt class="text-xs font-medium text-zinc-500">Kalem</dt>
              <dd id="rowCount" class="mt-1 text-2xl font-semibold">0</dd>
            </div>
            <div class="rounded-md bg-zinc-50 p-3">
              <dt class="text-xs font-medium text-zinc-500">Toplam</dt>
              <dd id="totalAmount" class="mt-1 text-2xl font-semibold">0,00</dd>
            </div>
          </dl>
        </div>
      </aside>

      <section class="min-w-0 rounded-lg border border-line bg-white shadow-sm">
        <div class="flex flex-col gap-3 border-b border-line p-4 sm:flex-row sm:items-center sm:justify-between">
          <h2 class="text-base font-semibold">Son gelen fis kalemleri</h2>
          <input
            id="search"
            type="search"
            placeholder="Ara"
            class="h-10 rounded-md border border-line bg-white px-3 text-sm outline-none ring-leaf/20 transition focus:ring-4"
          />
        </div>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[900px] text-left text-sm">
            <thead class="bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th class="px-4 py-3 font-semibold">Tarih</th>
                <th class="px-4 py-3 font-semibold">Fis no</th>
                <th class="px-4 py-3 font-semibold">Stok kodu</th>
                <th class="px-4 py-3 font-semibold">Stok adi</th>
                <th class="px-4 py-3 font-semibold">KDV orani</th>
                <th class="px-4 py-3 text-right font-semibold">KDV</th>
                <th class="px-4 py-3 text-right font-semibold">Toplam tutar</th>
              </tr>
            </thead>
            <tbody id="rows" class="divide-y divide-line"></tbody>
          </table>
        </div>
        <div id="empty" class="hidden p-10 text-center text-sm text-zinc-500">
          Henuz fis kalemi yok.
        </div>
      </section>
    </section>
  </main>

  <script>
    const state = { rows: [], events: 0, query: "" };
    const rowsEl = document.getElementById("rows");
    const emptyEl = document.getElementById("empty");
    const searchEl = document.getElementById("search");
    const eventsEl = document.getElementById("events");
    const eventCountEl = document.getElementById("eventCount");
    const rowCountEl = document.getElementById("rowCount");
    const totalAmountEl = document.getElementById("totalAmount");
    const connectionDotEl = document.getElementById("connectionDot");
    const connectionTextEl = document.getElementById("connectionText");

    const money = new Intl.NumberFormat("tr-TR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    function setConnected(connected) {
      connectionDotEl.className = `h-3 w-3 rounded-full ${connected ? "bg-emerald-500" : "bg-zinc-300"}`;
      connectionTextEl.textContent = connected ? "Canli bagli" : "Baglanti bekleniyor";
    }

    function renderRows() {
      const query = state.query.toLocaleLowerCase("tr-TR");
      const filtered = state.rows.filter((row) => {
        const text = [
          row.receipt_date,
          row.receipt_no,
          row.stock_code,
          row.stock_name,
          row.item_name,
          row.store_name
        ].join(" ").toLocaleLowerCase("tr-TR");
        return text.includes(query);
      });

      rowsEl.innerHTML = filtered.map((row) => `
        <tr class="hover:bg-mint/30">
          <td class="whitespace-nowrap px-4 py-3">${esc(row.receipt_date || "-")}</td>
          <td class="whitespace-nowrap px-4 py-3">${esc(row.receipt_no || "-")}</td>
          <td class="whitespace-nowrap px-4 py-3 font-mono text-xs">${esc(row.stock_code)}</td>
          <td class="px-4 py-3">
            <div class="font-medium">${esc(row.stock_name)}</div>
            <div class="mt-0.5 max-w-md truncate text-xs text-zinc-500">${esc(row.item_name)}</div>
          </td>
          <td class="whitespace-nowrap px-4 py-3">%${esc(row.vat_rate ?? "-")}</td>
          <td class="whitespace-nowrap px-4 py-3 text-right">${money.format(Number(row.vat_amount || 0))}</td>
          <td class="whitespace-nowrap px-4 py-3 text-right font-semibold">${money.format(Number(row.total_amount || 0))}</td>
        </tr>
      `).join("");

      emptyEl.classList.toggle("hidden", filtered.length > 0);
      rowCountEl.textContent = String(state.rows.length);
      totalAmountEl.textContent = money.format(
        state.rows.reduce((sum, row) => sum + Number(row.total_amount || 0), 0)
      );
    }

    function addRows(rows) {
      const known = new Set(state.rows.map((row) => row.id));
      const next = rows.filter((row) => !known.has(row.id));
      state.rows = [...next, ...state.rows].slice(0, 250);
      renderRows();
    }

    function addEvent(event) {
      state.events += 1;
      eventCountEl.textContent = `${state.events} olay`;
      const item = document.createElement("li");
      item.className = "rounded-md border border-line bg-zinc-50 p-3";
      item.innerHTML = `
        <div class="flex items-center justify-between gap-3">
          <p class="text-sm font-semibold">${esc(event.title || "Durum")}</p>
          <time class="shrink-0 text-xs text-zinc-500">${new Date().toLocaleTimeString("tr-TR")}</time>
        </div>
        <p class="mt-1 text-sm text-zinc-600">${esc(event.message || "")}</p>
      `;
      eventsEl.prepend(item);
      while (eventsEl.children.length > 8) {
        eventsEl.lastElementChild.remove();
      }
    }

    async function loadRecent() {
      const response = await fetch("/api/recent?limit=100");
      addRows(await response.json());
    }

    function connectEvents() {
      const source = new EventSource("/events");
      source.addEventListener("open", () => setConnected(true));
      source.addEventListener("error", () => setConnected(false));
      source.addEventListener("message", (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "receipt_rows") {
          addRows(event.rows || []);
        } else if (event.type === "status") {
          addEvent(event);
        }
      });
    }

    searchEl.addEventListener("input", (event) => {
      state.query = event.target.value;
      renderRows();
    });

    loadRecent();
    connectEvents();
  </script>
</body>
</html>
"""


@app.get("/api/recent")
async def api_recent(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return await asyncio.to_thread(recent_receipt_items, limit)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/events")
async def events() -> StreamingResponse:
    async def stream():
        async with subscribe() as queue:
            yield "event: message\ndata: {\"type\":\"status\",\"title\":\"Panel hazir\",\"message\":\"Canli baglanti kuruldu.\"}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    payload = json.dumps(event, ensure_ascii=False)
                    yield f"event: message\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
