from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.repositories.base import RepositoryValidationError
from services.storage.database_storage import DatabaseStorageBackend


class RepositoryDatabaseStorageTest(unittest.TestCase):
    def test_database_storage_persists_all_datasets_and_index_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "storage.db"
            storage = DatabaseStorageBackend(f"sqlite:///{db_path.as_posix()}")

            storage.save_auth_keys([{"id": "key-a", "key_hash": "hash-a", "role": "admin", "enabled": True}])
            storage.save_users([{"id": "user-a", "email": "user@example.com", "role": "user", "status": "active", "quota": 5, "quota_used": 1}])
            storage.save_sessions([{"id": "session-a", "token_hash": "token-hash-a", "user_id": "user-a", "expires_at": "2026-06-01T00:00:00+00:00"}])
            storage.save_redeem_codes([{"id": "code-a", "code": "YAI-CODEA", "status": "enabled", "used_count": 0, "max_uses": 1}])
            storage.save_channels([{"id": "channel-a", "enabled": True, "priority": 10, "weight": 2}])
            storage.save_prompt_library([{"id": "prompt-a", "title": "A", "prompt": "Prompt", "category": "quick", "quick_access": True}])
            storage.save_image_records([{"id": "image-a", "owner_user_id": "user-a", "created_at": "2026-05-28 12:00:00", "channel": "channel-a"}])

            self.assertEqual(storage.load_auth_keys()[0]["id"], "key-a")
            self.assertEqual(storage.load_users()[0]["email"], "user@example.com")
            self.assertEqual(storage.load_sessions()[0]["token_hash"], "token-hash-a")
            self.assertEqual(storage.load_redeem_codes()[0]["code"], "YAI-CODEA")
            self.assertEqual(storage.load_channels()[0]["id"], "channel-a")
            self.assertEqual(storage.load_prompt_library()[0]["id"], "prompt-a")
            self.assertEqual(storage.load_image_records()[0]["id"], "image-a")
            storage.repository_provider.image_records.insert(
                {
                    "record_id": "image-b",
                    "url": "http://127.0.0.1:8000/images/2026/05/29/b.png",
                    "owner_user_id": "user-a",
                    "created_at": "2026-05-29 12:00:00",
                    "channel": "external",
                }
            )
            page = storage.repository_provider.image_records.query(
                owner_user_id="user-a",
                start_date="2026-05-28",
                end_date="2026-05-29",
                page=1,
                page_size=1,
            )
            self.assertEqual(page["total"], 2)
            self.assertEqual(page["page_count"], 2)
            self.assertEqual(page["items"][0]["record_id"], "image-b")

            health = storage.health_check()
            self.assertEqual(health["status"], "healthy")
            self.assertEqual(health["users_count"], 1)
            self.assertEqual(health["channels_count"], 1)
            self.assertEqual(health["image_records_count"], 2)

            with storage.engine.connect() as connection:
                row = connection.exec_driver_sql(
                    "SELECT key_id, role, enabled FROM auth_keys"
                ).mappings().one()
                self.assertEqual(row["key_id"], "key-a")
                self.assertEqual(row["role"], "admin")
                self.assertTrue(row["enabled"])
            storage.close()

    def test_duplicate_keys_are_reported_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "storage.db"
            storage = DatabaseStorageBackend(f"sqlite:///{db_path.as_posix()}")

            with self.assertRaises(RepositoryValidationError):
                storage.save_channels([
                    {"id": "channel-a", "base_url": "https://a.example"},
                    {"id": "channel-a", "base_url": "https://b.example"},
                ])
            storage.close()


if __name__ == "__main__":
    unittest.main()
