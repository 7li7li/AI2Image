import tempfile
import unittest
import os
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")
os.environ.setdefault("STORAGE_BACKEND", "json")

import api.support as api_support
from api.app import create_app
from fastapi.testclient import TestClient


class AppStaticTests(unittest.TestCase):
    def test_frontend_fallback_accepts_head_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            web_dist = Path(tmp_dir)
            (web_dist / "index.html").write_text("<html></html>", encoding="utf-8")

            with mock.patch.object(api_support, "WEB_DIST_DIR", web_dist):
                client = TestClient(create_app())
                response = client.head("/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "")


if __name__ == "__main__":
    unittest.main()
