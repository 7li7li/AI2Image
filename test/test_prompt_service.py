import json
import tempfile
import unittest
from pathlib import Path

from services.prompt_service import PromptLibraryService
from services.storage.json_storage import JSONStorageBackend


class PromptLibraryServiceTests(unittest.TestCase):
    def test_bootstrap_create_update_delete_and_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            seed_path = root / "seed.json"
            seed_path.write_text(
                json.dumps(
                    {
                        "prompts": [
                            {
                                "title": "Legacy prompt",
                                "description": "Legacy description",
                                "prompt": "Generate a poster",
                                "mode": "generate",
                                "image_size": "4:3",
                                "image_count": "1",
                                "quick_access": True,
                                "category": "Work",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            storage = JSONStorageBackend(root / "storage.json")
            service = PromptLibraryService(storage, bootstrap_paths=(seed_path,), assets_dir=root / "assets")

            self.assertEqual(len(service.list_prompts()), 1)
            original = service.list_prompts()[0]
            self.assertEqual(original["description"], "Legacy description")
            self.assertEqual(original["image_size"], "4:3")
            self.assertTrue(original["quick_access"])

            created = service.create_prompt(
                {
                    "title": "New prompt",
                    "prompt": "Turn the reference image into a magazine cover",
                    "mode": "edit",
                    "preview": "/example.png",
                    "reference_image_urls": ["/ref.png"],
                }
            )

            self.assertEqual(created["mode"], "edit")
            self.assertEqual(len(storage.load_prompt_library()), 2)

            updated = service.update_prompt(
                created["id"],
                {"title": "Updated prompt", "reference_image_urls": "/a.png\n/b.png"},
            )
            self.assertIsNotNone(updated)
            self.assertEqual(updated["title"], "Updated prompt")
            self.assertEqual(updated["reference_image_urls"], ["/a.png", "/b.png"])

            asset_url = service.save_asset(b"image-bytes", filename="sample.png", content_type="image/png")
            self.assertTrue(asset_url.startswith("/prompt-assets/"))
            self.assertTrue(list((root / "assets").rglob("*.png")))

            self.assertTrue(service.delete_prompt(created["id"]))
            self.assertEqual(len(service.list_prompts()), 1)

    def test_default_prompts_are_added_to_existing_legacy_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            seed_path = root / "seed.json"
            seed_path.write_text(
                json.dumps(
                    {
                        "prompts": [
                            {
                                "id": "quick",
                                "title": "Quick prompt",
                                "prompt": "Generate quick content",
                                "quick_access": True,
                                "category": "Built in",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            storage = JSONStorageBackend(root / "storage.json")
            storage.save_prompt_library(
                [
                    {
                        "id": "legacy",
                        "title": "Legacy library prompt",
                        "prompt": "Generate legacy content",
                        "category": "Work",
                    }
                ]
            )

            service = PromptLibraryService(storage, bootstrap_paths=(seed_path,), assets_dir=root / "assets")
            items = service.list_prompts()

            self.assertEqual([item["id"] for item in items], ["quick", "legacy"])

    def test_user_submission_review_share_and_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage = JSONStorageBackend(root / "storage.json")
            service = PromptLibraryService(storage, bootstrap_paths=(), assets_dir=root / "assets")
            user = {"id": "user-1", "name": "User One", "role": "user"}
            admin = {"id": "admin", "name": "Admin", "role": "admin"}

            personal = service.create_user_prompt(
                {
                    "title": "User prompt",
                    "prompt": "Generate a soft-light portrait",
                    "mode": "generate",
                },
                user,
            )

            self.assertEqual(personal["status"], "personal")
            self.assertEqual(service.list_prompts(), [])
            self.assertEqual(len(service.list_user_prompts(user)), 1)

            submitted = service.submit_user_prompt(personal["id"], user)
            self.assertIsNotNone(submitted)
            self.assertEqual(submitted["status"], "submitted")
            self.assertEqual(len(service.list_admin_prompts()), 1)

            approved = service.approve_prompt(personal["id"], admin)
            self.assertIsNotNone(approved)
            self.assertEqual(approved["status"], "public")
            self.assertEqual(len(service.list_prompts()), 1)

            share = service.create_share(approved, user, source_prompt_id=approved["id"])
            self.assertEqual(share["status"], "shared")
            self.assertEqual(service.get_shared_prompt(share["share_id"])["title"], "User prompt")

            imported = service.import_shared_prompt(share["share_id"], admin)
            self.assertIsNotNone(imported)
            self.assertEqual(imported["status"], "public")
            self.assertEqual(imported["imported_from_share_id"], share["share_id"])


if __name__ == "__main__":
    unittest.main()
