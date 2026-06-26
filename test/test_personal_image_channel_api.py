from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("STORAGE_BACKEND", "json")

import api.ai as api_ai
import api.support as api_support


class FakeAuthService:
    def __init__(self) -> None:
        self.identity = {
            "id": "user-a",
            "name": "Alice",
            "role": "user",
            "email": "alice@example.com",
        }
        self.reserved: list[tuple[str, int, str]] = []
        self.confirmed: list[tuple[str, int | None]] = []
        self.released: list[str] = []
        self.reserve_error: ValueError | None = None

    def authenticate(self, token: str):
        return self.identity if token == "user-token" else None

    def reserve_quota(self, user_id: str, amount: int, request_id: str):
        self.reserved.append((user_id, amount, request_id))
        if self.reserve_error is not None:
            raise self.reserve_error
        return {"user_id": user_id, "amount": amount, "request_id": request_id}

    def release_quota(self, request_id: str):
        self.released.append(request_id)
        return {"request_id": request_id}

    def confirm_quota(self, request_id: str, amount: int | None = None):
        self.confirmed.append((request_id, amount))
        return {"request_id": request_id, "amount": amount}

    def get_user_image_channel_config(self, user_id: str, *, include_api_key: bool = False):
        raise AssertionError("image generation must not read legacy personal channel settings")


class FakeChannelService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.edit_calls: list[dict[str, object]] = []
        self.generation_result: tuple[dict[str, object], str] | None = (
            {"created": 1, "data": [{"url": "https://global.example/image.png"}]},
            "Global",
        )
        self.edit_result: tuple[dict[str, object], str] | None = (
            {"created": 1, "data": [{"url": "https://global.example/edit.png"}]},
            "Global",
        )

    def has_usable_personal_channel(
        self,
        model: str | None,
        personal_channel: object = None,
        *,
        owner_user_id: str = "",
    ) -> bool:
        raise AssertionError("image generation must not route through personal channels")

    def call_generation(self, payload: dict[str, object]):
        self.calls.append(dict(payload))
        if self.generation_result is not None:
            return self.generation_result
        payload["_channel_error"] = "Global: upstream timeout"
        return None

    def call_edit(self, payload: dict[str, object]):
        self.edit_calls.append(dict(payload))
        if self.edit_result is not None:
            return self.edit_result
        payload["_channel_error"] = "Global: upstream timeout"
        return None


class PersonalImageChannelApiTests(unittest.TestCase):
    def test_generation_ignores_legacy_personal_channel_config_and_charges_quota(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())
        auth = FakeAuthService()
        channels = FakeChannelService()
        record_calls: list[dict[str, object]] = []

        def fake_record_image_result(identity: dict[str, object], result: dict[str, object], **kwargs: object):
            record_calls.append(dict(kwargs))
            return []

        with (
            mock.patch.object(api_support, "auth_service", auth),
            mock.patch.object(api_ai, "auth_service", auth),
            mock.patch.object(api_ai, "channel_service", channels),
            mock.patch.object(api_ai, "record_image_result", fake_record_image_result),
        ):
            response = TestClient(app).post(
                "/v1/images/generations",
                headers={"Authorization": "Bearer user-token"},
                json={
                    "model": "gpt-image-2",
                    "prompt": "draw",
                    "n": 1,
                    "response_format": "url",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"][0]["url"], "https://global.example/image.png")
        self.assertEqual(len(channels.calls), 1)
        self.assertNotIn("_personal_image_channel", channels.calls[0])
        self.assertNotIn("_owner_user_id", channels.calls[0])
        self.assertEqual(len(auth.reserved), 1)
        self.assertEqual(auth.reserved[0][0], "user-a")
        self.assertEqual(auth.reserved[0][1], 1)
        self.assertEqual(auth.confirmed, [(auth.reserved[0][2], 1)])
        self.assertEqual(auth.released, [])
        self.assertEqual(record_calls[0]["channel"], "Global")
        self.assertEqual(record_calls[0]["quota_cost"], 1)

    def test_generation_failure_releases_reserved_quota(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())
        auth = FakeAuthService()
        channels = FakeChannelService()
        channels.generation_result = None
        log_calls: list[dict[str, object]] = []

        def fake_log_add(type_name: str, summary: str = "", detail: dict[str, object] | None = None, **data: object):
            log_calls.append({"type": type_name, "summary": summary, **(detail or data)})

        with (
            mock.patch.object(api_support, "auth_service", auth),
            mock.patch.object(api_ai, "auth_service", auth),
            mock.patch.object(api_ai, "channel_service", channels),
            mock.patch.object(api_ai.log_service, "add", fake_log_add),
        ):
            response = TestClient(app).post(
                "/v1/images/generations",
                headers={"Authorization": "Bearer user-token"},
                json={
                    "model": "gpt-image-2",
                    "prompt": "draw",
                    "n": 1,
                    "response_format": "url",
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("Global: upstream timeout", response.text)
        self.assertEqual(len(auth.reserved), 1)
        self.assertEqual(auth.confirmed, [])
        self.assertEqual(auth.released, [auth.reserved[0][2]])
        self.assertEqual(len(log_calls), 1)
        self.assertEqual(log_calls[0]["endpoint"], "/v1/images/generations")
        self.assertEqual(log_calls[0]["model"], "gpt-image-2")
        self.assertEqual(log_calls[0]["status"], "error")
        self.assertEqual(log_calls[0]["error"], "Global: upstream timeout")
        self.assertEqual(log_calls[0]["user_id"], "user-a")

    def test_edit_ignores_legacy_personal_channel_config_and_charges_quota(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())
        auth = FakeAuthService()
        channels = FakeChannelService()
        record_calls: list[dict[str, object]] = []

        def fake_record_image_result(identity: dict[str, object], result: dict[str, object], **kwargs: object):
            record_calls.append(dict(kwargs))
            return []

        with (
            mock.patch.object(api_support, "auth_service", auth),
            mock.patch.object(api_ai, "auth_service", auth),
            mock.patch.object(api_ai, "channel_service", channels),
            mock.patch.object(api_ai, "record_image_result", fake_record_image_result),
        ):
            response = TestClient(app).post(
                "/v1/images/edits",
                headers={"Authorization": "Bearer user-token"},
                data={
                    "model": "gpt-image-2",
                    "prompt": "edit",
                    "n": "1",
                    "response_format": "url",
                },
                files={"image": ("input.png", b"image-bytes", "image/png")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"][0]["url"], "https://global.example/edit.png")
        self.assertEqual(len(channels.edit_calls), 1)
        self.assertNotIn("_personal_image_channel", channels.edit_calls[0])
        self.assertNotIn("_owner_user_id", channels.edit_calls[0])
        self.assertEqual(len(auth.reserved), 1)
        self.assertEqual(auth.confirmed, [(auth.reserved[0][2], 1)])
        self.assertEqual(auth.released, [])
        self.assertEqual(record_calls[0]["channel"], "Global")
        self.assertEqual(record_calls[0]["quota_cost"], 1)


if __name__ == "__main__":
    unittest.main()
