import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.prompts as prompts_api
from services.prompt_service import PromptLibraryService
from services.storage.json_storage import JSONStorageBackend


class PromptApiTests(unittest.TestCase):
    def test_upload_prompt_asset_route_is_not_shadowed_by_prompt_id_route(self) -> None:
        self._assert_upload_prompt_asset("/api/admin/prompts/assets")

    def test_upload_prompt_asset_has_stable_non_dynamic_route(self) -> None:
        self._assert_upload_prompt_asset("/api/admin/prompt-assets")

    def test_user_prompt_submission_approval_and_share_import_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            service = PromptLibraryService(
                JSONStorageBackend(root / "storage.json"),
                assets_dir=root / "assets",
            )
            original_service = prompts_api.prompt_library_service
            original_require_admin = prompts_api.require_admin
            original_require_identity = prompts_api.require_identity
            try:
                prompts_api.prompt_library_service = service
                prompts_api.require_identity = lambda authorization: {"id": "user-1", "name": "User One", "role": "user"}
                prompts_api.require_admin = lambda authorization: {"id": "admin", "name": "Admin", "role": "admin"}

                app = FastAPI()
                app.include_router(prompts_api.create_router())
                client = TestClient(app)

                created = client.post(
                    "/api/me/prompts",
                    json={"title": "User prompt", "prompt": "Generate a clean poster"},
                )
                self.assertEqual(created.status_code, 200, created.text)
                prompt_id = created.json()["item"]["id"]
                self.assertEqual(created.json()["item"]["status"], "personal")

                submitted = client.post(f"/api/me/prompts/{prompt_id}/submit")
                self.assertEqual(submitted.status_code, 200, submitted.text)
                self.assertEqual(submitted.json()["item"]["status"], "submitted")

                approved = client.post(f"/api/admin/prompts/{prompt_id}/approve")
                self.assertEqual(approved.status_code, 200, approved.text)
                self.assertEqual(approved.json()["item"]["status"], "public")

                shared = client.post(
                    "/api/prompts/share",
                    json={"title": "Shared prompt", "prompt": "Generate a movie poster"},
                )
                self.assertEqual(shared.status_code, 200, shared.text)
                share_id = shared.json()["share_id"]

                imported = client.post(f"/api/prompts/share/{share_id}/import", json={"target_scope": "personal"})
                self.assertEqual(imported.status_code, 200, imported.text)
                self.assertEqual(imported.json()["item"]["status"], "personal")
            finally:
                prompts_api.prompt_library_service = original_service
                prompts_api.require_admin = original_require_admin
                prompts_api.require_identity = original_require_identity

    def _assert_upload_prompt_asset(self, path: str) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            service = PromptLibraryService(
                JSONStorageBackend(root / "storage.json"),
                assets_dir=root / "assets",
            )
            original_service = prompts_api.prompt_library_service
            original_require_admin = prompts_api.require_admin
            try:
                prompts_api.prompt_library_service = service
                prompts_api.require_admin = lambda authorization: {"id": "admin", "role": "admin"}

                app = FastAPI()
                app.include_router(prompts_api.create_router())
                response = TestClient(app).post(
                    path,
                    files={"file": ("sample.png", b"image-bytes", "image/png")},
                )
            finally:
                prompts_api.prompt_library_service = original_service
                prompts_api.require_admin = original_require_admin

            self.assertEqual(response.status_code, 200, response.text)
            url = response.json()["url"]
            self.assertTrue(url.startswith("/prompt-assets/"))
            relative_path = Path(*url.removeprefix("/prompt-assets/").split("/"))
            self.assertTrue((root / "assets" / relative_path).is_file())


if __name__ == "__main__":
    unittest.main()

