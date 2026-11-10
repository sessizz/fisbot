import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from fisbot import maclar


class ForwardProgramTests(unittest.TestCase):
    def _run(self, handler):
        transport = httpx.MockTransport(handler)
        with patch.object(maclar, "MACLAR_UPLOAD_URL", "https://maclar.test/api/program"),                 patch.object(maclar, "MACLAR_UPLOAD_TOKEN", "secret"):
            return asyncio.run(maclar.forward_program(b"xlsx-bytes", "11. HAFTA PROGRAM.xlsx", 42, transport=transport))

    def test_sends_file_token_and_chat_id(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers["Authorization"]
            seen["body"] = request.read()
            return httpx.Response(200, json={"ok": True, "matches": 83, "added": 39, "message": "📥 <b>ok</b>"})

        result = self._run(handler)

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "📥 <b>ok</b>")
        self.assertEqual(seen["auth"], "Bearer secret")
        self.assertIn(b'name="chat_id"', seen["body"])
        self.assertIn(b"42", seen["body"])
        self.assertIn("11. HAFTA PROGRAM.xlsx".encode(), seen["body"])
        self.assertIn(b"xlsx-bytes", seen["body"])

    def test_rejected_chat_passes_message_through(self):
        result = self._run(lambda r: httpx.Response(403, json={"ok": False, "message": "Bu sohbetten kabul edilmiyor."}))
        self.assertFalse(result.ok)
        self.assertIn("kabul edilmiyor", result.message)

    def test_wrong_token(self):
        result = self._run(lambda r: httpx.Response(401, json={"ok": False, "message": "Yetkisiz."}))
        self.assertFalse(result.ok)
        self.assertIn("MACLAR_UPLOAD_TOKEN", result.message)

    def test_unreachable(self):
        def handler(request):
            raise httpx.ConnectError("down")

        result = self._run(handler)
        self.assertFalse(result.ok)
        self.assertIn("ulaşılamadı", result.message)


if __name__ == "__main__":
    unittest.main()
