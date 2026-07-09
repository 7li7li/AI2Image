from __future__ import annotations

import unittest

from services.channel_service import (
    ChannelService,
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_GEMINI_MODELS,
    GEMINI_CHANNEL_TYPE,
    _inline_data_from_part,
)


class GeminiChannelServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = object.__new__(ChannelService)

    def test_normalize_preserves_gemini_channel_type_and_default_base_url(self) -> None:
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
        self.assertEqual(channel["base_url"], DEFAULT_GEMINI_BASE_URL)
        self.assertEqual(channel["models"], ["gemini-3.5-flash"])

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
            self.assertEqual(relay_session.headers.get("Authorization"), "Bearer sk-newapi")
            self.assertNotIn("x-goog-api-key", relay_session.headers)
        finally:
            google_session.close()
            relay_session.close()

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


if __name__ == "__main__":
    unittest.main()
