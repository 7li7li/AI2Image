from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from services.auth_service import AuthService
from services.storage.database_storage import DatabaseStorageBackend
from services.storage.json_storage import JSONStorageBackend


class QuotaExpiryTest(unittest.TestCase):
    def test_decimal_quota_is_reserved_confirmed_and_released_in_json_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = AuthService(storage)
            user, _ = service.create_user(email="user@example.com", password="secret123", quota=1.5)

            service.reserve_quota(str(user["id"]), 0.25, "request-confirm")
            service.confirm_quota("request-confirm")
            service.reserve_quota(str(user["id"]), 0.4, "request-release")
            service.release_quota("request-release")

            current = service.get_user(str(user["id"]))
            self.assertIsNotNone(current)
            self.assertEqual(current["quota"], 1.25)  # type: ignore[index]
            self.assertEqual(current["quota_used"], 0.25)  # type: ignore[index]

    def test_decimal_quota_is_preserved_in_database_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = DatabaseStorageBackend(f"sqlite:///{(Path(tmp_dir) / 'decimal-quota.db').as_posix()}")
            try:
                storage.save_users(
                    [
                        {
                            "id": "user-decimal",
                            "email": "decimal@example.com",
                            "role": "user",
                            "status": "active",
                            "quota": 1.5,
                            "quota_used": 0,
                        }
                    ]
                )
                reservations = storage.repository_provider.quota_reservations
                reservations.reserve("user-decimal", 0.25, "request-decimal")
                reservations.confirm("request-decimal")

                current = storage.load_users()[0]
                self.assertEqual(current["quota"], 1.25)
                self.assertEqual(current["quota_used"], 0.25)
            finally:
                storage.close()

    def test_redeemed_quota_gets_expiry_and_can_be_used_before_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = AuthService(storage)
            user, _ = service.create_user(email="user@example.com", password="secret123")
            code = service.create_redeem_codes(quota=3, valid_months=2)[0]

            redeemed_user, redeemed_code = service.redeem_code(str(user["id"]), str(code["code"]))
            service.reserve_quota(str(user["id"]), 1, "request-a")

            self.assertEqual(redeemed_user["quota"], 3)
            self.assertEqual(redeemed_code["valid_months"], 2)
            self.assertIsNotNone(redeemed_user["quota_expires_at"])
            self.assertEqual(service.get_user(str(user["id"]))["quota"], 2)  # type: ignore[index]

    def test_redeem_adds_quota_but_replaces_expiry_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = AuthService(storage)
            user, _ = service.create_user(
                email="user@example.com",
                password="secret123",
                quota=5,
                quota_expires_at=(datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
            )
            code = service.create_redeem_codes(quota=3, valid_months=1)[0]

            before = datetime.now(timezone.utc)
            redeemed_user, redeemed_code = service.redeem_code(str(user["id"]), str(code["code"]))
            after = datetime.now(timezone.utc)
            expires_at = datetime.fromisoformat(str(redeemed_user["quota_expires_at"]))

            self.assertEqual(redeemed_user["quota"], 8)
            self.assertEqual(redeemed_code["valid_months"], 1)
            self.assertLess(expires_at, before + timedelta(days=40))
            self.assertGreater(expires_at, after + timedelta(days=20))

    def test_expired_user_quota_is_not_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_users(
                [
                    {
                        "id": "user-a",
                        "email": "user@example.com",
                        "role": "user",
                        "status": "active",
                        "quota": 3,
                        "quota_used": 0,
                        "quota_expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                    }
                ]
            )
            service = AuthService(storage)

            with self.assertRaisesRegex(ValueError, "剩余额度不足"):
                service.reserve_quota("user-a", 1, "request-a")

            user = service.get_user("user-a")
            self.assertIsNotNone(user)
            self.assertEqual(user["quota"], 0)  # type: ignore[index]

    def test_database_redeem_updates_quota_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = DatabaseStorageBackend(f"sqlite:///{(Path(tmp_dir) / 'quota-expiry.db').as_posix()}")
            try:
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
                            "code": "YAI-MONTHS",
                            "quota": 2,
                            "status": "enabled",
                            "max_uses": 1,
                            "valid_months": 1,
                            "used_count": 0,
                            "used_by": [],
                        }
                    ]
                )

                user, code = storage.repository_provider.redeem_codes.redeem("user-a", "YAI-MONTHS")

                self.assertEqual(user["quota"], 2)
                self.assertEqual(code["valid_months"], 1)
                self.assertIsNotNone(user["quota_expires_at"])
                self.assertEqual(storage.load_users()[0]["quota_expires_at"], user["quota_expires_at"])
            finally:
                storage.close()

    def test_database_redeem_adds_quota_but_replaces_expiry_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = DatabaseStorageBackend(f"sqlite:///{(Path(tmp_dir) / 'quota-expiry-replace.db').as_posix()}")
            try:
                storage.save_users(
                    [
                        {
                            "id": "user-a",
                            "email": "user-a@example.com",
                            "role": "user",
                            "status": "active",
                            "quota": 5,
                            "quota_used": 0,
                            "quota_expires_at": (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
                        }
                    ]
                )
                storage.save_redeem_codes(
                    [
                        {
                            "id": "redeem-a",
                            "code": "YAI-MONTHS",
                            "quota": 3,
                            "status": "enabled",
                            "max_uses": 1,
                            "valid_months": 1,
                            "used_count": 0,
                            "used_by": [],
                        }
                    ]
                )

                before = datetime.now(timezone.utc)
                user, code = storage.repository_provider.redeem_codes.redeem("user-a", "YAI-MONTHS")
                after = datetime.now(timezone.utc)
                expires_at = datetime.fromisoformat(str(user["quota_expires_at"]))

                self.assertEqual(user["quota"], 8)
                self.assertEqual(code["valid_months"], 1)
                self.assertLess(expires_at, before + timedelta(days=40))
                self.assertGreater(expires_at, after + timedelta(days=20))
                self.assertEqual(storage.load_users()[0]["quota_expires_at"], user["quota_expires_at"])
            finally:
                storage.close()

    def test_database_expired_quota_cannot_be_reserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = DatabaseStorageBackend(f"sqlite:///{(Path(tmp_dir) / 'quota-expired.db').as_posix()}")
            try:
                storage.save_users(
                    [
                        {
                            "id": "user-a",
                            "email": "user-a@example.com",
                            "role": "user",
                            "status": "active",
                            "quota": 1,
                            "quota_used": 0,
                            "quota_expires_at": "2000-01-01T00:00:00+00:00",
                        }
                    ]
                )

                with self.assertRaisesRegex(ValueError, "剩余额度不足"):
                    storage.repository_provider.quota_reservations.reserve("user-a", 1, "request-a")

                self.assertEqual(storage.load_users()[0]["quota"], 0)
            finally:
                storage.close()


if __name__ == "__main__":
    unittest.main()
