import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from fisbot.dashboard_events import publish_event, subscribe
from fisbot.dashboard_store import (
    create_manual_receipt,
    delete_item,
    get_receipt,
    recent_events,
    recent_receipt_items,
    receipt_detail,
    review_receipts,
    stock_code_options,
    update_item_fields,
    update_receipt_fields,
)
from fisbot.pipeline import emit_status, publish_receipt_update, sync_receipt_if_ready

app = FastAPI(title="FisBot Dashboard")


class ReceiptUpdate(BaseModel):
    receipt_date: str | None = None
    receipt_no: str | None = None
    store_name: str | None = None
    payment_method: str | None = None
    total_vat: float | None = None
    grand_total: float | None = None


class ItemUpdate(BaseModel):
    item_name: str | None = None
    stock_code: str | None = None
    vat_rate: int | None = None
    net_amount: float | None = None
    vat_amount: float | None = None
    total_amount: float | None = None


class ManualItem(BaseModel):
    item_name: str | None = None
    stock_code: str
    vat_rate: int
    total_amount: float


class ManualReceiptCreate(BaseModel):
    receipt_date: str
    receipt_no: str
    total_vat: float
    grand_total: float
    items: list[ManualItem]


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
        <h1 class="mt-2 text-3xl font-semibold sm:text-4xl">FisBot</h1>
      </div>
      <div class="flex items-center gap-4">
        <a href="/manual" class="rounded-md bg-leaf px-4 py-2 text-sm font-semibold text-white">Fis giris</a>
        <div class="flex items-center gap-3">
          <span id="connectionDot" class="h-3 w-3 rounded-full bg-zinc-300"></span>
          <span id="connectionText" class="text-sm font-medium text-zinc-600">Baglaniyor</span>
        </div>
      </div>
    </header>

    <section class="grid gap-4 py-5 lg:grid-cols-[340px_minmax(0,1fr)]">
      <aside class="space-y-4">
        <section class="rounded-lg border border-line bg-white p-4 shadow-sm">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-semibold">Review bekleyenler</h2>
            <span id="reviewCount" class="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700">0</span>
          </div>
          <div id="reviewEmpty" class="mt-4 rounded-md bg-zinc-50 p-3 text-sm text-zinc-500">Bekleyen fis yok.</div>
          <div id="reviewList" class="mt-4 space-y-3"></div>
        </section>

        <section class="rounded-lg border border-line bg-white p-4 shadow-sm">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-semibold">Anlik durum</h2>
            <span id="eventCount" class="rounded-full bg-mint px-3 py-1 text-xs font-semibold text-leaf">0 olay</span>
          </div>
          <ol id="events" class="mt-4 space-y-3"></ol>
        </section>
      </aside>

      <section class="min-w-0 space-y-4">
        <section id="detailPanel" class="hidden rounded-lg border border-line bg-white shadow-sm"></section>

        <section class="rounded-lg border border-line bg-white shadow-sm">
          <div class="flex flex-col gap-3 border-b border-line p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 class="text-base font-semibold">Son gelen fis kalemleri</h2>
              <p id="summaryText" class="mt-1 text-sm text-zinc-500">0 kalem · 0,00 toplam</p>
            </div>
            <input id="search" type="search" placeholder="Ara" class="h-10 rounded-md border border-line bg-white px-3 text-sm outline-none ring-leaf/20 transition focus:ring-4" />
          </div>
          <div class="overflow-x-auto">
            <table class="w-full table-fixed text-left text-sm">
              <thead class="bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th class="w-[104px] px-3 py-3 font-semibold">Tarih</th>
                  <th class="w-[76px] px-3 py-3 font-semibold">Fis no</th>
                  <th class="w-[118px] px-3 py-3 font-semibold">Stok kodu</th>
                  <th class="px-3 py-3 font-semibold">Stok adi</th>
                  <th class="w-[78px] px-3 py-3 font-semibold">KDV</th>
                  <th class="w-[92px] px-3 py-3 text-right font-semibold">KDV tutar</th>
                  <th class="w-[108px] px-3 py-3 text-right font-semibold">Toplam</th>
                </tr>
              </thead>
              <tbody id="rows" class="divide-y divide-line"></tbody>
            </table>
          </div>
          <div id="empty" class="hidden p-10 text-center text-sm text-zinc-500">Henuz fis kalemi yok.</div>
        </section>
      </section>
    </section>
  </main>

  <script>
    const state = { rows: [], reviews: [], events: [], stockOptions: [], detail: null, query: "" };
    const money = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    const rowsEl = document.getElementById("rows");
    const emptyEl = document.getElementById("empty");
    const searchEl = document.getElementById("search");
    const summaryTextEl = document.getElementById("summaryText");
    const reviewListEl = document.getElementById("reviewList");
    const reviewEmptyEl = document.getElementById("reviewEmpty");
    const reviewCountEl = document.getElementById("reviewCount");
    const detailPanelEl = document.getElementById("detailPanel");
    const eventsEl = document.getElementById("events");
    const eventCountEl = document.getElementById("eventCount");
    const connectionDotEl = document.getElementById("connectionDot");
    const connectionTextEl = document.getElementById("connectionText");

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }

    function numberValue(value) {
      const parsed = Number(String(value ?? "").replace(",", "."));
      return Number.isFinite(parsed) ? parsed : null;
    }

    function setConnected(connected) {
      connectionDotEl.className = `h-3 w-3 rounded-full ${connected ? "bg-emerald-500" : "bg-zinc-300"}`;
      connectionTextEl.textContent = connected ? "Canli bagli" : "Baglanti bekleniyor";
    }

    function statusPill(status) {
      const classes = {
        synced: "bg-emerald-100 text-emerald-700",
        needs_review: "bg-amber-100 text-amber-700",
        sync_failed: "bg-red-100 text-red-700",
        ready_to_sync: "bg-blue-100 text-blue-700"
      };
      return `<span class="rounded-full px-2 py-1 text-xs font-semibold ${classes[status] || "bg-zinc-100 text-zinc-700"}">${esc(status)}</span>`;
    }

    function renderRows() {
      const query = state.query.toLocaleLowerCase("tr-TR");
      const filtered = state.rows.filter((row) => {
        const text = [row.receipt_date, row.receipt_no, row.stock_code, row.stock_name, row.item_name, row.store_name, row.receipt_status].join(" ").toLocaleLowerCase("tr-TR");
        return text.includes(query);
      });
      rowsEl.innerHTML = filtered.map((row) => `
        <tr class="cursor-pointer hover:bg-mint/30" data-receipt-id="${esc(row.receipt_id)}">
          <td class="truncate px-3 py-3">${esc(row.receipt_date || "-")}</td>
          <td class="truncate px-3 py-3">${esc(row.receipt_no || "-")}</td>
          <td class="truncate px-3 py-3 font-mono text-xs">${row.needs_review ? '<span class="rounded bg-amber-100 px-2 py-1 text-amber-700">Review</span>' : esc(row.stock_code)}</td>
          <td class="min-w-0 px-3 py-3">
            <div class="truncate font-medium">${esc(row.stock_name || "-")}</div>
            <div class="mt-0.5 truncate text-xs text-zinc-500">${esc(row.item_name || "-")}</div>
          </td>
          <td class="truncate px-3 py-3">%${esc(row.vat_rate ?? "-")}</td>
          <td class="truncate px-3 py-3 text-right">${money.format(Number(row.vat_amount || 0))}</td>
          <td class="truncate px-3 py-3 text-right font-semibold">${money.format(Number(row.total_amount || 0))}</td>
        </tr>
      `).join("");
      emptyEl.classList.toggle("hidden", filtered.length > 0);
      const total = state.rows.reduce((sum, row) => sum + Number(row.total_amount || 0), 0);
      summaryTextEl.textContent = `${state.rows.length} kalem · ${money.format(total)} toplam`;
    }

    function renderReviews() {
      reviewCountEl.textContent = String(state.reviews.length);
      reviewEmptyEl.classList.toggle("hidden", state.reviews.length > 0);
      reviewListEl.innerHTML = state.reviews.map((receipt) => `
        <button class="w-full rounded-md border border-amber-200 bg-amber-50 p-3 text-left hover:bg-amber-100" data-review-id="${esc(receipt.id)}">
          <div class="flex items-center justify-between gap-3">
            <span class="truncate text-sm font-semibold">${esc(receipt.store_name || "Bilinmeyen Magaza")}</span>
            ${statusPill(receipt.status)}
          </div>
          <div class="mt-1 text-xs text-zinc-600">${esc(receipt.receipt_date || "-")} · Fis ${esc(receipt.receipt_no || "-")}</div>
          <div class="mt-1 text-xs text-amber-700">${receipt.open_task_count || 0} alan bekliyor</div>
        </button>
      `).join("");
    }

    function renderEvents() {
      eventCountEl.textContent = `${state.events.length} olay`;
      eventsEl.innerHTML = state.events.slice(0, 8).map((event) => `
        <li class="rounded-md border border-line bg-zinc-50 p-3">
          <div class="flex items-center justify-between gap-3">
            <p class="truncate text-sm font-semibold">${esc(event.title)}</p>
            <time class="shrink-0 text-xs text-zinc-500">${new Date(event.created_at || Date.now()).toLocaleTimeString("tr-TR")}</time>
          </div>
          <p class="mt-1 text-sm text-zinc-600">${esc(event.message)}</p>
        </li>
      `).join("");
    }

    function stockOptions(selected) {
      return `<option value="">Sec</option>` + state.stockOptions.map((option) => `
        <option value="${esc(option.code)}" ${option.code === selected ? "selected" : ""}>${esc(option.code)} - ${esc(option.name)}</option>
      `).join("");
    }

    function renderDetail() {
      const detail = state.detail;
      if (!detail) {
        detailPanelEl.classList.add("hidden");
        return;
      }
      const receipt = detail.receipt;
      detailPanelEl.classList.remove("hidden");
      detailPanelEl.innerHTML = `
        <div class="flex flex-col gap-4 border-b border-line p-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div class="flex items-center gap-3">
              <h2 class="text-lg font-semibold">${esc(receipt.store_name || "Fis detayi")}</h2>
              ${statusPill(receipt.status)}
            </div>
            <p class="mt-1 text-sm text-zinc-500">${esc(receipt.id)}</p>
            ${receipt.sheet_error ? `<p class="mt-2 text-sm text-red-600">${esc(receipt.sheet_error)}</p>` : ""}
          </div>
          <button id="retrySync" class="rounded-md border border-line px-3 py-2 text-sm font-semibold hover:bg-zinc-50" type="button">Sheets retry</button>
        </div>
        <div class="grid gap-4 p-4 xl:grid-cols-[280px_minmax(0,1fr)]">
          <img class="max-h-[420px] w-full rounded-md border border-line object-contain" src="${esc(receipt.image_url)}" alt="Fis gorseli" />
          <div class="min-w-0 space-y-4">
            <form id="receiptForm" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              ${input("receipt_date", "Tarih", receipt.receipt_date)}
              ${input("receipt_no", "Fis no", receipt.receipt_no)}
              ${input("store_name", "Magaza", receipt.store_name)}
              ${input("grand_total", "Genel toplam", receipt.grand_total)}
              ${input("total_vat", "Toplam KDV", receipt.total_vat)}
              ${input("payment_method", "Odeme", receipt.payment_method)}
              <button class="h-10 rounded-md bg-leaf px-3 text-sm font-semibold text-white sm:col-span-2 lg:col-span-3" type="submit">Fis bilgilerini kaydet</button>
            </form>
            <div class="overflow-x-auto rounded-md border border-line">
              <table class="w-full min-w-[820px] text-left text-sm">
                <thead class="bg-zinc-50 text-xs uppercase text-zinc-500">
                  <tr>
                    <th class="px-3 py-2">Urun</th>
                    <th class="px-3 py-2">Stok</th>
                    <th class="px-3 py-2">KDV</th>
                    <th class="px-3 py-2">Net</th>
                    <th class="px-3 py-2">KDV tutar</th>
                    <th class="px-3 py-2">Toplam</th>
                    <th class="w-[128px] px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-line">
                  ${detail.items.map((item) => itemRow(item)).join("")}
                </tbody>
              </table>
            </div>
            ${detail.tasks.filter((task) => task.status === "open").length ? `
              <div class="rounded-md bg-amber-50 p-3 text-sm text-amber-800">
                ${detail.tasks.filter((task) => task.status === "open").map((task) => esc(task.label)).join(", ")} bekliyor.
              </div>
            ` : ""}
            <div class="rounded-md bg-zinc-50 p-3 text-sm text-zinc-600">
              Kalemleri kaydedince veya silince genel toplam ve toplam KDV otomatik yeniden hesaplanir.
            </div>
          </div>
        </div>
      `;
    }

    function input(name, label, value) {
      return `
        <label class="block">
          <span class="text-xs font-medium text-zinc-500">${label}</span>
          <input name="${name}" value="${esc(value ?? "")}" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm outline-none ring-leaf/20 focus:ring-4" />
        </label>
      `;
    }

    function itemRow(item) {
      return `
        <tr data-item-id="${item.id}">
          <td class="px-3 py-2"><input name="item_name" value="${esc(item.item_name || "")}" class="h-9 w-full rounded border border-line px-2" /></td>
          <td class="px-3 py-2"><select name="stock_code" class="h-9 w-full rounded border border-line px-2">${stockOptions(item.stock_code)}</select></td>
          <td class="px-3 py-2"><input name="vat_rate" value="${esc(item.vat_rate ?? "")}" class="h-9 w-20 rounded border border-line px-2" /></td>
          <td class="px-3 py-2"><input name="net_amount" value="${esc(item.net_amount ?? "")}" class="h-9 w-24 rounded border border-line px-2" /></td>
          <td class="px-3 py-2"><input name="vat_amount" value="${esc(item.vat_amount ?? "")}" class="h-9 w-24 rounded border border-line px-2" /></td>
          <td class="px-3 py-2"><input name="total_amount" value="${esc(item.total_amount ?? "")}" class="h-9 w-24 rounded border border-line px-2" /></td>
          <td class="px-3 py-2 text-right">
            <div class="flex justify-end gap-2">
              <button class="rounded-md bg-leaf px-3 py-2 text-xs font-semibold text-white" data-action="save" type="button">Kaydet</button>
              <button class="rounded-md border border-red-200 px-3 py-2 text-xs font-semibold text-red-700 hover:bg-red-50" data-action="delete" type="button">Sil</button>
            </div>
          </td>
        </tr>
      `;
    }

    async function loadInitialData() {
      const [stock, recent, reviews, events] = await Promise.all([
        fetch("/api/stock-codes"),
        fetch("/api/recent?limit=100"),
        fetch("/api/review?limit=50"),
        fetch("/api/events?limit=25")
      ]);
      state.stockOptions = await stock.json();
      state.rows = await recent.json();
      state.reviews = await reviews.json();
      state.events = await events.json();
      renderRows();
      renderReviews();
      renderEvents();
    }

    async function loadReceipt(receiptId) {
      const response = await fetch(`/api/receipts/${receiptId}`);
      state.detail = await response.json();
      renderDetail();
    }

    function upsertReceipt(receipt) {
      state.reviews = state.reviews.filter((item) => item.id !== receipt.id);
      if (["needs_review", "sync_failed"].includes(receipt.status) || Number(receipt.open_task_count || 0) > 0) {
        state.reviews = [receipt, ...state.reviews];
      }
      renderReviews();
    }

    function connectEvents() {
      const source = new EventSource("/events");
      source.addEventListener("open", () => setConnected(true));
      source.addEventListener("error", () => setConnected(false));
      source.addEventListener("message", (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "status") {
          state.events = [event, ...state.events].slice(0, 25);
          renderEvents();
        }
        if (event.type === "receipt_updated") {
          upsertReceipt(event.receipt);
          fetch("/api/recent?limit=100").then((res) => res.json()).then((rows) => {
            state.rows = rows;
            renderRows();
          });
        }
        if (event.type === "receipt_detail" && state.detail?.receipt?.id === event.detail.receipt.id) {
          state.detail = event.detail;
          renderDetail();
        }
      });
    }

    searchEl.addEventListener("input", (event) => {
      state.query = event.target.value;
      renderRows();
    });

    rowsEl.addEventListener("click", (event) => {
      const row = event.target.closest("[data-receipt-id]");
      if (row) loadReceipt(row.dataset.receiptId);
    });

    reviewListEl.addEventListener("click", (event) => {
      const card = event.target.closest("[data-review-id]");
      if (card) loadReceipt(card.dataset.reviewId);
    });

    detailPanelEl.addEventListener("submit", async (event) => {
      if (event.target.id !== "receiptForm") return;
      event.preventDefault();
      const form = new FormData(event.target);
      const body = Object.fromEntries(form.entries());
      body.grand_total = numberValue(body.grand_total);
      body.total_vat = numberValue(body.total_vat);
      const receiptId = state.detail.receipt.id;
      const response = await fetch(`/api/receipts/${receiptId}/fields`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      state.detail = await response.json();
      renderDetail();
    });

    detailPanelEl.addEventListener("click", async (event) => {
      if (event.target.id === "retrySync") {
        const receiptId = state.detail.receipt.id;
        const response = await fetch(`/api/receipts/${receiptId}/sync`, {method: "POST"});
        state.detail = await response.json();
        renderDetail();
        return;
      }
      const button = event.target.closest("tr button");
      if (!button) return;
      const row = button.closest("tr[data-item-id]");
      if (button.dataset.action === "delete") {
        const response = await fetch(`/api/items/${row.dataset.itemId}`, {method: "DELETE"});
        state.detail = await response.json();
        renderDetail();
        return;
      }
      const body = {};
      row.querySelectorAll("input, select").forEach((input) => {
        body[input.name] = input.name.endsWith("_amount") || input.name === "vat_rate"
          ? numberValue(input.value)
          : input.value;
      });
      const response = await fetch(`/api/items/${row.dataset.itemId}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      state.detail = await response.json();
      renderDetail();
    });

    loadInitialData();
    connectEvents();
  </script>
</body>
</html>
"""


@app.get("/manual", response_class=HTMLResponse)
async def manual_entry() -> str:
    return """
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FisBot Manuel Fis Giris</title>
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
  <main class="mx-auto min-h-screen w-full max-w-6xl px-4 py-5 sm:px-6 lg:px-8">
    <header class="flex flex-col gap-4 border-b border-line pb-5 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <a href="/" class="text-sm font-medium text-leaf">Ana panele don</a>
        <h1 class="mt-2 text-3xl font-semibold">Fis giris</h1>
      </div>
      <button id="saveReceipt" class="h-11 rounded-md bg-leaf px-5 text-sm font-semibold text-white" type="button">Kaydet ve Sheets'e yaz</button>
    </header>

    <section class="grid gap-4 py-5 lg:grid-cols-[minmax(0,1fr)_300px]">
      <section class="space-y-4">
        <section class="rounded-lg border border-line bg-white p-4 shadow-sm">
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 class="text-base font-semibold">Fis bilgileri</h2>
            <button id="createSummaryRow" class="rounded-md border border-line px-3 py-2 text-sm font-semibold hover:bg-zinc-50" type="button">Satir olustur</button>
          </div>
          <div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label class="block">
              <span class="text-xs font-medium text-zinc-500">Tarih</span>
              <input id="receiptDate" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm outline-none ring-leaf/20 focus:ring-4" placeholder="GG.AA.YYYY" />
            </label>
            <label class="block">
              <span class="text-xs font-medium text-zinc-500">Fis no</span>
              <input id="receiptNo" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm outline-none ring-leaf/20 focus:ring-4" />
            </label>
            <label class="block">
              <span class="text-xs font-medium text-zinc-500">Toplam KDV</span>
              <input id="targetVat" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm outline-none ring-leaf/20 focus:ring-4" inputmode="decimal" />
            </label>
            <label class="block">
              <span class="text-xs font-medium text-zinc-500">Toplam tutar</span>
              <input id="targetTotal" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm outline-none ring-leaf/20 focus:ring-4" inputmode="decimal" />
            </label>
          </div>
        </section>

        <section class="rounded-lg border border-line bg-white shadow-sm">
          <div class="flex items-center justify-between border-b border-line p-4">
            <h2 class="text-base font-semibold">Kalemler</h2>
            <button id="addRow" class="rounded-md border border-line px-3 py-2 text-sm font-semibold hover:bg-zinc-50" type="button">Satir ekle</button>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full min-w-[880px] text-left text-sm">
              <thead class="bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th class="px-3 py-3">Aciklama</th>
                  <th class="px-3 py-3">Stok</th>
                  <th class="px-3 py-3">KDV %</th>
                  <th class="px-3 py-3 text-right">Toplam</th>
                  <th class="px-3 py-3 text-right">Net</th>
                  <th class="px-3 py-3 text-right">KDV</th>
                  <th class="px-3 py-3"></th>
                </tr>
              </thead>
              <tbody id="manualRows" class="divide-y divide-line"></tbody>
            </table>
          </div>
        </section>
      </section>

      <aside class="space-y-4">
        <section class="rounded-lg border border-line bg-white p-4 shadow-sm">
          <h2 class="text-base font-semibold">Kontrol</h2>
          <dl class="mt-4 space-y-3 text-sm">
            <div class="flex justify-between gap-3"><dt class="text-zinc-500">Girilen toplam</dt><dd id="enteredTotal" class="font-semibold">0,00</dd></div>
            <div class="flex justify-between gap-3"><dt class="text-zinc-500">Kalan toplam</dt><dd id="remainingTotal" class="font-semibold">0,00</dd></div>
            <div class="flex justify-between gap-3"><dt class="text-zinc-500">Girilen KDV</dt><dd id="enteredVat" class="font-semibold">0,00</dd></div>
            <div class="flex justify-between gap-3"><dt class="text-zinc-500">Kalan KDV</dt><dd id="remainingVat" class="font-semibold">0,00</dd></div>
          </dl>
          <div id="readyBox" class="mt-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800">Fis henuz tamamlanmadi.</div>
        </section>
        <section id="resultBox" class="hidden rounded-lg border border-line bg-white p-4 text-sm shadow-sm"></section>
      </aside>
    </section>
  </main>

  <script>
    const state = { stockOptions: [], rows: [] };
    const money = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const rowsEl = document.getElementById("manualRows");
    const fields = {
      receiptDate: document.getElementById("receiptDate"),
      receiptNo: document.getElementById("receiptNo"),
      targetVat: document.getElementById("targetVat"),
      targetTotal: document.getElementById("targetTotal")
    };

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }

    function numberValue(value) {
      const clean = String(value ?? "").trim().split(".").join("").replace(",", ".");
      const parsed = Number(clean);
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function fmt(value) {
      return money.format(Number(value || 0));
    }

    function formatDateInput(value) {
      const digits = String(value ?? "").split("").filter((char) => char >= "0" && char <= "9").join("");
      if (digits.length !== 8) return value;
      return `${digits.slice(0, 2)}.${digits.slice(2, 4)}.${digits.slice(4)}`;
    }

    function guessVatRate(total, vat) {
      const net = total - vat;
      if (net <= 0 || vat <= 0) return 10;
      const actual = Math.round((vat / net) * 100);
      return [1, 10, 20].reduce((best, rate) =>
        Math.abs(rate - actual) < Math.abs(best - actual) ? rate : best
      , 10);
    }

    function calcLine(row) {
      const total = numberValue(row.total_amount);
      const rate = Number(row.vat_rate || 0);
      const net = rate > 0 ? total / (1 + rate / 100) : total;
      const vat = total - net;
      return {
        net_amount: Math.round(net * 100) / 100,
        vat_amount: Math.round(vat * 100) / 100,
        total_amount: Math.round(total * 100) / 100
      };
    }

    function stockOptions(selected) {
      return `<option value="">Stok sec</option>` + state.stockOptions.map((option) => `
        <option value="${esc(option.code)}" ${option.code === selected ? "selected" : ""}>${esc(option.code)} - ${esc(option.name)}</option>
      `).join("");
    }

    function addRow(row = {}) {
      state.rows.push({
        id: crypto.randomUUID(),
        item_name: row.item_name || "",
        stock_code: row.stock_code || "",
        vat_rate: row.vat_rate ?? 10,
        total_amount: row.total_amount || ""
      });
      render();
    }

    function render() {
      rowsEl.innerHTML = state.rows.map((row) => {
        const calc = calcLine(row);
        return `
          <tr data-row-id="${row.id}">
            <td class="px-3 py-3"><input name="item_name" value="${esc(row.item_name)}" class="h-10 w-full rounded-md border border-line px-2 text-sm" placeholder="Opsiyonel" /></td>
            <td class="px-3 py-3"><select name="stock_code" class="h-10 w-full rounded-md border border-line px-2 text-sm">${stockOptions(row.stock_code)}</select></td>
            <td class="px-3 py-3">
              <select name="vat_rate" class="h-10 w-24 rounded-md border border-line px-2 text-sm">
                ${[1,10,20].map((rate) => `<option value="${rate}" ${Number(row.vat_rate) === rate ? "selected" : ""}>%${rate}</option>`).join("")}
              </select>
            </td>
            <td class="px-3 py-3 text-right"><input name="total_amount" value="${esc(row.total_amount)}" class="h-10 w-28 rounded-md border border-line px-2 text-right text-sm" inputmode="decimal" /></td>
            <td class="px-3 py-3 text-right font-medium">${fmt(calc.net_amount)}</td>
            <td class="px-3 py-3 text-right font-medium">${fmt(calc.vat_amount)}</td>
            <td class="px-3 py-3 text-right"><button class="rounded-md border border-red-200 px-3 py-2 text-xs font-semibold text-red-700 hover:bg-red-50" type="button">Sil</button></td>
          </tr>
        `;
      }).join("");
      renderSummary();
    }

    function renderSummary() {
      const targetTotal = numberValue(fields.targetTotal.value);
      const targetVat = numberValue(fields.targetVat.value);
      const totals = state.rows.reduce((acc, row) => {
        const calc = calcLine(row);
        acc.total += calc.total_amount;
        acc.vat += calc.vat_amount;
        return acc;
      }, {total: 0, vat: 0});
      const remainingTotal = Math.round((targetTotal - totals.total) * 100) / 100;
      const remainingVat = Math.round((targetVat - totals.vat) * 100) / 100;
      document.getElementById("enteredTotal").textContent = fmt(totals.total);
      document.getElementById("enteredVat").textContent = fmt(totals.vat);
      document.getElementById("remainingTotal").textContent = fmt(remainingTotal);
      document.getElementById("remainingVat").textContent = fmt(remainingVat);
      const ready = isReady();
      const readyBox = document.getElementById("readyBox");
      readyBox.className = `mt-4 rounded-md p-3 text-sm ${ready ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"}`;
      readyBox.textContent = ready ? "Fis tamam. Kaydedebilirsiniz." : "Fis henuz tamamlanmadi.";
    }

    function isReady() {
      const targetTotal = numberValue(fields.targetTotal.value);
      const targetVat = numberValue(fields.targetVat.value);
      const totals = state.rows.reduce((acc, row) => {
        const calc = calcLine(row);
        acc.total += calc.total_amount;
        acc.vat += calc.vat_amount;
        return acc;
      }, {total: 0, vat: 0});
      return fields.receiptDate.value.trim()
        && fields.receiptNo.value.trim()
        && targetTotal > 0
        && state.rows.length > 0
        && state.rows.every((row) => row.stock_code && numberValue(row.total_amount) > 0)
        && Math.abs(targetTotal - totals.total) < 0.05
        && Math.abs(targetVat - totals.vat) < 0.05;
    }

    function resetManualForm() {
      Object.values(fields).forEach((field) => {
        field.value = "";
      });
      state.rows = [];
      addRow();
      fields.receiptDate.focus();
    }

    rowsEl.addEventListener("input", (event) => {
      const rowEl = event.target.closest("tr[data-row-id]");
      const row = state.rows.find((item) => item.id === rowEl.dataset.rowId);
      row[event.target.name] = event.target.value;
      renderSummary();
    });
    rowsEl.addEventListener("change", (event) => {
      const rowEl = event.target.closest("tr[data-row-id]");
      const row = state.rows.find((item) => item.id === rowEl.dataset.rowId);
      row[event.target.name] = event.target.value;
      render();
    });
    rowsEl.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      const rowEl = button.closest("tr[data-row-id]");
      state.rows = state.rows.filter((row) => row.id !== rowEl.dataset.rowId);
      render();
    });
    Object.values(fields).forEach((field) => field.addEventListener("input", renderSummary));
    fields.receiptDate.addEventListener("blur", () => {
      fields.receiptDate.value = formatDateInput(fields.receiptDate.value);
      renderSummary();
    });
    document.getElementById("addRow").addEventListener("click", () => addRow());
    document.getElementById("createSummaryRow").addEventListener("click", () => {
      fields.receiptDate.value = formatDateInput(fields.receiptDate.value);
      const total = numberValue(fields.targetTotal.value);
      const vat = numberValue(fields.targetVat.value);
      if (total <= 0) {
        alert("Önce toplam tutarı girin.");
        return;
      }
      state.rows = [];
      addRow({
        item_name: "Fiş toplamı",
        vat_rate: guessVatRate(total, vat),
        total_amount: fields.targetTotal.value
      });
    });
    document.getElementById("saveReceipt").addEventListener("click", async () => {
      fields.receiptDate.value = formatDateInput(fields.receiptDate.value);
      if (!isReady()) {
        alert("Fis toplamları ve kalemler tamamlanmadan kaydedilemez.");
        return;
      }
      const items = state.rows.map((row) => ({...row, ...calcLine(row), vat_rate: Number(row.vat_rate)}));
      const response = await fetch("/api/manual-receipts", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          receipt_date: fields.receiptDate.value.trim(),
          receipt_no: fields.receiptNo.value.trim(),
          total_vat: numberValue(fields.targetVat.value),
          grand_total: numberValue(fields.targetTotal.value),
          items
        })
      });
      const resultBox = document.getElementById("resultBox");
      resultBox.classList.remove("hidden");
      if (!response.ok) {
        resultBox.className = "rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 shadow-sm";
        resultBox.textContent = "Kayit basarisiz.";
        return;
      }
      const detail = await response.json();
      resultBox.className = "rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 shadow-sm";
      resultBox.innerHTML = `Kaydedildi ve Sheets'e gonderildi. <a class="font-semibold underline" href="/#${detail.receipt.id}">Panelde ac</a>`;
      resetManualForm();
    });

    async function boot() {
      const stockResponse = await fetch("/api/stock-codes");
      state.stockOptions = await stockResponse.json();
      addRow();
    }
    boot();
  </script>
</body>
</html>
"""


@app.get("/api/recent")
async def api_recent(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return await asyncio.to_thread(recent_receipt_items, limit)


@app.get("/api/review")
async def api_review(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return await asyncio.to_thread(review_receipts, limit)


@app.get("/api/events")
async def api_events(limit: int = Query(default=25, ge=1, le=100)) -> list[dict[str, Any]]:
    return await asyncio.to_thread(recent_events, limit)


@app.get("/api/stock-codes")
async def api_stock_codes() -> list[dict[str, str]]:
    return stock_code_options()


@app.post("/api/manual-receipts")
async def api_create_manual_receipt(payload: ManualReceiptCreate) -> dict[str, Any]:
    stock_codes = {option["code"] for option in stock_code_options()}
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    normalized_items: list[dict[str, Any]] = []
    total = 0.0
    total_vat = 0.0
    for item in payload.items:
        if item.stock_code not in stock_codes:
            raise HTTPException(status_code=400, detail="Unknown stock code")
        if item.vat_rate not in {1, 10, 20}:
            raise HTTPException(status_code=400, detail="Invalid VAT rate")
        if item.total_amount <= 0:
            raise HTTPException(status_code=400, detail="Item total must be positive")
        net_amount = item.total_amount / (1 + item.vat_rate / 100)
        vat_amount = item.total_amount - net_amount
        normalized = {
            "item_name": item.item_name,
            "stock_code": item.stock_code,
            "vat_rate": item.vat_rate,
            "net_amount": round(net_amount, 2),
            "vat_amount": round(vat_amount, 2),
            "total_amount": round(item.total_amount, 2),
        }
        normalized_items.append(normalized)
        total += normalized["total_amount"]
        total_vat += normalized["vat_amount"]

    if abs(round(total, 2) - round(payload.grand_total, 2)) >= 0.05:
        raise HTTPException(status_code=400, detail="Grand total does not match items")
    if abs(round(total_vat, 2) - round(payload.total_vat, 2)) >= 0.05:
        raise HTTPException(status_code=400, detail="VAT total does not match items")

    receipt = await asyncio.to_thread(
        create_manual_receipt,
        receipt_date=payload.receipt_date,
        receipt_no=payload.receipt_no,
        total_vat=round(payload.total_vat, 2),
        grand_total=round(payload.grand_total, 2),
        items=normalized_items,
    )
    await emit_status(
        "Manuel fis kaydedildi",
        f"{len(normalized_items)} kalem girildi.",
        receipt_id=receipt["id"],
    )
    await sync_receipt_if_ready(receipt["id"])
    await publish_receipt_update(receipt["id"])
    return await asyncio.to_thread(receipt_detail, receipt["id"])


@app.get("/api/receipts/{receipt_id}")
async def api_receipt(receipt_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(receipt_detail, receipt_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/receipts/{receipt_id}/image")
async def api_receipt_image(receipt_id: str) -> FileResponse:
    try:
        receipt = await asyncio.to_thread(get_receipt, receipt_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    image_path = Path(receipt["image_path"])
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image_path)


@app.post("/api/receipts/{receipt_id}/fields")
async def api_update_receipt(receipt_id: str, update: ReceiptUpdate) -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            update_receipt_fields,
            receipt_id,
            update.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await sync_receipt_if_ready(receipt_id)
    await emit_status("Fis guncellendi", "Fis ust bilgileri kaydedildi.", receipt_id=receipt_id)
    await publish_receipt_update(receipt_id)
    return await asyncio.to_thread(receipt_detail, receipt_id)


@app.post("/api/items/{item_id}")
async def api_update_item(item_id: int, update: ItemUpdate) -> dict[str, Any]:
    try:
        row = await asyncio.to_thread(
            update_item_fields,
            item_id,
            update.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await sync_receipt_if_ready(row["receipt_id"])
    await emit_status("Kalem guncellendi", "Fis kalemi kaydedildi.", receipt_id=row["receipt_id"])
    await publish_receipt_update(row["receipt_id"])
    return await asyncio.to_thread(receipt_detail, row["receipt_id"])


@app.delete("/api/items/{item_id}")
async def api_delete_item(item_id: int) -> dict[str, Any]:
    try:
        receipt = await asyncio.to_thread(delete_item, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await sync_receipt_if_ready(receipt["id"])
    await emit_status(
        "Kalem silindi",
        "Fis toplamlari yeniden hesaplandi.",
        receipt_id=receipt["id"],
    )
    await publish_receipt_update(receipt["id"])
    return await asyncio.to_thread(receipt_detail, receipt["id"])


@app.post("/api/items/{item_id}/stock")
async def api_select_stock(item_id: int, selection: dict[str, str]) -> dict[str, Any]:
    try:
        row = await asyncio.to_thread(
            update_item_fields,
            item_id,
            {"stock_code": selection.get("stock_code")},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await sync_receipt_if_ready(row["receipt_id"])
    await publish_receipt_update(row["receipt_id"])
    return {"row": row}


@app.post("/api/receipts/{receipt_id}/sync")
async def api_retry_sync(receipt_id: str) -> dict[str, Any]:
    try:
        await sync_receipt_if_ready(receipt_id)
        await publish_receipt_update(receipt_id)
        return await asyncio.to_thread(receipt_detail, receipt_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
