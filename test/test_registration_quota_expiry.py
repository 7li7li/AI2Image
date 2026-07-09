from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import system as system_api
from services.auth_service import AuthService
from services.config import ConfigStore
from services.storage.json_storage import JSONStorageBackend


class RegistrationQuotaExpiryTest(unittest.TestCase):
    def test_registration_applies_configured_initial_quota_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "auth-key": "test-auth",
                        "allow_user_registration": True,
                        "new_user_initial_quota": 25,
                        "new_user_quota_valid_days": 7,
                    }
                ),
                encoding="utf-8",
            )
            config = ConfigStore(config_path)
            auth_service = AuthService(JSONStorageBackend(Path(tmp_dir) / "storage.json"))
            app = FastAPI()
            with mock.patch.object(system_api, "config", config), mock.patch.object(system_api, "auth_service", auth_service):
                app.include_router(system_api.create_router("test"))
                before = datetime.now(timezone.utc)
                response = TestClient(app).post(
                    "/auth/register",
                    json={"email": "new@example.com", "password": "secret123", "name": "New User"},
                )
                after = datetime.now(timezone.utc)

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["quota"], 25)
            users = auth_service.list_users()
            self.assertEqual(len(users), 1)
            expires_at = datetime.fromisoformat(str(users[0]["quota_expires_at"]))
            self.assertGreaterEqual(expires_at, before + timedelta(days=7))
            self.assertLessEqual(expires_at, after + timedelta(days=7))


if __name__ == "__main__":
    unittest.main()
