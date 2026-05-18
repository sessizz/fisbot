import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from fisbot.dashboard_events import publish_event
from fisbot.dashboard_events import subscribe
from fisbot.dashboard_store import (
    mark_receipt_group_appended,
    pending_stock_items,
    receipt_group_ready_for_sheet,
    recent_receipt_items,
    stock_code_options,
    update_item_stock,
)
from fisbot.sheets import append_dashboard_rows_to_sheet

app = FastAPI(title="FisBot Dashboard")


class StockSelection(BaseModel):
    stock_code: str


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

    <section class="grid gap-4 py-5 lg:grid-cols-[320px_minmax(0,1fr)]">
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

        <div class="rounded-lg border border-line bg-white p-4 shadow-sm">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-semibold">Stok secimi</h2>
            <span id="pendingCount" class="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700">0 bekliyor</span>
          </div>
          <div id="pendingEmpty" class="mt-4 rounded-md bg-zinc-50 p-3 text-sm text-zinc-500">
            Secim bekleyen fis satiri yok.
          </div>
          <div id="pendingRows" class="mt-4 space-y-3"></div>
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
          <table class="w-full table-fixed text-left text-sm">
            <thead class="bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th class="w-[112px] px-3 py-3 font-semibold">Tarih</th>
                <th class="w-[76px] px-3 py-3 font-semibold">Fis no</th>
                <th class="w-[126px] px-3 py-3 font-semibold">Stok kodu</th>
                <th class="px-3 py-3 font-semibold">Stok adi</th>
                <th class="w-[86px] px-3 py-3 font-semibold">KDV</th>
                <th class="w-[94px] px-3 py-3 text-right font-semibold">KDV tutar</th>
                <th class="w-[112px] px-3 py-3 text-right font-semibold">Toplam</th>
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
    const state = { rows: [], pending: [], stockOptions: [], events: 0, query: "" };
    const rowsEl = document.getElementById("rows");
    const emptyEl = document.getElementById("empty");
    const searchEl = document.getElementById("search");
    const eventsEl = document.getElementById("events");
    const eventCountEl = document.getElementById("eventCount");
    const rowCountEl = document.getElementById("rowCount");
    const totalAmountEl = document.getElementById("totalAmount");
    const connectionDotEl = document.getElementById("connectionDot");
    const connectionTextEl = document.getElementById("connectionText");
    const pendingRowsEl = document.getElementById("pendingRows");
    const pendingEmptyEl = document.getElementById("pendingEmpty");
    const pendingCountEl = document.getElementById("pendingCount");

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
          <td class="truncate px-3 py-3">${esc(row.receipt_date || "-")}</td>
          <td class="truncate px-3 py-3">${esc(row.receipt_no || "-")}</td>
          <td class="truncate px-3 py-3 font-mono text-xs">
            ${row.needs_stock_review ? '<span class="rounded bg-amber-100 px-2 py-1 text-amber-700">Sec</span>' : esc(row.stock_code)}
          </td>
          <td class="min-w-0 px-3 py-3">
            <div class="truncate font-medium">${esc(row.stock_name)}</div>
            <div class="mt-0.5 truncate text-xs text-zinc-500">${esc(row.item_name)}</div>
          </td>
          <td class="truncate px-3 py-3">%${esc(row.vat_rate ?? "-")}</td>
          <td class="truncate px-3 py-3 text-right">${money.format(Number(row.vat_amount || 0))}</td>
          <td class="truncate px-3 py-3 text-right font-semibold">${money.format(Number(row.total_amount || 0))}</td>
        </tr>
      `).join("");

      emptyEl.classList.toggle("hidden", filtered.length > 0);
      rowCountEl.textContent = String(state.rows.length);
      totalAmountEl.textContent = money.format(
        state.rows.reduce((sum, row) => sum + Number(row.total_amount || 0), 0)
      );
    }

    function renderPending() {
      pendingCountEl.textContent = `${state.pending.length} bekliyor`;
      pendingEmptyEl.classList.toggle("hidden", state.pending.length > 0);
      pendingRowsEl.innerHTML = state.pending.map((row) => `
        <article class="rounded-md border border-amber-200 bg-amber-50 p-3" data-pending-id="${row.id}">
          <div class="text-xs font-medium text-amber-700">${esc(row.receipt_date || "-")} · Fis ${esc(row.receipt_no || "-")}</div>
          <div class="mt-1 text-sm font-semibold">${esc(row.item_name)}</div>
          <div class="mt-1 text-xs text-zinc-600">KDV %${esc(row.vat_rate ?? "-")} · Toplam ${money.format(Number(row.total_amount || 0))}</div>
          <div class="mt-3 flex gap-2">
            <select class="min-w-0 flex-1 rounded-md border border-amber-200 bg-white px-2 py-2 text-sm outline-none ring-leaf/20 focus:ring-4">
              <option value="">Stok sec</option>
              ${state.stockOptions.map((option) => `
                <option value="${esc(option.code)}">${esc(option.code)} - ${esc(option.name)}</option>
              `).join("")}
            </select>
            <button class="rounded-md bg-leaf px-3 py-2 text-sm font-semibold text-white" type="button">Kaydet</button>
          </div>
        </article>
      `).join("");
    }

    function addPending(rows) {
      const known = new Set(state.pending.map((row) => row.id));
      const next = rows.filter((row) => row.needs_stock_review && !known.has(row.id));
      state.pending = [...next, ...state.pending];
      renderPending();
    }

    function upsertRow(row) {
      const index = state.rows.findIndex((existing) => existing.id === row.id);
      if (index === -1) {
        state.rows = [row, ...state.rows].slice(0, 250);
      } else {
        state.rows[index] = row;
      }
      renderRows();
    }

    function addRows(rows) {
      const known = new Set(state.rows.map((row) => row.id));
      const next = rows.filter((row) => !known.has(row.id));
      state.rows = [...next, ...state.rows].slice(0, 250);
      renderRows();
      addPending(rows);
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

    async function loadInitialData() {
      const [stockResponse, recentResponse, pendingResponse] = await Promise.all([
        fetch("/api/stock-codes"),
        fetch("/api/recent?limit=100"),
        fetch("/api/pending-stock?limit=50")
      ]);
      state.stockOptions = await stockResponse.json();
      addRows(await recentResponse.json());
      addPending(await pendingResponse.json());
    }

    function connectEvents() {
      const source = new EventSource("/events");
      source.addEventListener("open", () => setConnected(true));
      source.addEventListener("error", () => setConnected(false));
      source.addEventListener("message", (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "receipt_rows") {
          addRows(event.rows || []);
        } else if (event.type === "stock_review") {
          addPending(event.rows || []);
        } else if (event.type === "stock_updated") {
          upsertRow(event.row);
          state.pending = state.pending.filter((row) => row.id !== event.row.id);
          renderPending();
        } else if (event.type === "status") {
          addEvent(event);
        }
      });
    }

    searchEl.addEventListener("input", (event) => {
      state.query = event.target.value;
      renderRows();
    });

    pendingRowsEl.addEventListener("click", async (event) => {
      const button = event.target.closest("button");
      if (!button) return;

      const card = button.closest("[data-pending-id]");
      const select = card.querySelector("select");
      const stockCode = select.value;
      if (!stockCode) return;

      button.disabled = true;
      button.textContent = "Kaydediliyor";
      const response = await fetch(`/api/items/${card.dataset.pendingId}/stock`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({stock_code: stockCode})
      });

      if (!response.ok) {
        button.disabled = false;
        button.textContent = "Kaydet";
        alert("Stok kodu kaydedilemedi.");
        return;
      }

      const payload = await response.json();
      upsertRow(payload.row);
      state.pending = state.pending.filter((row) => row.id !== payload.row.id);
      renderPending();
    });

    loadInitialData();
    connectEvents();
  </script>
</body>
</html>
"""


@app.get("/api/recent")
async def api_recent(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return await asyncio.to_thread(recent_receipt_items, limit)


@app.get("/api/pending-stock")
async def api_pending_stock(
    limit: int = Query(default=50, ge=1, le=200)
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(pending_stock_items, limit)


@app.get("/api/stock-codes")
async def api_stock_codes() -> list[dict[str, str]]:
    return stock_code_options()


@app.post("/api/items/{item_id}/stock")
async def api_select_stock(item_id: int, selection: StockSelection) -> dict[str, Any]:
    try:
        row = await asyncio.to_thread(
            update_item_stock, item_id, selection.stock_code
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await publish_event({"type": "stock_updated", "row": row})

    ready_rows = await asyncio.to_thread(
        receipt_group_ready_for_sheet, row["receipt_group_id"]
    )
    if ready_rows:
        try:
            row_count = await asyncio.to_thread(append_dashboard_rows_to_sheet, ready_rows)
            await asyncio.to_thread(mark_receipt_group_appended, row["receipt_group_id"])
            await publish_event(
                {
                    "type": "status",
                    "title": "Sheets'e yazildi",
                    "message": f"{row_count} satir stok seciminden sonra eklendi.",
                }
            )
        except Exception:
            await publish_event(
                {
                    "type": "status",
                    "title": "Sheets hatasi",
                    "message": "Stok secildi ama Google Sheets'e yazilamadi.",
                }
            )

    return {"row": row}


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
