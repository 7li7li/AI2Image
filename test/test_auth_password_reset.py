from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from services.auth_service import AuthService
from services.storage.json_storage import JSONStorageBackend


class PasswordResetTest(unittest.TestCase):
    def test_reset_password_accepts_custom_password_and_invalidates_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = AuthService(storage)
            user, session_token = service.create_user(email="user@example.com", password="old-secret")

            result = service.reset_password(str(user["id"]), "new-secret")

            self.assertIsNotNone(result)
            updated_user, password = result
            self.assertEqual(updated_user["email"], "user@example.com")
            self.assertEqual(password, "new-secret")
            self.assertIsNone(service.authenticate(session_token))
            with self.assertRaisesRegex(ValueError, "email or password is invalid"):
                service.login_user(email="user@example.com", password="old-secret")
            logged_in_user, _ = service.login_user(email="user@example.com", password="new-secret")
            self.assertEqual(logged_in_user["id"], user["id"])

    def test_reset_password_generates_password_when_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = AuthService(storage)
            user, _ = service.create_user(email="user@example.com", password="old-secret")

            result = service.reset_password(str(user["id"]), "")

            self.assertIsNotNone(result)
            _, password = result
            self.assertGreaterEqual(len(password), 6)
            logged_in_user, _ = service.login_user(email="user@example.com", password=password)
            self.assertEqual(logged_in_user["id"], user["id"])

    def test_reset_password_rejects_short_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = AuthService(storage)
            user, _ = service.create_user(email="user@example.com", password="old-secret")

            with self.assertRaisesRegex(ValueError, "password must be at least 6 characters"):
                service.reset_password(str(user["id"]), "12345")


if __name__ == "__main__":
    unittest.main()
