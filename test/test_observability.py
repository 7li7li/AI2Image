from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services.log_service import LOG_TYPE_CALL, LogService
from services.observability import get_current_request_id, request_id_context
from services.storage.database_storage import DatabaseStorageBackend
from utils.timezone import china_timestamp_text


class ObservabilityTest(unittest.TestCase):
    def test_request_id_context_tracks_current_request(self) -> None:
        self.assertEqual(get_current_request_id(), "")
        with request_id_context("req-observe-1"):
            self.assertEqual(get_current_request_id(), "req-observe-1")
        self.assertEqual(get_current_request_id(), "")

    def test_server_log_time_uses_china_timezone(self) -> None:
        self.assertEqual(china_timestamp_text(0), "1970-01-01 08:00:00")

    def test_system_logs_are_persisted_and_paginated_in_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = DatabaseStorageBackend(f"sqlite:///{(Path(tmp_dir) / 'logs.db').as_posix()}")
            log_path = Path(tmp_dir) / "logs.jsonl"
            service = LogService(log_path)
            fake_config = SimpleNamespace(get_repository_provider=lambda: storage.repository_provider)

            with mock.patch("services.config.config", fake_config), request_id_context("req-log"):
                for index in range(3):
                    service.add(
                        LOG_TYPE_CALL,
                        f"call-{index}",
                        {
                            "status": "failed" if index == 1 else "success",
                            "index": index,
                            "user_id": f"user-{index}",
                            "user_name": "Alice" if index == 1 else "Bob",
                        },
                    )
                page = service.query(type=LOG_TYPE_CALL, request_id="req-log", page=1, page_size=2)
                failed_page = service.query(type=LOG_TYPE_CALL, request_id="req-log", status="failed")
                user_page = service.query(type=LOG_TYPE_CALL, request_id="req-log", user="alice")

            self.assertEqual(storage.repository_provider.system_logs.count(), 3)
            self.assertFalse(log_path.exists())
            self.assertEqual(page["total"], 3)
            self.assertEqual(page["page_count"], 2)
            self.assertEqual(len(page["items"]), 2)
            self.assertEqual(page["items"][0]["detail"]["request_id"], "req-log")
            self.assertEqual(failed_page["total"], 1)
            self.assertEqual(failed_page["items"][0]["detail"]["status"], "failed")
            self.assertEqual(user_page["total"], 1)
            self.assertEqual(user_page["items"][0]["detail"]["user_id"], "user-1")
            storage.close()

    def test_file_system_logs_can_filter_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "logs.jsonl"
            service = LogService(log_path)
            fake_config = SimpleNamespace(get_repository_provider=lambda: None)

            with mock.patch("services.config.config", fake_config):
                service.add(LOG_TYPE_CALL, "call-success", {"status": "success", "user_email": "alice@example.com"})
                service.add(LOG_TYPE_CALL, "call-failed", {"status": "failed", "user_email": "bob@example.com"})
                result = service.query(type=LOG_TYPE_CALL, status="failed")
                user_result = service.query(type=LOG_TYPE_CALL, user="alice")

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["summary"], "call-failed")
            self.assertEqual(user_result["total"], 1)
            self.assertEqual(user_result["items"][0]["summary"], "call-success")

    def test_audit_logs_have_dedicated_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = DatabaseStorageBackend(f"sqlite:///{(Path(tmp_dir) / 'audit.db').as_posix()}")
            repo = storage.repository_provider.audit_logs

            repo.add(
                {
                    "request_id": "req-audit",
                    "actor_id": "admin",
                    "actor_role": "admin",
                    "action": "users.quota.adjust",
                    "resource": "user",
                    "target_id": "user-a",
                    "detail": {"amount": 2},
                }
            )
            result = repo.query(resource="user", request_id="req-audit")
            actor_result = repo.query(user="admin")
            target_result = repo.query(user="user-a")

            self.assertEqual(repo.count(), 1)
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["action"], "users.quota.adjust")
            self.assertEqual(result["items"][0]["detail"]["amount"], 2)
            self.assertEqual(actor_result["total"], 1)
            self.assertEqual(target_result["total"], 1)
            storage.close()

    def test_request_id_links_image_records_and_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = DatabaseStorageBackend(f"sqlite:///{(Path(tmp_dir) / 'observability.db').as_posix()}")
            storage.repository_provider.image_records.insert(
                {
                    "record_id": "image-a",
                    "url": "http://127.0.0.1:8000/images/a.png",
                    "owner_user_id": "user-a",
                    "created_at": "2026-05-29 12:00:00",
                    "channel": "channel-a",
                    "request_id": "req-image",
                }
            )

            page = storage.repository_provider.image_records.query(request_id="req-image")
            health = storage.health_check()

            self.assertEqual(page["total"], 1)
            self.assertEqual(page["items"][0]["request_id"], "req-image")
            self.assertEqual(health["status"], "healthy")
            self.assertEqual(health["migration_version"], "006_decimal_quota")
            self.assertIn("006_decimal_quota", health["schema_migrations"])
            self.assertEqual(health["image_records_count"], 1)
            storage.close()


if __name__ == "__main__":
    unittest.main()
