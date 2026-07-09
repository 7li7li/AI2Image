import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from services.storage.database_storage import DatabaseStorageBackend


ROOT_DIR = Path(__file__).resolve().parents[1]
ROOT_CONFIG_FILE = ROOT_DIR / "config.json"


class ConfigLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._created_root_config = False
        if not ROOT_CONFIG_FILE.exists():
            ROOT_CONFIG_FILE.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            cls._created_root_config = True

        from services import config as config_module

        cls.config_module = config_module

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._created_root_config and ROOT_CONFIG_FILE.exists():
            ROOT_CONFIG_FILE.unlink()

    def test_image_model_mappings_default_and_override(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            store = module.ConfigStore(config_path)

            self.assertEqual(store.image_model_mappings, {})

            store.update({"image_model_mappings": {"gpt-image-2": "auto", "custom-image": "gpt-5-3-mini"}})

            self.assertEqual(store.image_model_mappings["gpt-image-2"], "auto")
            self.assertEqual(store.image_model_mappings["custom-image"], "gpt-5-3-mini")
            self.assertEqual(set(store.get()["image_model_mappings"]), {"gpt-image-2", "custom-image"})

    def test_default_models_default_and_override(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            store = module.ConfigStore(config_path)

            self.assertEqual(store.default_image_model, "gpt-image-2")
            self.assertEqual(store.default_text_model, "gpt-5.5")
            self.assertEqual(store.public_settings()["default_image_model"], "gpt-image-2")
            self.assertEqual(store.public_settings()["default_text_model"], "gpt-5.5")

            store.update({"default_image_model": "custom-image", "default_text_model": "custom-chat"})

            self.assertEqual(store.default_image_model, "custom-image")
            self.assertEqual(store.default_text_model, "custom-chat")
            self.assertEqual(store.get()["default_image_model"], "custom-image")
            self.assertEqual(store.get()["default_text_model"], "custom-chat")

    def test_background_task_limits_default_override_and_env(self) -> None:
        module = self.config_module
        env_keys = [
            "YANAI_BACKGROUND_TASK_MAX_WORKERS",
            "YANAI_BACKGROUND_TASK_QUEUE_LIMIT",
            "YANAI_BACKGROUND_TASK_USER_LIMIT",
        ]
        original_env = {key: os.environ.get(key) for key in env_keys}
        for key in env_keys:
            os.environ.pop(key, None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                config_path = Path(tmp_dir) / "config.json"
                config_path.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
                store = module.ConfigStore(config_path)

                self.assertEqual(store.background_task_max_workers, 12)
                self.assertEqual(store.background_task_queue_limit, 100)
                self.assertEqual(store.background_task_user_limit, 3)

                store.update(
                    {
                        "background_task_max_workers": 20,
                        "background_task_queue_limit": 200,
                        "background_task_user_limit": 0,
                    }
                )

                self.assertEqual(store.background_task_max_workers, 20)
                self.assertEqual(store.background_task_queue_limit, 200)
                self.assertEqual(store.background_task_user_limit, 0)

                os.environ["YANAI_BACKGROUND_TASK_MAX_WORKERS"] = "12"
                os.environ["YANAI_BACKGROUND_TASK_QUEUE_LIMIT"] = "1000"
                os.environ["YANAI_BACKGROUND_TASK_USER_LIMIT"] = "3"

                self.assertEqual(store.background_task_max_workers, 12)
                self.assertEqual(store.background_task_queue_limit, 1000)
                self.assertEqual(store.background_task_user_limit, 3)
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_auth_key_comes_from_config_file_only(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"auth-key": "file-auth"}), encoding="utf-8")

            original_env_value = os.environ.get("CHATGPT2API_AUTH_KEY")
            os.environ["CHATGPT2API_AUTH_KEY"] = "env-auth"
            try:
                store = module.ConfigStore(config_path)
            finally:
                if original_env_value is None:
                    os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    os.environ["CHATGPT2API_AUTH_KEY"] = original_env_value

            self.assertEqual(store.auth_key, "file-auth")

    def test_registration_settings_are_admin_only_and_secrets_are_masked(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "auth-key": "test-auth",
                        "smtp_password": "smtp-secret",
                        "allow_user_registration": True,
                        "email_verification_enabled": True,
                        "email_domain_whitelist_enabled": True,
                        "email_domain_whitelist": ["Example.com", "@example.org", "user@example.net", "*.school.edu"],
                    }
                ),
                encoding="utf-8",
            )
            store = module.ConfigStore(config_path)

            admin = store.get()
            self.assertTrue(admin["allow_user_registration"])
            self.assertTrue(admin["email_verification_enabled"])
            self.assertTrue(admin["email_domain_whitelist_enabled"])
            self.assertEqual(admin["email_domain_whitelist"], ["example.com", "example.org", "user@example.net", "*.school.edu"])
            self.assertEqual(admin["new_user_quota_valid_days"], 0)
            self.assertTrue(admin["smtp_password_set"])
            self.assertNotIn("smtp_password", admin)

            public = store.public_settings()
            self.assertNotIn("allow_user_registration", public)
            self.assertNotIn("email_verification_enabled", public)
            self.assertNotIn("email_domain_whitelist", public)

            public_auth = store.public_auth_settings()
            self.assertEqual(
                public_auth,
                {
                    "allow_user_registration": True,
                    "email_verification_enabled": True,
                    "email_domain_whitelist_enabled": True,
                    "email_domain_whitelist": ["example.com", "example.org"],
                },
            )

    def test_update_registration_settings_ignores_transient_status_fields(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"auth-key": "test-auth", "smtp_password": "existing-secret"}),
                encoding="utf-8",
            )
            store = module.ConfigStore(config_path)

            updated = store.update(
                {
                    "allow_user_registration": "true",
                    "email_verification_enabled": "false",
                    "email_domain_whitelist_enabled": "on",
                    "email_domain_whitelist": "Example.com\n@example.org,user@example.net",
                    "new_user_initial_quota": "25",
                    "new_user_quota_valid_days": "7",
                    "smtp_password": "",
                    "smtp_password_set": False,
                    "linuxdo_client_secret_set": True,
                    "image_webdav_password_set": True,
                }
            )

            self.assertTrue(updated["allow_user_registration"])
            self.assertFalse(updated["email_verification_enabled"])
            self.assertTrue(updated["email_domain_whitelist_enabled"])
            self.assertEqual(updated["email_domain_whitelist"], ["example.com", "example.org", "user@example.net"])
            self.assertEqual(updated["new_user_initial_quota"], 25)
            self.assertEqual(updated["new_user_quota_valid_days"], 7)
            self.assertTrue(updated["smtp_password_set"])
            self.assertEqual(store.smtp_password, "existing-secret")
            self.assertNotIn("smtp_password_set", store.data)
            self.assertNotIn("linuxdo_client_secret_set", store.data)
            self.assertNotIn("image_webdav_password_set", store.data)
            self.assertEqual(store.public_auth_settings()["allow_user_registration"], True)

    def test_new_user_quota_valid_days_calculates_expiry(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            store = module.ConfigStore(config_path)

            self.assertEqual(store.new_user_quota_valid_days, 0)
            self.assertIsNone(store.new_user_quota_expires_at(datetime(2026, 1, 1, tzinfo=timezone.utc)))

            updated = store.update({"new_user_initial_quota": 25, "new_user_quota_valid_days": "7"})
            expires_at = store.new_user_quota_expires_at(datetime(2026, 1, 1, tzinfo=timezone.utc))

            self.assertEqual(updated["new_user_quota_valid_days"], 7)
            self.assertEqual(expires_at, "2026-01-08T00:00:00+00:00")

            updated = store.update({"new_user_quota_valid_days": "99999"})
            self.assertEqual(updated["new_user_quota_valid_days"], 3650)

    def test_database_backed_registration_update_takes_effect_immediately(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            storage = DatabaseStorageBackend(f"sqlite:///{(Path(tmp_dir) / 'settings.db').as_posix()}")
            try:
                store = module.ConfigStore(config_path)
                store._storage_backend = storage

                updated = store.update({"allow_user_registration": True})

                self.assertTrue(updated["allow_user_registration"])
                self.assertTrue(store.public_auth_settings()["allow_user_registration"])
                self.assertTrue(storage.repository_provider.system_config.get_setting("allow_user_registration"))
            finally:
                storage.close()

    def test_email_registration_whitelist_supports_domains_wildcards_and_addresses(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "auth-key": "test-auth",
                        "email_domain_whitelist_enabled": True,
                        "email_domain_whitelist": ["example.com", "*.school.edu", "invited@example.net"],
                    }
                ),
                encoding="utf-8",
            )
            store = module.ConfigStore(config_path)

            self.assertTrue(store.email_allowed_for_registration("person@example.com"))
            self.assertTrue(store.email_allowed_for_registration("student@dept.school.edu"))
            self.assertTrue(store.email_allowed_for_registration("invited@example.net"))
            self.assertFalse(store.email_allowed_for_registration("person@other.com"))
            self.assertFalse(store.email_allowed_for_registration("person@school.edu"))

    def test_cleanup_old_images_keeps_recent_recorded_files_and_removes_old_orphans(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            data_dir = base_dir / "data"
            config_path = base_dir / "config.json"
            config_path.write_text(json.dumps({"auth-key": "test-auth", "image_retention_days": 30}), encoding="utf-8")
            old_data_dir = module.DATA_DIR
            try:
                module.DATA_DIR = data_dir
                store = module.ConfigStore(config_path)
                keep = data_dir / "images" / "2026" / "05" / "29" / "keep.png"
                orphan = data_dir / "images" / "2026" / "05" / "01" / "orphan.png"
                keep.parent.mkdir(parents=True)
                orphan.parent.mkdir(parents=True)
                keep.write_bytes(b"keep")
                orphan.write_bytes(b"orphan")
                old_timestamp = time.time() - 40 * 86400
                os.utime(keep, (old_timestamp, old_timestamp))
                os.utime(orphan, (old_timestamp, old_timestamp))
                store._storage_backend = SimpleNamespace(
                    load_image_records=lambda: [
                        {
                            "url": "http://127.0.0.1:8000/images/2026/05/29/keep.png",
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                    ]
                )

                removed = store.cleanup_old_images()

                self.assertEqual(removed, 1)
                self.assertTrue(keep.exists())
                self.assertFalse(orphan.exists())
            finally:
                module.DATA_DIR = old_data_dir


if __name__ == "__main__":
    unittest.main()
