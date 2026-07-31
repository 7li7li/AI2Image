from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.channel_service import (
    ChannelService,
    DEFAULT_CHANNEL_TIMEOUT,
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_GEMINI_MODELS,
    GEMINI_CHANNEL_TYPE,
    _inline_data_from_part,
)
from services.storage.json_storage import JSONStorageBackend


class GeminiChannelServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = object.__new__(ChannelService)

    def test_normalize_preserves_gemini_channel_type_and_empty_base_url(self) -> None:
        channel = self.service._normalize(
            {
                "type": GEMINI_CHANNEL_TYPE,
                "api_key": "gemini-key",
                "models": ["gemini-3.5-flash"],
            }
        )

        self.assertIsNotNone(channel)
        assert channel is not None
        self.assertEqual(channel["type"], GEMINI_CHANNEL_TYPE)
        self.assertEqual(channel["base_url"], "")
        self.assertEqual(channel["models"], ["gemini-3.5-flash"])

    def test_create_gemini_channel_allows_empty_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ChannelService(JSONStorageBackend(Path(tmp_dir) / "storage.json"))

            channel = service.create_channel(
                {
                    "type": GEMINI_CHANNEL_TYPE,
                    "api_key": "gemini-key",
                    "models": ["gemini-3.5-flash"],
                }
            )

        self.assertEqual(channel["type"], GEMINI_CHANNEL_TYPE)
        self.assertEqual(channel["base_url"], "")
        self.assertEqual(channel["timeout"], DEFAULT_CHANNEL_TIMEOUT)

    def test_normalize_defaults_models_by_channel_type(self) -> None:
        gemini_channel = self.service._normalize(
            {
                "type": GEMINI_CHANNEL_TYPE,
                "api_key": "gemini-key",
            }
        )
        openai_channel = self.service._normalize(
            {
                "type": "openai_image",
                "base_url": "https://api.example.test",
                "api_key": "openai-key",
            }
        )

        self.assertIsNotNone(gemini_channel)
        self.assertIsNotNone(openai_channel)
        assert gemini_channel is not None
        assert openai_channel is not None
        self.assertEqual(gemini_channel["models"], DEFAULT_GEMINI_MODELS)
        self.assertNotIn("gemini-3-pro", openai_channel["models"])

    def test_gemini_url_adds_v1beta_for_top_level_domains(self) -> None:
        self.assertEqual(
            ChannelService._gemini_url(
                {"base_url": ""},
                "/models/gemini-2.5-flash-image:generateContent",
            ),
            f"{DEFAULT_GEMINI_BASE_URL}/models/gemini-2.5-flash-image:generateContent",
        )
        self.assertEqual(
            ChannelService._gemini_url(
                {"base_url": "https://generativelanguage.googleapis.com"},
                "/models/gemini-2.5-flash-image:generateContent",
            ),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent",
        )
        self.assertEqual(
            ChannelService._gemini_url(
                {"base_url": "https://newapi.example.test"},
                "/models?pageSize=1000",
            ),
            "https://newapi.example.test/v1beta/models?pageSize=1000",
        )

    def test_gemini_url_keeps_configured_api_version(self) -> None:
        self.assertEqual(
            ChannelService._gemini_url(
                {"base_url": "https://newapi.example.test/v1beta"},
                "/models/gemini-2.5-flash-image:generateContent",
            ),
            "https://newapi.example.test/v1beta/models/gemini-2.5-flash-image:generateContent",
        )
        self.assertEqual(
            ChannelService._gemini_url(
                {"base_url": "https://newapi.example.test/gemini/v1beta"},
                "/models/gemini-2.5-flash-image:generateContent",
            ),
            "https://newapi.example.test/gemini/v1beta/models/gemini-2.5-flash-image:generateContent",
        )

    def test_gemini_auth_header_matches_native_endpoint(self) -> None:
        google_session = self.service._session(
            {
                "type": GEMINI_CHANNEL_TYPE,
                "base_url": "https://generativelanguage.googleapis.com",
                "api_key": "google-key",
            }
        )
        relay_session = self.service._session(
            {
                "type": GEMINI_CHANNEL_TYPE,
                "base_url": "https://newapi.example.test",
                "api_key": "sk-newapi",
            }
        )
        try:
            self.assertEqual(google_session.headers.get("x-goog-api-key"), "google-key")
            self.assertNotIn("Authorization", google_session.headers)
            self.assertEqual(google_session.headers.get("Content-Type"), "application/json")
            self.assertEqual(relay_session.headers.get("Authorization"), "Bearer sk-newapi")
            self.assertNotIn("x-goog-api-key", relay_session.headers)
            self.assertEqual(relay_session.headers.get("Content-Type"), "application/json")
        finally:
            google_session.close()
            relay_session.close()

    def test_gemini_generate_url_matches_google_and_newapi_routes(self) -> None:
        self.assertEqual(
            self.service._gemini_generate_url(
                {
                    "type": GEMINI_CHANNEL_TYPE,
                    "base_url": "https://generativelanguage.googleapis.com",
                    "api_key": "google-key",
                },
                "gemini-3.1-flash-image",
            ),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image:generateContent",
        )
        self.assertEqual(
            self.service._gemini_generate_url(
                {
                    "type": GEMINI_CHANNEL_TYPE,
                    "base_url": "https://newapi.example.test",
                    "api_key": "sk-newapi",
                },
                "gemini-3.1-flash-image",
            ),
            "https://newapi.example.test/v1beta/models/gemini-3.1-flash-image:generateContent/",
        )
        self.assertEqual(
            self.service._gemini_generate_url(
                {
                    "type": GEMINI_CHANNEL_TYPE,
                    "base_url": "https://newapi.example.test/v1beta",
                    "api_key": "sk-newapi",
                },
                "gemini-3.1-flash-image",
                stream=True,
            ),
            "https://newapi.example.test/v1beta/models/gemini-3.1-flash-image:streamGenerateContent/?alt=sse",
        )

    def test_chat_messages_convert_to_gemini_contents(self) -> None:
        contents, system_instruction = self.service._gemini_contents_from_messages(
            [
                {"role": "system", "content": "Answer briefly."},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this."},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
                        },
                    ],
                },
            ]
        )

        self.assertEqual(system_instruction, {"parts": [{"text": "Answer briefly."}]})
        self.assertEqual(contents[0], {"role": "user", "parts": [{"text": "Hello"}]})
        self.assertEqual(contents[1], {"role": "model", "parts": [{"text": "Hi"}]})
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(
            contents[2]["parts"],
            [
                {"text": "Describe this."},
                {"inlineData": {"mimeType": "image/png", "data": "aW1hZ2U="}},
            ],
        )

    def test_gemini_text_and_inline_image_parts_are_extracted(self) -> None:
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "hello"},
                            {"inlineData": {"mimeType": "image/png", "data": "aW1hZ2U="}},
                        ]
                    }
                }
            ]
        }

        self.assertEqual(self.service._gemini_text_from_payload(payload), "hello")
        self.assertEqual(
            _inline_data_from_part(payload["candidates"][0]["content"]["parts"][1]),
            {"mimeType": "image/png", "data": "aW1hZ2U="},
        )

    def test_gemini_generation_uses_native_image_config(self) -> None:
        calls: dict[str, object] = {}

        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {
                    "candidates": [
                        {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "aW1hZ2U="}}]}}
                    ]
                }

        class FakeSession:
            def post(self, url, **kwargs):
                calls["url"] = url
                calls["kwargs"] = kwargs
                return FakeResponse()

        self.service._session = lambda channel: FakeSession()  # type: ignore[method-assign]
        with mock.patch("services.channel_service._format_image_result", return_value={"created": 1, "data": []}):
            self.service._call_generation(
                {"type": GEMINI_CHANNEL_TYPE, "base_url": "https://newapi.example.test", "timeout": 60},
                {
                    "prompt": "draw",
                    "model": "gemini-3-pro-image-preview",
                    "size": "16:9",
                    "resolution": "2k",
                    "response_format": "url",
                },
            )

        self.assertEqual(
            calls["url"],
            "https://newapi.example.test/v1beta/models/gemini-3-pro-image-preview:generateContent/",
        )
        body = calls["kwargs"]["json"]
        self.assertEqual(
            body["generationConfig"],
            {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": "16:9", "imageSize": "2K"},
            },
        )
        self.assertEqual(body["contents"], [{"role": "user", "parts": [{"text": "draw"}]}])

    def test_gemini_edit_uses_native_config_and_inline_reference_image(self) -> None:
        calls: dict[str, object] = {}

        class FakeResponse:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {
                    "candidates": [
                        {"content": {"parts": [{"inline_data": {"mime_type": "image/png", "data": "aW1hZ2U="}}]}}
                    ]
                }

        class FakeSession:
            def post(self, url, **kwargs):
                calls["url"] = url
                calls["kwargs"] = kwargs
                return FakeResponse()

        self.service._session = lambda channel: FakeSession()  # type: ignore[method-assign]
        with mock.patch("services.channel_service._format_image_result", return_value={"created": 1, "data": []}):
            self.service._call_edit(
                {"type": GEMINI_CHANNEL_TYPE, "base_url": "https://newapi.example.test", "timeout": 60},
                {
                    "prompt": "edit this",
                    "model": "gemini-3.1-flash-image-preview",
                    "size": "4:1",
                    "resolution": "4K",
                    "response_format": "url",
                    "images": [(b"image-bytes", "input.png", "image/png")],
                },
            )

        body = calls["kwargs"]["json"]
        self.assertEqual(
            calls["url"],
            "https://newapi.example.test/v1beta/models/gemini-3.1-flash-image-preview:generateContent/",
        )
        self.assertEqual(
            body["generationConfig"],
            {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": "4:1", "imageSize": "4K"},
            },
        )
        self.assertEqual(
            body["contents"],
            [
                {
                    "role": "user",
                    "parts": [
                        {"text": "edit this"},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": "aW1hZ2UtYnl0ZXM=",
                            }
                        },
                    ],
                }
            ],
        )

    def test_gemini_url_response_parses_file_data_and_localizes_it(self) -> None:
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "generated"},
                            {
                                "file_data": {
                                    "mime_type": "image/png",
                                    "file_uri": "https://files.example.test/result.png",
                                }
                            },
                        ]
                    }
                }
            ]
        }

        with mock.patch(
            "services.channel_service._localize_url_items",
            return_value=[{"url": "https://app.example.test/images/result.png"}],
        ) as localize:
            result = self.service._normalize_gemini_image_response(
                payload,
                {
                    "prompt": "draw",
                    "response_format": "url",
                    "base_url": "https://app.example.test",
                },
            )

        self.assertEqual(result["data"], [{"url": "https://app.example.test/images/result.png"}])
        localize.assert_called_once_with(
            [{"url": "https://files.example.test/result.png"}],
            "https://app.example.test",
            transparent_background=False,
        )

    def test_gemini_image_response_accepts_openai_data_items(self) -> None:
        with mock.patch(
            "services.channel_service._format_image_result",
            return_value={"created": 1, "data": [{"url": "https://app.example.test/images/result.png"}]},
        ) as formatter:
            result = self.service._normalize_gemini_image_response(
                {"data": [{"b64_json": "aW1hZ2U="}]},
                {"prompt": "draw", "response_format": "url"},
            )

        self.assertEqual(result["data"], [{"url": "https://app.example.test/images/result.png"}])
        formatter.assert_called_once()

    def test_gemini_image_response_accepts_markdown_image_url(self) -> None:
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "![generated](https://files.example.test/result.png)"},
                        ]
                    }
                }
            ]
        }

        with mock.patch(
            "services.channel_service._localize_url_items",
            return_value=[{"url": "https://app.example.test/images/result.png"}],
        ) as localize:
            result = self.service._normalize_gemini_image_response(
                payload,
                {"prompt": "draw", "response_format": "url"},
            )

        self.assertEqual(result["data"], [{"url": "https://app.example.test/images/result.png"}])
        localize.assert_called_once_with(
            [{"url": "https://files.example.test/result.png"}],
            None,
            transparent_background=False,
        )

    def test_gemini_missing_image_reports_safe_response_shape(self) -> None:
        payload = {
            "candidates": [
                {
                    "finishReason": "SAFETY",
                    "content": {"parts": [{"text": "request was blocked"}]},
                }
            ],
            "promptFeedback": {"blockReason": "SAFETY"},
        }

        with self.assertRaisesRegex(RuntimeError, "block_reason=SAFETY.*finish_reason=SAFETY.*part_keys=text"):
            self.service._normalize_gemini_image_response(payload, {"prompt": "private prompt"})

    def test_google_gemini_url_response_keeps_inline_image_modality(self) -> None:
        self.assertEqual(
            self.service._gemini_image_response_modalities(
                {
                    "type": GEMINI_CHANNEL_TYPE,
                    "base_url": "https://generativelanguage.googleapis.com",
                    "api_key": "google-key",
                },
                {"response_format": "url"},
            ),
            ["IMAGE"],
        )

    def test_rolldek_url_response_uses_documented_text_modality(self) -> None:
        self.assertEqual(
            self.service._gemini_image_response_modalities(
                {
                    "type": GEMINI_CHANNEL_TYPE,
                    "base_url": "https://rolldek.com",
                    "api_key": "relay-key",
                },
                {"response_format": "url"},
            ),
            ["TEXT"],
        )


if __name__ == "__main__":
    unittest.main()
