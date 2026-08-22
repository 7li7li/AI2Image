from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.system as api_system


class TelegramSettingsApiTests(unittest.TestCase):
    def test_telegram_test_notification_requires_admin_and_sends(self) -> None:
        app = FastAPI()
        app.include_router(api_system.create_router("test-version"))

        with (
            mock.patch.object(api_system, "require_admin", return_value={"role": "admin"}) as require_admin,
            mock.patch.object(api_system, "send_telegram_test_message", return_value={"ok": True}) as send_message,
        ):
            response = TestClient(app).post(
                "/api/settings/telegram/test",
                headers={"Authorization": "Bearer admin-token"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True})
        require_admin.assert_called_once()
        send_message.assert_called_once_with()

    def test_telegram_test_notification_maps_configuration_errors(self) -> None:
        app = FastAPI()
        app.include_router(api_system.create_router("test-version"))

        with (
            mock.patch.object(api_system, "require_admin", return_value={"role": "admin"}),
            mock.patch.object(api_system, "send_telegram_test_message", side_effect=ValueError("telegram chat id is not configured")),
        ):
            response = TestClient(app).post(
                "/api/settings/telegram/test",
                headers={"Authorization": "Bearer admin-token"},
            )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("telegram chat id is not configured", response.text)


if __name__ == "__main__":
    unittest.main()
