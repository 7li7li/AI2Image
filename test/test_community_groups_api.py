from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import users as users_api
from services.config import ConfigStore


class FakeAuthService:
    def get_user(self, user_id: str) -> dict[str, object] | None:
        if user_id != "user-a":
            return None
        return {
            "id": "user-a",
            "email": "user@example.com",
            "name": "User",
            "role": "user",
            "status": "active",
            "quota": 10,
        }


class FakePaymentService:
    def __init__(self) -> None:
        self.subscription: dict[str, object] | None = None

    def active_subscription_access(self, user_id: str, *, default: int = 1) -> dict[str, object]:
        return {
            "concurrency": int((self.subscription or {}).get("concurrency") or default),
            "subscription": self.subscription,
        }


class CommunityGroupsApiTests(unittest.TestCase):
    def test_me_filters_community_groups_by_any_active_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            config = ConfigStore(config_path)
            config.update(
                {
                    "qq_group_number": "123456789",
                    "qq_group_link": "https://qm.qq.com/q/example",
                    "qq_group_subscription_required": True,
                    "telegram_group_link": "https://t.me/example",
                    "telegram_group_subscription_required": False,
                }
            )
            payment = FakePaymentService()
            app = FastAPI()
            app.include_router(users_api.create_router())

            with (
                mock.patch.object(
                    users_api,
                    "require_identity",
                    return_value={"id": "user-a", "role": "user"},
                ),
                mock.patch.object(users_api, "auth_service", FakeAuthService()),
                mock.patch.object(users_api, "payment_service", payment),
                mock.patch.object(users_api, "config", config),
            ):
                client = TestClient(app)
                without_subscription = client.get("/api/me")

                payment.subscription = {
                    "plan_id": "any-plan",
                    "plan_name": "任意有效订阅",
                    "concurrency": 2,
                }
                with_subscription = client.get("/api/me")

                config.update(
                    {
                        "qq_group_subscription_required": False,
                        "telegram_group_subscription_required": True,
                    }
                )
                payment.subscription = None
                qq_open_to_all = client.get("/api/me")

            self.assertEqual(without_subscription.status_code, 200, without_subscription.text)
            self.assertEqual(
                without_subscription.json()["user"]["community_groups"],
                {"telegram": {"link": "https://t.me/example"}},
            )
            expected_groups = {
                "qq": {"number": "123456789", "link": "https://qm.qq.com/q/example"},
                "telegram": {"link": "https://t.me/example"},
            }
            self.assertEqual(with_subscription.json()["user"]["community_groups"], expected_groups)
            self.assertEqual(
                qq_open_to_all.json()["user"]["community_groups"],
                {"qq": {"number": "123456789", "link": "https://qm.qq.com/q/example"}},
            )


if __name__ == "__main__":
    unittest.main()
