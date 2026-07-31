from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import system as system_api
from services.config import ConfigStore


class AnnouncementConfigTests(unittest.TestCase):
    def test_announcements_are_normalized_and_only_enabled_items_are_public(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            store = ConfigStore(config_path)

            updated = store.update(
                {
                    "announcements": [
                        {
                            "id": " release / 1 ",
                            "title": " 版本更新 ",
                            "content": " 新功能已上线。 ",
                            "category": "update",
                            "enabled": "true",
                            "popup": "yes",
                            "created_at": "2026-07-30T08:00:00Z",
                            "updated_at": "2026-07-30T09:00:00Z",
                        },
                        {
                            "id": "draft",
                            "title": "维护草稿",
                            "content": "暂不发布",
                            "category": "unknown",
                            "enabled": False,
                            "popup": True,
                        },
                        {"id": "invalid", "title": "缺少正文"},
                    ]
                }
            )

            self.assertEqual(len(updated["announcements"]), 2)
            self.assertEqual(updated["announcements"][0]["id"], "release1")
            self.assertEqual(updated["announcements"][0]["category"], "update")
            self.assertTrue(updated["announcements"][0]["popup"])
            self.assertEqual(updated["announcements"][1]["category"], "system")
            self.assertEqual([item["id"] for item in store.public_announcements()], ["release1"])

            reloaded = ConfigStore(config_path)
            self.assertEqual(reloaded.announcements, updated["announcements"])


class AnnouncementApiTests(unittest.TestCase):
    def test_authenticated_users_receive_public_announcements(self) -> None:
        items = [
            {
                "id": "notice-1",
                "title": "系统公告",
                "content": "公告正文",
                "category": "system",
                "enabled": True,
                "popup": False,
                "created_at": "2026-07-30T08:00:00Z",
                "updated_at": "2026-07-30T08:00:00Z",
            }
        ]
        fake_config = SimpleNamespace(public_announcements=lambda: items)
        app = FastAPI()
        app.include_router(system_api.create_router("test"))

        with (
            mock.patch.object(system_api, "config", fake_config),
            mock.patch.object(
                system_api,
                "require_identity",
                return_value={"id": "user-a", "role": "user"},
            ) as require_identity,
        ):
            response = TestClient(app).get(
                "/api/announcements",
                headers={"Authorization": "Bearer user-token"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"items": items})
        require_identity.assert_called_once_with("Bearer user-token")


if __name__ == "__main__":
    unittest.main()
