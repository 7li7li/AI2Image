from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services.log_service import LOG_TYPE_CALL, LogService
from services.telegram_service import format_error_log_message, send_telegram_message


class TelegramServiceTests(unittest.TestCase):
    def test_error_log_message_contains_diagnostic_context_without_payload(self) -> None:
        message = format_error_log_message(
            {
                "time": "2026-08-22 12:00:00",
                "type": LOG_TYPE_CALL,
                "summary": "channel call failed",
                "detail": {
                    "status": "error",
                    "endpoint": "/api/chat/completions",
                    "model": "gpt-5.5",
                    "channel": "Global",
                    "request_id": "req-123",
                    "user_email": "user@example.com",
                    "error": "upstream timeout",
                },
            }
        )

        self.assertIn("/api/chat/completions", message)
        self.assertIn("req-123", message)
        self.assertIn("upstream timeout", message)
        self.assertNotIn("messages", message)

    def test_send_message_uses_configured_credentials(self) -> None:
        settings = SimpleNamespace(telegram_bot_token="123:secret", telegram_chat_id="-1001")
        with (
            mock.patch("services.telegram_service._config", return_value=settings),
            mock.patch(
                "services.telegram_service._telegram_request",
                return_value={"ok": True},
            ) as request,
        ):
            result = send_telegram_message("hello")

        self.assertEqual(result, {"ok": True})
        request.assert_called_once_with(token="123:secret", chat_id="-1001", text="hello")

    def test_log_service_notifies_error_logs_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "logs.jsonl"
            service = LogService(log_path)
            fake_config = SimpleNamespace(get_repository_provider=lambda: None)
            with (
                mock.patch("services.config.config", fake_config),
                mock.patch("services.telegram_service._notifications_configured", return_value=True),
                mock.patch("services.telegram_service.notify_error_log") as notify,
            ):
                service.add(LOG_TYPE_CALL, "successful call", status="success")
                service.add(LOG_TYPE_CALL, "failed call", status="error", error="upstream failed")

            notify.assert_called_once()
            notified_item = notify.call_args.args[0]
            self.assertEqual(notified_item["summary"], "failed call")
            persisted = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(persisted), 2)


if __name__ == "__main__":
    unittest.main()
