import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


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

    def test_removed_registration_settings_are_not_returned(self) -> None:
        module = self.config_module
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "auth-key": "test-auth",
                        "smtp_password": "smtp-secret",
                        "allow_user_registration": True,
                        "internal_pool_enabled": True,
                    }
                ),
                encoding="utf-8",
            )
            store = module.ConfigStore(config_path)

            public = store.get()
            self.assertNotIn("smtp_password", public)
            self.assertNotIn("smtp_password_set", public)
            self.assertNotIn("allow_user_registration", public)
            self.assertNotIn("internal_pool_enabled", public)

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
