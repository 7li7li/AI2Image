import unittest
from types import SimpleNamespace
from unittest import mock

import api.payments as payments_api


class PaymentBaseUrlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_config = SimpleNamespace(base_url="https://pay.example.com")
        patcher = mock.patch.object(payments_api, "config", self.fake_config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_prefers_configured_base_url(self) -> None:
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="http", netloc="127.0.0.1:9001"),
            headers={"host": "127.0.0.1:9001", "origin": "https://site.example.com"},
        )

        self.assertEqual(payments_api._resolve_api_base_url(request), "https://pay.example.com")

    def test_falls_back_to_forwarded_host_before_origin(self) -> None:
        self.fake_config.base_url = ""
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="http", netloc="127.0.0.1:9001"),
            headers={
                "host": "127.0.0.1:9001",
                "origin": "https://site.example.com",
                "x-forwarded-host": "api.example.com",
                "x-forwarded-proto": "https",
            },
        )

        self.assertEqual(payments_api._resolve_api_base_url(request), "https://api.example.com")

    def test_falls_back_to_browser_origin_before_internal_host(self) -> None:
        self.fake_config.base_url = ""
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="http", netloc="127.0.0.1:9001"),
            headers={"host": "127.0.0.1:9001", "origin": "https://site.example.com"},
        )

        self.assertEqual(payments_api._resolve_api_base_url(request), "https://site.example.com")

    def test_falls_back_to_browser_referer_when_origin_missing(self) -> None:
        self.fake_config.base_url = ""
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="http", netloc="127.0.0.1:9001"),
            headers={"host": "127.0.0.1:9001", "referer": "https://site.example.com/subscription"},
        )

        self.assertEqual(payments_api._resolve_api_base_url(request), "https://site.example.com")

    def test_ignores_invalid_configured_base_url(self) -> None:
        self.fake_config.base_url = "site.example.com"
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="http", netloc="127.0.0.1:9001"),
            headers={"host": "127.0.0.1:9001", "origin": "https://site.example.com"},
        )

        self.assertEqual(payments_api._resolve_api_base_url(request), "https://site.example.com")


if __name__ == "__main__":
    unittest.main()
