import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from fisbot import dashboard_store
from fisbot.parser import parse_receipt_response, parse_turkish_price


class ParserV2Tests(unittest.TestCase):
    def test_null_fields_become_review_flags(self):
        receipt = parse_receipt_response(
            """
            {
              "receipts": [{
                "tarih": null,
                "fis_no": null,
                "urunler": [{
                  "ad": null,
                  "stok": null,
                  "toplam": null,
                  "kdv": "0",
                  "net": "0"
                }],
                "genel_toplam": null
              }]
            }
            """
        )[0]

        self.assertTrue(receipt.tarih_secim_gerekli)
        self.assertTrue(receipt.fis_no_secim_gerekli)
        self.assertTrue(receipt.genel_toplam_secim_gerekli)
        self.assertTrue(receipt.urunler[0].ad_secim_gerekli)
        self.assertTrue(receipt.urunler[0].stok_secim_gerekli)
        self.assertTrue(receipt.urunler[0].toplam_secim_gerekli)

    def test_kdv_math_is_recalculated_from_total(self):
        receipt = parse_receipt_response(
            """
            {
              "urunler": [{
                "ad": "YIYECEK",
                "stok": "GY3.30.303",
                "kdv_oran": 10,
                "toplam": "110,00",
                "kdv": "0",
                "net": "0"
              }],
              "genel_toplam": "110,00"
            }
            """
        )[0]

        self.assertEqual(receipt.urunler[0].net, 100)
        self.assertEqual(receipt.urunler[0].kdv, 10)

    def test_price_parser_accepts_turkish_and_json_decimal_formats(self):
        self.assertEqual(parse_turkish_price("1.250,50"), 1250.50)
        self.assertEqual(parse_turkish_price("1250.50"), 1250.50)


class StoreV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        dashboard_store.set_db_path(Path(self.tmp.name) / "fisbot.db")
        dashboard_store.init_db()
        self.image_path = Path(self.tmp.name) / "receipt.jpg"
        self.image_path.write_bytes(b"fake")

    def tearDown(self):
        self.tmp.cleanup()

    def test_review_tasks_clear_to_ready(self):
        record = dashboard_store.create_receipt(
            image_path=self.image_path,
            telegram_user_id=1,
            telegram_user_name="Tester",
        )
        receipt = parse_receipt_response(
            """
            {
              "receipts": [{
                "tarih": null,
                "fis_no": null,
                "urunler": [{
                  "ad": null,
                  "stok": null,
                  "toplam": null,
                  "kdv": 0,
                  "net": 0
                }],
                "genel_toplam": null
              }]
            }
            """
        )[0]

        saved = dashboard_store.save_receipt_extraction(
            record["id"],
            receipt,
            raw_extraction={},
            raw_verification={},
            warnings=[],
        )
        self.assertEqual(saved["status"], "needs_review")
        detail = dashboard_store.receipt_detail(record["id"])
        self.assertGreater(len([t for t in detail["tasks"] if t["status"] == "open"]), 0)

        item_id = detail["items"][0]["id"]
        dashboard_store.update_receipt_fields(
            record["id"],
            {
                "receipt_date": "01.05.2026",
                "receipt_no": "42",
                "grand_total": 110.0,
            },
        )
        dashboard_store.update_item_fields(
            item_id,
            {
                "item_name": "YIYECEK",
                "stock_code": "GY3.30.303",
                "total_amount": 110.0,
            },
        )

        updated = dashboard_store.get_receipt(record["id"])
        self.assertEqual(updated["status"], "ready_to_sync")

    def test_item_update_and_delete_recalculate_receipt_totals(self):
        record = dashboard_store.create_receipt(
            image_path=self.image_path,
            telegram_user_id=1,
            telegram_user_name="Tester",
        )
        receipt = parse_receipt_response(
            """
            {
              "receipts": [{
                "tarih": "01.05.2026",
                "fis_no": "77",
                "urunler": [
                  {
                    "ad": "A",
                    "stok": "GY3.30.303",
                    "kdv_oran": 10,
                    "toplam": 110,
                    "kdv": 10,
                    "net": 100
                  },
                  {
                    "ad": "NOISE",
                    "stok": "GY4.49.501",
                    "kdv_oran": 20,
                    "toplam": 120,
                    "kdv": 20,
                    "net": 100
                  }
                ],
                "genel_toplam": 230
              }]
            }
            """
        )[0]
        dashboard_store.save_receipt_extraction(
            record["id"],
            receipt,
            raw_extraction={},
            raw_verification={},
            warnings=[],
        )
        detail = dashboard_store.receipt_detail(record["id"])
        first_id = detail["items"][0]["id"]
        second_id = detail["items"][1]["id"]

        dashboard_store.update_item_fields(
            first_id,
            {
                "total_amount": 220.0,
                "vat_amount": 20.0,
                "net_amount": 200.0,
            },
        )
        updated = dashboard_store.get_receipt(record["id"])
        self.assertEqual(updated["grand_total"], 340.0)
        self.assertEqual(updated["total_vat"], 40.0)

        dashboard_store.delete_item(second_id)
        updated = dashboard_store.get_receipt(record["id"])
        self.assertEqual(updated["grand_total"], 220.0)
        self.assertEqual(updated["total_vat"], 20.0)
        self.assertEqual(len(dashboard_store.receipt_items(record["id"])), 1)

    def test_create_manual_receipt(self):
        receipt = dashboard_store.create_manual_receipt(
            receipt_date="02.05.2026",
            receipt_no="M-1",
            total_vat=10.0,
            grand_total=110.0,
            items=[
                {
                    "item_name": "Manuel yemek",
                    "stock_code": "GY3.30.303",
                    "vat_rate": 10,
                    "net_amount": 100.0,
                    "vat_amount": 10.0,
                    "total_amount": 110.0,
                }
            ],
        )
        self.assertEqual(receipt["status"], "ready_to_sync")
        self.assertEqual(receipt["grand_total"], 110.0)
        self.assertEqual(dashboard_store.receipt_items(receipt["id"])[0]["stock_code"], "GY3.30.303")


class WebV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        dashboard_store.set_db_path(Path(self.tmp.name) / "fisbot.db")
        dashboard_store.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_public_dashboard_endpoints(self):
        from fisbot.web import app

        client = TestClient(app)
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/health").json(), {"status": "ok"})
        self.assertEqual(client.get("/api/recent").status_code, 200)
        self.assertEqual(client.get("/api/review").status_code, 200)

    def test_manual_page_and_api(self):
        import fisbot.web as web
        from fisbot.web import app

        async def fake_sync(receipt_id: str):
            return dashboard_store.mark_receipt_synced(receipt_id)

        original_sync = web.sync_receipt_if_ready
        web.sync_receipt_if_ready = fake_sync
        try:
            client = TestClient(app)
            manual_html = client.get("/manual").text
            self.assertIn("Fis giris", manual_html)
            self.assertIn("Satir olustur", manual_html)
            self.assertIn("formatDateInput", manual_html)
            self.assertIn("saveManualReceipt", manual_html)
            self.assertIn("event.altKey", manual_html)
            self.assertIn("receiptFieldOrder", manual_html)
            self.assertIn("fuelMode", manual_html)
            self.assertIn("67899009", manual_html)
            response = client.post(
                "/api/manual-receipts",
                json={
                    "receipt_date": "03.05.2026",
                    "receipt_no": "M-2",
                    "total_vat": 10.0,
                    "grand_total": 110.0,
                    "items": [
                        {
                            "stock_code": "GY3.30.303",
                            "vat_rate": 10,
                            "total_amount": 110.0,
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["receipt"]["status"], "synced")

            fuel_response = client.post(
                "/api/manual-receipts",
                json={
                    "receipt_date": "04.05.2026",
                    "receipt_no": "BENZIN-1",
                    "total_vat": 233.33,
                    "grand_total": 2000.0,
                    "items": [
                        {
                            "stock_code": "GY3.32.322",
                            "vat_rate": 20,
                            "total_amount": 1400.0,
                        },
                        {
                            "stock_code": "67899009",
                            "vat_rate": 0,
                            "total_amount": 500.0,
                        },
                        {
                            "stock_code": "6899008",
                            "vat_rate": 0,
                            "total_amount": 100.0,
                        },
                    ],
                },
            )
            self.assertEqual(fuel_response.status_code, 200)
            fuel_receipt = fuel_response.json()["receipt"]
            fuel_items = dashboard_store.receipt_items(fuel_receipt["id"])
            self.assertEqual(
                [item["stock_code"] for item in fuel_items],
                ["GY3.32.322", "67899009", "6899008"],
            )
            self.assertEqual([item["vat_rate"] for item in fuel_items], [20, 0, 0])
        finally:
            web.sync_receipt_if_ready = original_sync


if __name__ == "__main__":
    unittest.main()
