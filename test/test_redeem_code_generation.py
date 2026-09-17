from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from api.users import RedeemCodeCreateRequest
from services.auth_service import AuthService
from services.storage.json_storage import JSONStorageBackend


class RedeemCodeGenerationTest(unittest.TestCase):
    def test_redeem_code_request_defaults_to_30_quota(self) -> None:
        self.assertEqual(RedeemCodeCreateRequest().quota, 30)

    def test_new_redeem_codes_use_ikun_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            created = AuthService(storage).create_redeem_codes(quota=10, count=3)

        self.assertEqual(len(created), 3)
        self.assertTrue(all(str(item["code"]).startswith("IKUN-") for item in created))


if __name__ == "__main__":
    unittest.main()
