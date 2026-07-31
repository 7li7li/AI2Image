from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.ai as api_ai


class FakeChannelService:
    def list_channels(self):
        return [
            {
                "id": "enabled-openai",
                "name": "Enabled OpenAI",
                "enabled": True,
                "models": ["gpt-5.5", "gpt-image-2"],
            },
            {
                "id": "disabled-gemini",
                "name": "Disabled Gemini",
                "enabled": False,
                "models": ["gemini-3-pro", "disabled-only-model"],
            },
            {
                "id": "enabled-gemini",
                "name": "Enabled Gemini",
                "enabled": True,
                "models": ["gpt-5.5", "gemini-3.1-flash-image"],
            },
        ]


class FakeModelService:
    def quota_cost(self, model: str) -> int:
        return {"gpt-image-2": 3, "gemini-3.1-flash-image": 2}.get(model, 1)

    def list_quota_costs(self) -> dict[str, int]:
        return {
            "gemini-3.1-flash-image": 2,
            "gpt-5.5": 1,
            "gpt-image-2": 3,
        }


class AiModelsApiTests(unittest.TestCase):
    def test_public_models_returns_names_and_costs_without_authentication(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())

        with (
            mock.patch.object(api_ai, "channel_service", FakeChannelService()),
            mock.patch.object(api_ai, "model_service", FakeModelService()),
        ):
            response = TestClient(app).get("/api/public/models")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["items"],
            [
                {"model": "gpt-5.5", "quota_cost": 1, "image_resolutions": ["1k", "2k", "4k"]},
                {"model": "gpt-image-2", "quota_cost": 3, "image_resolutions": ["1k", "2k", "4k"]},
                {"model": "gemini-3.1-flash-image", "quota_cost": 2, "image_resolutions": ["1k", "2k", "4k"]},
            ],
        )

    def test_v1_models_only_returns_models_from_enabled_channels(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())

        with (
            mock.patch.object(api_ai, "require_identity", return_value={"id": "user-a", "role": "user"}),
            mock.patch.object(api_ai, "channel_service", FakeChannelService()),
            mock.patch.object(api_ai, "model_service", FakeModelService()),
        ):
            response = TestClient(app).get("/v1/models", headers={"Authorization": "Bearer user-token"})

        self.assertEqual(response.status_code, 200, response.text)
        models = response.json()["data"]
        model_ids = [item["id"] for item in models]
        quota_costs = {item["id"]: item["quota_cost"] for item in models}

        self.assertEqual(model_ids, ["gpt-5.5", "gpt-image-2", "gemini-3.1-flash-image"])
        self.assertEqual(quota_costs["gpt-5.5"], 1)
        self.assertEqual(quota_costs["gpt-image-2"], 3)
        self.assertEqual(quota_costs["gemini-3.1-flash-image"], 2)
        self.assertNotIn("gemini-3-pro", model_ids)
        self.assertNotIn("disabled-only-model", model_ids)

    def test_model_quota_costs_returns_cost_mapping(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())

        with (
            mock.patch.object(api_ai, "require_identity", return_value={"id": "user-a", "role": "user"}),
            mock.patch.object(api_ai, "model_service", FakeModelService()),
        ):
            response = TestClient(app).get("/api/model-quota-costs", headers={"Authorization": "Bearer user-token"})

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["costs"]["gpt-image-2"], 3)
        self.assertEqual(payload["costs"]["gemini-3.1-flash-image"], 2)
        self.assertIn({"model": "gpt-5.5", "quota_cost": 1}, payload["items"])


if __name__ == "__main__":
    unittest.main()
