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


if __name__ == "__main__":
    unittest.main()
