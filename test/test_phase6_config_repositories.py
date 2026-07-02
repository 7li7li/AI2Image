from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.channel_service import ChannelService
from services.prompt_service import PromptLibraryService
from services.storage.database_storage import DatabaseStorageBackend


class Phase6ConfigRepositoryTest(unittest.TestCase):
    def test_concurrent_single_use_redeem_code_only_succeeds_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "redeem.db"
            storage = DatabaseStorageBackend(f"sqlite:///{db_path.as_posix()}")
            storage.save_users(
                [
                    {
                        "id": "user-a",
                        "email": "user-a@example.com",
                        "role": "user",
                        "status": "active",
                        "quota": 0,
                        "quota_used": 0,
                    }
                ]
            )
            storage.save_redeem_codes(
                [
                    {
                        "id": "redeem-a",
                        "code": "YAI-ONCE",
                        "quota": 1,
                        "status": "enabled",
                        "max_uses": 1,
                        "used_count": 0,
                        "used_by": [],
                    }
                ]
            )
            repo = storage.repository_provider.redeem_codes

            def redeem(_: int) -> bool:
                try:
                    repo.redeem("user-a", "YAI-ONCE")
                    return True
                except ValueError:
                    return False

            with ThreadPoolExecutor(max_workers=10) as executor:
                results = list(executor.map(redeem, range(10)))

            self.assertEqual(sum(1 for item in results if item), 1)
            user = storage.load_users()[0]
            code = storage.load_redeem_codes()[0]
            self.assertEqual(user["quota"], 1)
            self.assertEqual(code["used_count"], 1)
            self.assertEqual(code["status"], "disabled")
            storage.close()

    def test_channel_updates_write_rows_without_overwriting_other_channels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "channels.db"
            storage = DatabaseStorageBackend(f"sqlite:///{db_path.as_posix()}")
            storage.save_channels(
                [
                    {"id": "channel-a", "name": "A", "base_url": "https://a.example", "api_key": "a", "weight": 1},
                    {"id": "channel-b", "name": "B", "base_url": "https://b.example", "api_key": "b", "priority": 1},
                ]
            )
            admin_a = ChannelService(storage.repository_provider)
            admin_b = ChannelService(storage.repository_provider)

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(admin_a.update_channel, "channel-a", {"weight": 8}),
                    executor.submit(admin_b.update_channel, "channel-b", {"priority": 6}),
                ]
                for future in futures:
                    self.assertIsNotNone(future.result())

            channels = {item["id"]: item for item in storage.load_channels()}
            self.assertEqual(channels["channel-a"]["weight"], 8)
            self.assertEqual(channels["channel-b"]["priority"], 6)
            self.assertEqual(channels["channel-a"]["base_url"], "https://a.example")
            self.assertEqual(channels["channel-b"]["base_url"], "https://b.example")
            storage.close()

    def test_prompt_concurrent_creates_do_not_drop_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "prompts.db"
            storage = DatabaseStorageBackend(f"sqlite:///{db_path.as_posix()}")
            service = PromptLibraryService(
                storage.repository_provider,
                assets_dir=Path(tmp_dir) / "assets",
            )

            def create(index: int) -> str:
                item = service.create_prompt({"title": f"Prompt {index}", "prompt": f"Do {index}"})
                return str(item["id"])

            with ThreadPoolExecutor(max_workers=20) as executor:
                ids = list(executor.map(create, range(20)))

            prompts = storage.load_prompt_library()
            self.assertEqual(len(prompts), 20)
            self.assertEqual(len({item["id"] for item in prompts}), 20)
            self.assertEqual(set(ids), {item["id"] for item in prompts})
            storage.close()

    def test_system_settings_are_database_backed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "settings.db"
            url = f"sqlite:///{db_path.as_posix()}"
            storage = DatabaseStorageBackend(url)
            storage.repository_provider.system_config.set_setting("image_retention_days", 45)
            storage.repository_provider.system_config.set_setting("log_levels", ["error"])
            storage.close()

            reopened = DatabaseStorageBackend(url)
            settings = reopened.repository_provider.system_config.list_settings()
            self.assertEqual(settings["image_retention_days"], 45)
            self.assertEqual(settings["log_levels"], ["error"])
            reopened.close()


if __name__ == "__main__":
    unittest.main()
