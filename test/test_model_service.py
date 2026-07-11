from __future__ import annotations

import tempfile
import unittest
import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from services.channel_service import ChannelService
from services import channel_service as channel_service_module
from services.model_service import FIXED_BILLING_MODE, ModelService, normalize_model_pricing
from services.storage.json_storage import JSONStorageBackend


class FakeConfigStore:
    def __init__(self):
        self.data: dict[str, object] = {}

    def get(self) -> dict[str, object]:
        return dict(self.data)

    def update(self, data: dict[str, object]) -> dict[str, object]:
        self.data.update(data)
        return self.get()


class ModelServiceTest(unittest.TestCase):
    def test_extract_model_ids_accepts_openai_and_compatible_shapes(self) -> None:
        payload = {
            "data": [
                {"id": "gpt-5.5"},
                {"model": "gpt-image-2"},
                "custom-image-model",
                {"slug": "custom-model"},
                {"id": "gpt-5.5"},
            ]
        }

        self.assertEqual(
            ChannelService.extract_model_ids(payload),
            ["gpt-5.5", "gpt-image-2", "custom-image-model", "custom-model"],
        )

    def test_catalog_merges_channel_models_with_default_pricing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "2api",
                        "base_url": "https://example.test",
                        "api_key": "sk-test",
                        "models": ["gpt-5.5", "gpt-image-2"],
                        "enabled": True,
                    }
                ]
            )
            service = ModelService(ChannelService(storage), FakeConfigStore())

            catalog = service.list_catalog()
            by_model = {item["model"]: item for item in catalog["items"]}

            self.assertIn("gpt-5.5", by_model)
            self.assertIn("gpt-image-2", by_model)
            self.assertEqual(by_model["gpt-5.5"]["channel_count"], 1)
            self.assertFalse(by_model["gpt-5.5"]["configured"])
            self.assertEqual(by_model["gpt-5.5"]["pricing"]["billing_mode"], "fixed")
            self.assertEqual(by_model["gpt-5.5"]["pricing"]["model_price"], 1)

    def test_channel_model_test_reports_status_without_persisting_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["configured-model"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())

            service._fetch_external_channel_models = lambda channel: ["remote-model", "other-model"]  # type: ignore[method-assign]
            result = service.test_channel_models("channel-a", ["remote-model"])

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["models"], ["remote-model", "other-model"])
            self.assertEqual(result["tested_models"], ["remote-model"])
            self.assertEqual(result["missing_models"], [])
            self.assertEqual(service.get_channel("channel-a")["models"], ["configured-model"])

            missing = service.test_channel_models("channel-a", ["missing-model"])

            self.assertIsNotNone(missing)
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["tested_models"], ["missing-model"])
            self.assertEqual(missing["missing_models"], ["missing-model"])

            def fail_fetch(channel):
                raise RuntimeError("models unavailable")

            service._fetch_external_channel_models = fail_fetch  # type: ignore[method-assign]
            failed = service.test_channel_models("channel-a", ["remote-model"])

            self.assertIsNotNone(failed)
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["tested_models"], ["remote-model"])
            self.assertIn("models unavailable", failed["error"])

    def test_channel_urls_accept_base_url_with_or_without_v1(self) -> None:
        self.assertEqual(
            ChannelService._openai_compatible_url({"base_url": "https://api.example.test"}, "/v1/models"),
            "https://api.example.test/v1/models",
        )
        self.assertEqual(
            ChannelService._openai_compatible_url({"base_url": "https://api.example.test/v1"}, "/v1/models"),
            "https://api.example.test/v1/models",
        )

    def test_model_list_unsupported_status_gets_helpful_error(self) -> None:
        class FakeResponse:
            ok = False
            status_code = 405
            text = "Method Not Allowed"

        class FakeSession:
            def get(self, url, timeout):
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["configured-model"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            service._session = lambda channel: FakeSession()  # type: ignore[method-assign]

            result = service.test_channel_models("channel-a", ["configured-model"])

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertIn("GET /v1/models", result["error"])
            self.assertIn("HTTP 405", result["error"])

    def test_external_channel_requires_requested_image_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-5.5"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())

            self.assertFalse(service.has_external_channels("gpt-image-2"))

    def test_channel_order_honors_weight_before_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "weight-wins",
                        "name": "Weight Wins",
                        "base_url": "https://weight.example",
                        "api_key": "sk-weight",
                        "models": ["gpt-image-2", "gpt-5.5"],
                        "priority": 1,
                        "weight": 2,
                    },
                    {
                        "id": "priority-wins-when-weight-ties",
                        "name": "Priority Wins",
                        "base_url": "https://priority.example",
                        "api_key": "sk-priority",
                        "models": ["gpt-image-2", "gpt-5.5"],
                        "priority": 2,
                        "weight": 1,
                    },
                    {
                        "id": "lower-priority-tie",
                        "name": "Lower Priority Tie",
                        "base_url": "https://tie.example",
                        "api_key": "sk-tie",
                        "models": ["gpt-image-2", "gpt-5.5"],
                        "priority": 1,
                        "weight": 1,
                    },
                ]
            )
            service = ChannelService(storage, FakeConfigStore())

            image_order = [channel["id"] for channel in service._enabled_external_channels("gpt-image-2")]
            chat_order = [channel["id"] for channel in service._enabled_external_chat_channels("gpt-5.5")]

            self.assertEqual(
                image_order,
                ["weight-wins", "priority-wins-when-weight-ties", "lower-priority-tie"],
            )
            self.assertEqual(
                chat_order,
                ["weight-wins", "priority-wins-when-weight-ties", "lower-priority-tie"],
            )

    def test_generation_uses_requested_image_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            seen: dict[str, object] = {}

            def fake_generation(channel, payload):
                seen["channel"] = channel.get("id")
                seen["model"] = payload.get("model")
                return {"created": 1, "data": [{"url": "https://a.example/image.png"}]}

            service._call_generation = fake_generation  # type: ignore[method-assign]
            routed = service.call_generation({"prompt": "draw", "model": "gpt-image-2", "n": 1})

            self.assertIsNotNone(routed)
            self.assertEqual(seen["channel"], "channel-a")
            self.assertEqual(seen["model"], "gpt-image-2")
            self.assertEqual(routed[1], "A")

    def test_generation_retries_next_distinct_supported_channel_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-a",
                        "models": ["gpt-image-2"],
                        "weight": 3,
                    },
                    {
                        "id": "channel-b",
                        "name": "B",
                        "base_url": "https://b.example",
                        "api_key": "sk-b",
                        "models": ["gpt-image-2"],
                    },
                    {
                        "id": "channel-c",
                        "name": "C",
                        "base_url": "https://c.example",
                        "api_key": "sk-c",
                        "models": ["other-image-model"],
                    },
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            calls: list[tuple[str, object]] = []
            payload = {"prompt": "draw", "model": "gpt-image-2", "n": 1}

            def fake_generation(channel, routed_payload):
                channel_id = str(channel.get("id"))
                calls.append((channel_id, routed_payload.get("model")))
                if channel_id == "channel-a":
                    raise RuntimeError("upstream timeout")
                return {"created": 1, "data": [{"url": "https://b.example/image.png"}]}

            service._call_generation = fake_generation  # type: ignore[method-assign]
            routed = service.call_generation(payload)

            self.assertIsNotNone(routed)
            self.assertEqual(calls, [("channel-a", "gpt-image-2"), ("channel-b", "gpt-image-2")])
            self.assertEqual(routed[1], "B")
            self.assertNotIn("_channel_error", payload)

    def test_chat_uses_text_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-5.5"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            seen: dict[str, object] = {}

            def fake_chat_completion(channel, payload):
                seen["channel"] = channel.get("id")
                seen["model"] = payload.get("model")
                return {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": payload.get("model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                }

            service._call_chat_completion = fake_chat_completion  # type: ignore[method-assign]
            routed = service.call_chat_completion({
                "model": "gpt-5.5",
                "messages": [{"role": "user", "content": "hello"}],
            })

            self.assertIsNotNone(routed)
            self.assertEqual(seen["channel"], "channel-a")
            self.assertEqual(seen["model"], "gpt-5.5")
            self.assertEqual(routed[1], "A")

    def test_chat_retries_next_distinct_supported_channel_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-a",
                        "models": ["gpt-5.5"],
                        "weight": 4,
                    },
                    {
                        "id": "channel-b",
                        "name": "B",
                        "base_url": "https://b.example",
                        "api_key": "sk-b",
                        "models": ["gpt-5.5"],
                    },
                    {
                        "id": "channel-c",
                        "name": "C",
                        "base_url": "https://c.example",
                        "api_key": "sk-c",
                        "models": ["other-text-model"],
                    },
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            calls: list[tuple[str, object]] = []
            payload = {
                "model": "gpt-5.5",
                "messages": [{"role": "user", "content": "hello"}],
            }

            def fake_chat_completion(channel, routed_payload):
                channel_id = str(channel.get("id"))
                calls.append((channel_id, routed_payload.get("model")))
                if channel_id == "channel-a":
                    raise RuntimeError("HTTP 500: upstream error")
                return {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": routed_payload.get("model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                }

            service._call_chat_completion = fake_chat_completion  # type: ignore[method-assign]
            routed = service.call_chat_completion(payload)

            self.assertIsNotNone(routed)
            self.assertEqual(calls, [("channel-a", "gpt-5.5"), ("channel-b", "gpt-5.5")])
            self.assertEqual(routed[1], "B")
            self.assertNotIn("_channel_error", payload)

    def test_chat_stream_retries_next_supported_channel_after_initial_request_failure(self) -> None:
        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def iter_content(self):
                yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                yield b"data: [DONE]\n\n"

        class FakeSession:
            def __init__(self, channel_id: str):
                self.channel_id = channel_id
                self.closed = False

            def post(self, url, **kwargs):
                calls.append((self.channel_id, kwargs["json"]["model"], kwargs["json"]["stream"]))
                if self.channel_id == "channel-a":
                    raise RuntimeError("connect timeout")
                return FakeResponse()

            def close(self):
                self.closed = True
                closed.append(self.channel_id)

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-a",
                        "models": ["gpt-5.5"],
                        "weight": 2,
                    },
                    {
                        "id": "channel-b",
                        "name": "B",
                        "base_url": "https://b.example",
                        "api_key": "sk-b",
                        "models": ["gpt-5.5"],
                    },
                    {
                        "id": "channel-c",
                        "name": "C",
                        "base_url": "https://c.example",
                        "api_key": "sk-c",
                        "models": ["other-text-model"],
                    },
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            calls: list[tuple[str, object, object]] = []
            closed: list[str] = []
            service._session = lambda channel: FakeSession(str(channel.get("id")))  # type: ignore[method-assign]

            routed = service.call_chat_completion_stream({
                "model": "gpt-5.5",
                "messages": [{"role": "user", "content": "hello"}],
            })

            self.assertIsNotNone(routed)
            chunks, channel_name = routed
            self.assertEqual(channel_name, "B")
            self.assertEqual(list(chunks), ["ok"])
            self.assertEqual(calls, [("channel-a", "gpt-5.5", True), ("channel-b", "gpt-5.5", True)])
            self.assertEqual(closed, ["channel-a", "channel-b"])

    def test_chat_prefers_channel_model_alias_before_image_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-5.5", "gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            seen: dict[str, object] = {}

            def fake_chat_completion(channel, payload):
                seen["channel"] = channel.get("id")
                seen["model"] = payload.get("model")
                return {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": payload.get("model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                }

            service._call_chat_completion = fake_chat_completion  # type: ignore[method-assign]
            routed = service.call_chat_completion({
                "model": "gpt-5-5",
                "messages": [{"role": "user", "content": "hello"}],
            })

            self.assertIsNotNone(routed)
            self.assertEqual(seen["channel"], "channel-a")
            self.assertEqual(seen["model"], "gpt-5.5")
            self.assertEqual(routed[1], "A")

    def test_chat_stream_delta_parser_accepts_openai_chunks(self) -> None:
        self.assertEqual(
            ChannelService._chat_stream_delta_text('{"choices":[{"delta":{"content":"hel"}}]}'),
            "hel",
        )
        self.assertEqual(
            ChannelService._chat_stream_delta_text('{"choices":[{"delta":{"content":"lo"}}]}'),
            "lo",
        )
        self.assertEqual(ChannelService._chat_stream_delta_text('{"choices":[{"delta":{}}]}'), "")

    def test_generation_does_not_use_text_model_when_image_model_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-5.5"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            seen: dict[str, object] = {}

            def fake_generation(channel, payload):
                seen["model"] = payload.get("model")
                return {"created": 1, "data": [{"url": "https://a.example/image.png"}]}

            service._call_generation = fake_generation  # type: ignore[method-assign]
            routed = service.call_generation({"prompt": "draw", "model": "gpt-image-2", "n": 1})

            self.assertIsNone(routed)
            self.assertEqual(seen, {})

    def test_personal_generation_channel_precedes_global_channels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "Global",
                        "base_url": "https://global.example",
                        "api_key": "sk-global",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            calls: list[str] = []

            def fake_generation(channel, payload):
                calls.append(str(channel.get("id")))
                return {"created": 1, "data": [{"url": "https://personal.example/image.png"}]}

            service._call_generation = fake_generation  # type: ignore[method-assign]
            routed = service.call_generation(
                {
                    "prompt": "draw",
                    "model": "gpt-image-2",
                    "n": 1,
                    "_owner_user_id": "user-a",
                    "_personal_image_channel": {
                        "enabled": True,
                        "name": "Mine",
                        "base_url": "https://personal.example",
                        "api_key": "sk-personal",
                        "models": ["gpt-image-2"],
                    },
                }
            )

            self.assertIsNotNone(routed)
            self.assertEqual(calls, ["personal_image_channel:user-a"])
            self.assertTrue(str(routed[1]).endswith("/Mine"))

    def test_personal_generation_channel_does_not_fall_back_to_global_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "Global",
                        "base_url": "https://global.example",
                        "api_key": "sk-global",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            calls: list[str] = []
            payload = {
                "prompt": "draw",
                "model": "gpt-image-2",
                "n": 1,
                "_owner_user_id": "user-a",
                "_personal_image_channel": {
                    "enabled": True,
                    "name": "Mine",
                    "base_url": "https://personal.example",
                    "api_key": "sk-personal",
                    "models": ["gpt-image-2"],
                },
            }

            def fake_generation(channel, payload):
                channel_id = str(channel.get("id"))
                calls.append(channel_id)
                if channel_id.startswith("personal_image_channel:"):
                    raise RuntimeError("Failed to perform, curl: (35) Recv failure: Connection was reset.")
                return {"created": 1, "data": [{"url": "https://global.example/image.png"}]}

            service._call_generation = fake_generation  # type: ignore[method-assign]
            routed = service.call_generation(payload)

            self.assertIsNone(routed)
            self.assertEqual(calls, ["personal_image_channel:user-a"])
            self.assertIn("Mine", payload["_personal_channel_error"])

    def test_external_generation_channel_normalizes_aspect_ratio_for_upstream(self) -> None:
        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {"created": 1, "data": [{"url": "https://a.example/image.png"}]}

        calls: dict[str, object] = {}

        class FakeSession:
            def post(self, url, **kwargs):
                calls["url"] = url
                calls["kwargs"] = kwargs
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            service._session = lambda channel: FakeSession()  # type: ignore[method-assign]

            routed = service.call_generation({
                "prompt": "draw",
                "model": "gpt-image-2",
                "n": 1,
                "size": "9:16",
                "response_format": "url",
            })

        self.assertIsNotNone(routed)
        self.assertEqual(calls["url"], "https://a.example/v1/images/generations")
        body = calls["kwargs"]["json"]
        self.assertEqual(body["size"], "1024x1536")
        self.assertTrue(body["prompt"].startswith("draw\n\n"))
        self.assertIn("9:16", body["prompt"])

    def test_external_generation_channel_applies_resolution_to_aspect_ratio(self) -> None:
        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {"created": 1, "data": [{"url": "https://a.example/image.png"}]}

        calls: dict[str, object] = {}

        class FakeSession:
            def post(self, url, **kwargs):
                calls["url"] = url
                calls["kwargs"] = kwargs
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            service._session = lambda channel: FakeSession()  # type: ignore[method-assign]

            routed = service.call_generation({
                "prompt": "draw",
                "model": "gpt-image-2",
                "n": 1,
                "size": "16:9",
                "resolution": "2k",
                "quality": "high",
                "output_format": "webp",
                "output_compression": 82,
                "moderation": "low",
                "background": "transparent",
                "response_format": "url",
            })

        self.assertIsNotNone(routed)
        body = calls["kwargs"]["json"]
        self.assertEqual(body["size"], "2560x1440")
        self.assertEqual(body["quality"], "high")
        self.assertEqual(body["output_format"], "png")
        self.assertNotIn("output_compression", body)
        self.assertEqual(body["moderation"], "low")
        self.assertNotIn("background", body)
        self.assertTrue(body["prompt"].startswith("draw\n\n"))
        self.assertIn("16:9", body["prompt"])
        self.assertIn("#00FF00", body["prompt"])
        self.assertIn("#FF00FF", body["prompt"])

    def test_external_generation_transparent_background_postprocesses_b64_response(self) -> None:
        source = Image.new("RGBA", (3, 3), (0, 255, 0, 255))
        source.putpixel((1, 1), (200, 20, 20, 255))
        buffer = BytesIO()
        source.save(buffer, format="PNG")
        source_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")

        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {"created": 1, "data": [{"b64_json": source_b64}]}

        class FakeSession:
            def post(self, url, **kwargs):
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir) / "images"
            fake_config = SimpleNamespace(
                images_dir=images_dir,
                base_url="http://127.0.0.1:8000",
                cleanup_old_images=lambda: 0,
            )
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            service._session = lambda channel: FakeSession()  # type: ignore[method-assign]

            with (
                mock.patch.object(channel_service_module, "config", fake_config),
                mock.patch.object(channel_service_module, "china_now_text", return_value="2026-05-29 08:00:00"),
            ):
                routed = service.call_generation({
                    "prompt": "draw",
                    "model": "gpt-image-2",
                    "n": 1,
                    "background": "transparent",
                    "response_format": "b64_json",
                    "base_url": "http://127.0.0.1:8000",
                })

            self.assertIsNotNone(routed)
            result, _channel = routed
            item = result["data"][0]
            output_bytes = base64.b64decode(item["b64_json"])
            with Image.open(BytesIO(output_bytes)) as output:
                output = output.convert("RGBA")
                self.assertEqual(output.getpixel((0, 0))[3], 0)
                self.assertEqual(output.getpixel((1, 1))[3], 255)
            saved_path = images_dir / item["url"].split("/images/", 1)[1]
            with Image.open(saved_path) as saved:
                self.assertEqual(saved.convert("RGBA").getpixel((0, 0))[3], 0)

    def test_external_generation_url_response_is_saved_locally(self) -> None:
        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {"created": 1, "data": [{"url": "https://gptimage.futureppo.top/image.png"}]}

        class FakeSession:
            def post(self, url, **kwargs):
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir) / "images"
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            service._session = lambda channel: FakeSession()  # type: ignore[method-assign]
            fake_config = SimpleNamespace(
                images_dir=images_dir,
                base_url="",
                cleanup_old_images=lambda: 0,
            )

            with (
                mock.patch.object(channel_service_module, "config", fake_config),
                mock.patch.object(channel_service_module, "china_now_text", return_value="2026-05-29 08:00:00"),
                mock.patch.object(channel_service_module, "_download_image_url", return_value=b"image-bytes") as download,
            ):
                routed = service.call_generation({
                    "prompt": "draw",
                    "model": "gpt-image-2",
                    "n": 1,
                    "response_format": "url",
                    "base_url": "https://site.example",
                })

            self.assertIsNotNone(routed)
            data = routed[0]["data"]
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["url"].startswith("https://site.example/images/2026/05/29/"))
            self.assertTrue(list((images_dir / "2026" / "05" / "29").glob("*.png")))
            download.assert_called_once_with("https://gptimage.futureppo.top/image.png")

    def test_external_generation_existing_local_url_is_rebased_without_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir) / "images"
            image_path = images_dir / "2026" / "05" / "29" / "image.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"image-bytes")
            fake_config = SimpleNamespace(images_dir=images_dir, base_url="", cleanup_old_images=lambda: 0)

            class FakeResponse:
                ok = True
                status_code = 200
                text = ""

                def json(self):
                    return {"created": 1, "data": [{"url": "https://old.example/images/2026/05/29/image.png"}]}

            with (
                mock.patch.object(channel_service_module, "config", fake_config),
                mock.patch.object(channel_service_module, "_download_image_url") as download,
            ):
                result = ChannelService._normalize_response(
                    FakeResponse(),
                    {"prompt": "draw", "response_format": "url", "base_url": "https://site.example"},
                )

        self.assertEqual(result["data"][0]["url"], "https://site.example/images/2026/05/29/image.png")
        download.assert_not_called()

    def test_personal_edit_channel_does_not_fall_back_to_global_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "Global",
                        "base_url": "https://global.example",
                        "api_key": "sk-global",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            calls: list[str] = []
            payload = {
                "prompt": "draw",
                "model": "gpt-image-2",
                "n": 1,
                "_owner_user_id": "user-a",
                "_personal_image_channel": {
                    "enabled": True,
                    "name": "Mine",
                    "base_url": "https://personal.example",
                    "api_key": "sk-personal",
                    "models": ["gpt-image-2"],
                },
            }

            def fake_edit(channel, routed_payload):
                channel_id = str(channel.get("id"))
                calls.append(channel_id)
                if channel_id.startswith("personal_image_channel:"):
                    raise RuntimeError("Failed to perform, curl: (35) Recv failure: Connection was reset.")
                return {"created": 1, "data": [{"url": "https://global.example/image.png"}]}

            service._call_edit = fake_edit  # type: ignore[method-assign]
            routed = service.call_edit(payload)

            self.assertIsNone(routed)
            self.assertEqual(calls, ["personal_image_channel:user-a"])
            self.assertIn("Mine", payload["_personal_channel_error"])

    def test_external_edit_channel_uses_curl_mime_multipart(self) -> None:
        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {"created": 1, "data": [{"url": "https://a.example/image.png"}]}

        calls: dict[str, object] = {}

        class FakeSession:
            def post(self, url, **kwargs):
                calls["url"] = url
                calls["kwargs"] = kwargs
                return FakeResponse()

        mime_instances = []

        class FakeCurlMime:
            def __init__(self):
                self.parts = []
                self.closed = False
                mime_instances.append(self)

            def addpart(self, name, **kwargs):
                self.parts.append({"name": name, **kwargs})

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            service._session = lambda channel: FakeSession()  # type: ignore[method-assign]

            with mock.patch("services.channel_service.CurlMime", FakeCurlMime):
                routed = service.call_edit({
                    "prompt": "draw",
                    "model": "gpt-image-2",
                    "n": 2,
                    "size": "1024x1024",
                    "quality": "medium",
                    "output_format": "jpeg",
                    "output_compression": 64,
                    "moderation": "low",
                    "background": "opaque",
                    "response_format": "url",
                    "images": [(b"image-bytes", "input.png", "image/png")],
                })

        self.assertIsNotNone(routed)
        self.assertEqual(calls["url"], "https://a.example/v1/images/edits")
        kwargs = calls["kwargs"]
        self.assertNotIn("files", kwargs)
        self.assertNotIn("data", kwargs)
        self.assertIs(kwargs["multipart"], mime_instances[0])
        self.assertTrue(mime_instances[0].closed)
        parts = mime_instances[0].parts
        self.assertIn({"name": "prompt", "data": b"draw"}, parts)
        self.assertIn({"name": "model", "data": b"gpt-image-2"}, parts)
        self.assertIn({"name": "n", "data": b"2"}, parts)
        self.assertIn({"name": "size", "data": b"1024x1024"}, parts)
        self.assertIn({"name": "quality", "data": b"medium"}, parts)
        self.assertIn({"name": "output_format", "data": b"jpeg"}, parts)
        self.assertIn({"name": "output_compression", "data": b"64"}, parts)
        self.assertIn({"name": "moderation", "data": b"low"}, parts)
        self.assertIn({"name": "background", "data": b"opaque"}, parts)
        self.assertIn({"name": "response_format", "data": b"url"}, parts)
        self.assertIn(
            {"name": "image", "filename": "input.png", "content_type": "image/png", "data": b"image-bytes"},
            parts,
        )

    def test_external_edit_channel_normalizes_aspect_ratio_for_upstream(self) -> None:
        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {"created": 1, "data": [{"url": "https://a.example/image.png"}]}

        calls: dict[str, object] = {}

        class FakeSession:
            def post(self, url, **kwargs):
                calls["url"] = url
                calls["kwargs"] = kwargs
                return FakeResponse()

        mime_instances = []

        class FakeCurlMime:
            def __init__(self):
                self.parts = []
                self.closed = False
                mime_instances.append(self)

            def addpart(self, name, **kwargs):
                self.parts.append({"name": name, **kwargs})

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            service._session = lambda channel: FakeSession()  # type: ignore[method-assign]

            with mock.patch("services.channel_service.CurlMime", FakeCurlMime):
                routed = service.call_edit({
                    "prompt": "draw",
                    "model": "gpt-image-2",
                    "n": 2,
                    "size": "9:16",
                    "response_format": "url",
                    "images": [(b"image-bytes", "input.png", "image/png")],
                })

        self.assertIsNotNone(routed)
        self.assertEqual(calls["url"], "https://a.example/v1/images/edits")
        parts = mime_instances[0].parts
        prompt_part = next(part for part in parts if part["name"] == "prompt")
        self.assertTrue(prompt_part["data"].decode("utf-8").startswith("draw\n\n"))
        self.assertIn("9:16", prompt_part["data"].decode("utf-8"))
        self.assertIn({"name": "size", "data": b"1024x1536"}, parts)

    def test_external_edit_channel_applies_resolution_to_aspect_ratio(self) -> None:
        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {"created": 1, "data": [{"url": "https://a.example/image.png"}]}

        calls: dict[str, object] = {}

        class FakeSession:
            def post(self, url, **kwargs):
                calls["url"] = url
                calls["kwargs"] = kwargs
                return FakeResponse()

        mime_instances = []

        class FakeCurlMime:
            def __init__(self):
                self.parts = []
                self.closed = False
                mime_instances.append(self)

            def addpart(self, name, **kwargs):
                self.parts.append({"name": name, **kwargs})

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-image-2"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())
            service._session = lambda channel: FakeSession()  # type: ignore[method-assign]

            with mock.patch("services.channel_service.CurlMime", FakeCurlMime):
                routed = service.call_edit({
                    "prompt": "draw",
                    "model": "gpt-image-2",
                    "n": 2,
                    "size": "3:4",
                    "resolution": "4k",
                    "response_format": "url",
                    "images": [(b"image-bytes", "input.png", "image/png")],
                })

        self.assertIsNotNone(routed)
        self.assertEqual(calls["url"], "https://a.example/v1/images/edits")
        parts = mime_instances[0].parts
        self.assertIn({"name": "size", "data": b"2160x3840"}, parts)
        prompt_part = next(part for part in parts if part["name"] == "prompt")
        self.assertIn("3:4", prompt_part["data"].decode("utf-8"))

    def test_channel_model_test_requires_requested_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            storage.save_channels(
                [
                    {
                        "id": "channel-a",
                        "name": "A",
                        "base_url": "https://a.example",
                        "api_key": "sk-test",
                        "models": ["gpt-5.5"],
                    }
                ]
            )
            service = ChannelService(storage, FakeConfigStore())

            service._fetch_external_channel_models = lambda channel: ["gpt-5.5"]  # type: ignore[method-assign]
            result = service.test_channel_models("channel-a", ["gpt-image-2"])

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["missing_models"], ["gpt-image-2"])

    def test_update_pricing_persists_and_estimates_token_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = ModelService(ChannelService(storage), FakeConfigStore())

            pricing = service.update_pricing(
                "gpt-5.5",
                {"input_price_per_million": 5, "output_price_per_million": 40, "currency": "usd"},
            )
            estimate = service.estimate_cost("gpt-5.5", prompt_tokens=1_000_000, completion_tokens=1_000_000)

            self.assertEqual(pricing["completion_ratio"], 8)
            self.assertEqual(estimate["amount"], 45)
            self.assertEqual(estimate["unit"], "usd")
            self.assertTrue(service.list_catalog()["pricing"]["gpt-5.5"]["enabled"])

    def test_fixed_price_mode_estimates_per_request_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = ModelService(ChannelService(storage), FakeConfigStore())

            service.update_pricing(
                "image-model",
                {"billing_mode": FIXED_BILLING_MODE, "model_price": 0.02, "currency": "USD"},
            )
            estimate = service.estimate_cost("image-model", prompt_tokens=999, completion_tokens=999, group_ratio=2)

            self.assertEqual(estimate["amount"], 0.04)
            self.assertEqual(estimate["unit"], "usd")

    def test_default_quota_cost_is_one_per_request_and_can_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = JSONStorageBackend(Path(tmp_dir) / "storage.json")
            service = ModelService(ChannelService(storage), FakeConfigStore())

            self.assertEqual(service.quota_cost("image-model"), 1)

            service.update_pricing("image-model", {"billing_mode": FIXED_BILLING_MODE, "model_price": 3})
            self.assertEqual(service.quota_cost("image-model"), 3)

            service.update_pricing("image-model", {"billing_mode": FIXED_BILLING_MODE, "model_price": 0.25})
            self.assertEqual(service.quota_cost("image-model"), 0.25)

    def test_completion_ratio_can_derive_output_price(self) -> None:
        pricing = normalize_model_pricing("gpt-test", {"input_price_per_million": 5, "completion_ratio": 8})

        self.assertEqual(pricing["output_price_per_million"], 40)
        self.assertEqual(pricing["completion_ratio"], 8)


if __name__ == "__main__":
    unittest.main()
