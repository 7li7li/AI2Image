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


class AiModelsApiTests(unittest.TestCase):
    def test_v1_models_only_returns_models_from_enabled_channels(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())

        with (
            mock.patch.object(api_ai, "require_identity", return_value={"id": "user-a", "role": "user"}),
            mock.patch.object(api_ai, "channel_service", FakeChannelService()),
        ):
            response = TestClient(app).get("/v1/models", headers={"Authorization": "Bearer user-token"})

        self.assertEqual(response.status_code, 200, response.text)
        model_ids = [item["id"] for item in response.json()["data"]]

        self.assertEqual(model_ids, ["gpt-5.5", "gpt-image-2", "gemini-3.1-flash-image"])
        self.assertNotIn("gemini-3-pro", model_ids)
        self.assertNotIn("disabled-only-model", model_ids)


if __name__ == "__main__":
    unittest.main()
