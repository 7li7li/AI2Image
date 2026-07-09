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

    def test_password_reset_code_updates_password_and_invalidates_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = AuthService(storage)
            user, session_token = service.create_user(email="user@example.com", password="old-secret")

            reset_user, code = service.create_password_reset("USER@example.com")

            self.assertEqual(reset_user["id"], user["id"])
            self.assertRegex(code, r"^\d{6}$")
            with self.assertRaisesRegex(ValueError, "email or verification code is invalid"):
                service.reset_password_with_code(email="user@example.com", code="000000", password="new-secret")

            updated_user = service.reset_password_with_code(email="user@example.com", code=code, password="new-secret")

            self.assertEqual(updated_user["id"], user["id"])
            self.assertIsNone(service.authenticate(session_token))
            with self.assertRaisesRegex(ValueError, "email or password is invalid"):
                service.login_user(email="user@example.com", password="old-secret")
            logged_in_user, _ = service.login_user(email="user@example.com", password="new-secret")
            self.assertEqual(logged_in_user["id"], user["id"])

    def test_email_verification_activates_pending_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = AuthService(storage)
            user, token = service.create_user(
                email="new@example.com",
                password="secret-pass",
                status="pending",
                email_verified=False,
                create_session=False,
            )

            self.assertEqual(token, "")
            self.assertEqual(user["status"], "pending")
            self.assertFalse(user["email_verified"])
            with self.assertRaisesRegex(ValueError, "email verification is required"):
                service.login_user(email="new@example.com", password="secret-pass")

            pending_user, code = service.create_email_verification("new@example.com")
            self.assertEqual(pending_user["status"], "pending")
            self.assertRegex(code, r"^\d{6}$")

            verified_user, session_token = service.verify_email(email="new@example.com", code=code)

            self.assertEqual(verified_user["status"], "active")
            self.assertTrue(verified_user["email_verified"])
            self.assertTrue(session_token)
            self.assertEqual(service.authenticate(session_token)["id"], user["id"])  # type: ignore[index]

    def test_email_verification_rejects_wrong_code_and_resend_requires_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = AuthService(storage)
            service.create_user(
                email="new@example.com",
                password="secret-pass",
                status="pending",
                email_verified=False,
                create_session=False,
            )
            service.create_email_verification("new@example.com")

            with self.assertRaisesRegex(ValueError, "email or verification code is invalid"):
                service.verify_email(email="new@example.com", code="000000")
            with self.assertRaisesRegex(ValueError, "email or password is invalid"):
                service.create_email_verification("new@example.com", password="wrong-pass")

            _, code = service.create_email_verification("new@example.com", password="secret-pass")
            verified_user, _ = service.verify_email(email="new@example.com", code=code)
            self.assertEqual(verified_user["status"], "active")


if __name__ == "__main__":
    unittest.main()
