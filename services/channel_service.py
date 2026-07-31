from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote, urlparse

from curl_cffi import CurlMime
from curl_cffi.requests import Session

from services.config import config
from services.proxy_service import proxy_settings
from services.repositories.base import RepositoryProvider
from services.repositories.storage_adapter import RepositoryStorageAdapter
from services.storage.base import StorageBackend
from services.transparent_image import build_transparent_prompt, remove_keyed_background
from utils.timezone import china_now_text
PERSONAL_CHANNEL_ID_PREFIX = "personal_image_channel"
OPENAI_CHANNEL_TYPE = "openai_image"
GEMINI_CHANNEL_TYPE = "gemini"
SUPPORTED_CHANNEL_TYPES = {OPENAI_CHANNEL_TYPE, GEMINI_CHANNEL_TYPE}
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_OPENAI_IMAGE_MODELS = ["gpt-5.5", "gpt-image-2"]
DEFAULT_GEMINI_MODELS = [
    "gemini-3-pro-image-preview",
    "gemini-3.5-flash",
]
DEFAULT_CHANNEL_TIMEOUT = 600

DATA_IMAGE_URL_PATTERN = re.compile(r"data:image/[^;\s]+;base64,([A-Za-z0-9+/=]+)", re.IGNORECASE)
MARKDOWN_IMAGE_URL_PATTERN = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object) -> str:
    return str(value or "").strip()


def _save_image_bytes(image_data: bytes, base_url: str | None = None) -> str:
    config.cleanup_old_images()
    file_hash = hashlib.md5(image_data).hexdigest()
    filename = f"{file_hash}_{uuid.uuid4().hex}.png"
    relative_dir = Path(*china_now_text()[:10].split("-"))
    file_path = config.images_dir / relative_dir / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(image_data)
    return f"{(base_url or config.base_url)}/images/{relative_dir.as_posix()}/{filename}"


def _is_transparent_background_request(payload: dict[str, Any]) -> bool:
    return _clean(payload.get("background")).lower() == "transparent"


def _remove_keyed_background_with_fallback(image_data: bytes) -> bytes:
    try:
        return remove_keyed_background(image_data)
    except Exception as exc:
        print(f"[channel] transparent background post-processing failed: {_friendly_channel_error(exc)}")
        return image_data


def _download_image_url(image_url: str) -> bytes:
    parsed = urlparse(image_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("channel image url is invalid")
    session = Session(**proxy_settings.build_session_kwargs(verify=True))
    try:
        response = session.get(image_url, timeout=60)
    finally:
        session.close()
    if not response.ok:
        raise RuntimeError(f"channel image download failed HTTP {response.status_code}: {response.text[:200]}")
    image_data = bytes(response.content or b"")
    if not image_data:
        raise RuntimeError("channel image download is empty")
    return image_data


def _local_image_path_from_path(parsed_path: str) -> Path | None:
    if not parsed_path.startswith("/images/"):
        return None
    local_path = config.images_dir / parsed_path.removeprefix("/images/")
    return local_path if local_path.is_file() else None


def _local_image_url_from_path(parsed_path: str, base_url: str) -> str:
    local_path = _local_image_path_from_path(parsed_path)
    if local_path is None:
        return ""
    return f"{base_url.rstrip('/')}{parsed_path}"


def _localize_url_items(
        items: list[dict[str, Any]],
        base_url: str | None,
        *,
        transparent_background: bool = False,
) -> list[dict[str, Any]]:
    target_base_url = _clean(base_url) or config.base_url
    if not target_base_url:
        return items

    localized: list[dict[str, Any]] = []
    for item in items:
        image_url = _clean(item.get("url"))
        if not image_url:
            continue
        parsed = urlparse(image_url)
        parsed_path = parsed.path or image_url
        local_url = _local_image_url_from_path(parsed_path, target_base_url)
        if local_url and not transparent_background:
            localized.append({**item, "url": local_url})
            continue
        local_path = _local_image_path_from_path(parsed_path)
        image_data = local_path.read_bytes() if local_path else _download_image_url(image_url)
        if transparent_background:
            image_data = _remove_keyed_background_with_fallback(image_data)
        localized.append({**item, "url": _save_image_bytes(image_data, target_base_url)})
    return localized


def _format_image_result(
        items: list[dict[str, Any]],
        prompt: str,
        response_format: str,
        base_url: str | None = None,
        created: int | None = None,
        transparent_background: bool = False,
) -> dict[str, Any]:
    data: list[dict[str, Any]] = []
    for item in items:
        b64_json = _clean(item.get("b64_json"))
        if not b64_json:
            continue
        revised_prompt = _clean(item.get("revised_prompt") or prompt) or prompt
        image_data = base64.b64decode(b64_json)
        if transparent_background:
            image_data = _remove_keyed_background_with_fallback(image_data)
            b64_json = base64.b64encode(image_data).decode("ascii")
        saved_url = _save_image_bytes(image_data, base_url)
        if response_format == "b64_json":
            data.append({"b64_json": b64_json, "url": saved_url, "revised_prompt": revised_prompt})
        else:
            data.append({"url": saved_url, "revised_prompt": revised_prompt})
    return {"created": created or int(time.time()), "data": data}


def _bool(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _normalize_models(value: object) -> list[str]:
    if isinstance(value, list):
        return [_clean(item) for item in value if _clean(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return list(DEFAULT_OPENAI_IMAGE_MODELS)


def _default_models_for_channel(channel_type: str) -> list[str]:
    if channel_type == GEMINI_CHANNEL_TYPE:
        return list(DEFAULT_GEMINI_MODELS)
    return list(DEFAULT_OPENAI_IMAGE_MODELS)


def _normalize_channel_models(value: object, channel_type: str) -> list[str]:
    models = _normalize_models(value)
    if value is None:
        return _default_models_for_channel(channel_type)
    return models or _default_models_for_channel(channel_type)


def _requested_models(value: object) -> list[str]:
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, str):
        candidates = value.replace(";", ",").split(",")
    else:
        candidates = []
    seen: set[str] = set()
    result: list[str] = []
    for item in candidates:
        model = _clean(item)
        if model and model not in seen:
            seen.add(model)
            result.append(model)
    return result


EXTERNAL_IMAGE_MODEL_ALIASES: dict[str, list[str]] = {}

EXTERNAL_IMAGE_RATIO_SIZE_ALIASES = {
    "1:1": "1024x1024",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
    "16:9": "1536x1024",
    "4:3": "1536x1024",
    "9:16": "1024x1536",
    "3:4": "1024x1536",
    "21:9": "1536x658",
    "9:21": "816x1920",
}

EXTERNAL_IMAGE_RATIO_PROMPT_HINTS = {
    "1:1": "输出为 1:1 正方形构图，主体居中，适合正方形画幅。",
    "3:2": "输出为 3:2 横屏构图，适合宽画幅和产品展示。",
    "2:3": "输出为 2:3 竖屏构图，适合竖版海报和人物展示。",
    "16:9": "输出为 16:9 横屏构图，适合宽画幅展示。",
    "9:16": "输出为 9:16 竖屏构图，适合竖版画幅展示。",
    "4:3": "输出为 4:3 比例，兼顾宽度与高度，适合展示画面细节。",
    "3:4": "输出为 3:4 比例，纵向构图，适合人物肖像或竖向场景。",
    "21:9": "输出为 21:9 超宽幅构图，适合电影感场景和横向展示。",
    "9:21": "输出为 9:21 超高竖幅构图，适合竖向长图和移动端展示。",
}

EXTERNAL_IMAGE_RESOLUTION_SIZE_PRESETS = {
    "1k": {
        "square": "1024x1024",
        "landscape": "1536x1024",
        "portrait": "1024x1536",
    },
    "2k": {
        "square": "2048x2048",
        "landscape": "2560x1440",
        "portrait": "1440x2560",
    },
    "4k": {
        "square": "2880x2880",
        "landscape": "3840x2160",
        "portrait": "2160x3840",
    },
}

EXTERNAL_IMAGE_RATIO_RESOLUTION_SIZE_PRESETS = {
    "21:9": {
        "1k": "1920x816",
        "2k": "3120x1344",
        "4k": "3840x1648",
    },
    "9:21": {
        "1k": "816x1920",
        "2k": "1344x3120",
        "4k": "1648x3840",
    },
}

EXTERNAL_IMAGE_RATIO_DIMENSIONS = {
    "1:1": (1, 1),
    "3:2": (3, 2),
    "2:3": (2, 3),
    "16:9": (16, 9),
    "4:3": (4, 3),
    "9:16": (9, 16),
    "3:4": (3, 4),
    "21:9": (21, 9),
    "9:21": (9, 21),
}

GEMINI_COMMON_IMAGE_ASPECT_RATIOS = {
    "1:1": (1, 1),
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "3:2": (3, 2),
    "2:3": (2, 3),
    "5:4": (5, 4),
    "4:5": (4, 5),
    "21:9": (21, 9),
}

GEMINI_FLASH_IMAGE_ASPECT_RATIOS = {
    "8:1": (8, 1),
    "4:1": (4, 1),
    "1:4": (1, 4),
    "1:8": (1, 8),
}

GEMINI_IMAGE_SIZE_TIERS = {
    "1k": "1K",
    "2k": "2K",
    "4k": "4K",
}


def _dedupe_models(models: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in models:
        model = _clean(item)
        if not model or model in seen:
            continue
        seen.add(model)
        result.append(model)
    return result


def _model_alias_key(model: str) -> str:
    return model.lower().replace(".", "-")


def _data_url_to_inline_data(url: str) -> dict[str, str] | None:
    prefix, separator, data = _clean(url).partition(",")
    if not separator or not prefix.lower().startswith("data:") or ";base64" not in prefix.lower():
        return None
    mime_type = prefix[5:].split(";", 1)[0].strip() or "image/png"
    if not data.strip():
        return None
    return {"mimeType": mime_type, "data": data.strip()}


def _inline_data_from_part(part: object) -> dict[str, str] | None:
    if not isinstance(part, dict):
        return None
    inline_data = part.get("inlineData") or part.get("inline_data")
    if not isinstance(inline_data, dict):
        return None
    data = _clean(inline_data.get("data"))
    if not data:
        return None
    return {
        "mimeType": _clean(inline_data.get("mimeType") or inline_data.get("mime_type")) or "image/png",
        "data": data,
    }


def _file_data_from_part(part: object) -> dict[str, str] | None:
    if not isinstance(part, dict):
        return None
    file_data = part.get("fileData") or part.get("file_data")
    if not isinstance(file_data, dict):
        return None
    file_uri = _clean(file_data.get("fileUri") or file_data.get("file_uri") or file_data.get("url"))
    if not file_uri:
        return None
    return {
        "mimeType": _clean(file_data.get("mimeType") or file_data.get("mime_type")) or "image/png",
        "fileUri": file_uri,
    }


def _image_items_from_text(value: object) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    text = _clean(value)
    if not text:
        return [], []
    b64_items = [{"b64_json": match.group(1)} for match in DATA_IMAGE_URL_PATTERN.finditer(text)]
    url_items = [{"url": match.group(1)} for match in MARKDOWN_IMAGE_URL_PATTERN.finditer(text)]
    if not url_items and text.startswith(("http://", "https://")) and not any(char.isspace() for char in text):
        url_items.append({"url": text})
    return b64_items, url_items


def _image_items_from_mapping(value: object) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not isinstance(value, dict):
        return [], []
    b64_value = _clean(
        value.get("b64_json")
        or value.get("base64")
        or value.get("imageBase64")
        or value.get("image_base64")
        or value.get("imageBytes")
        or value.get("image_bytes")
        or value.get("bytesBase64Encoded")
        or value.get("bytes_base64_encoded")
    )
    url_value = _clean(
        value.get("url")
        or value.get("fileUri")
        or value.get("file_uri")
        or value.get("imageUrl")
        or value.get("image_url")
    )
    b64_items = [{"b64_json": b64_value}] if b64_value else []
    url_items = [{"url": url_value}] if url_value else []
    if not b64_items and not url_items and isinstance(value.get("image"), dict):
        return _image_items_from_mapping(value["image"])
    return b64_items, url_items


def _is_explicit_image_size(value: str) -> bool:
    width, separator, height = value.lower().partition("x")
    return bool(separator and width.isdigit() and height.isdigit())


def _image_orientation(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _resolve_image_resolution_size(size: str, resolution: str) -> str | None:
    normalized_resolution = resolution.lower()
    if normalized_resolution in {"", "auto"}:
        return None
    preset = EXTERNAL_IMAGE_RESOLUTION_SIZE_PRESETS.get(normalized_resolution)
    if not preset:
        return None
    ratio_preset = EXTERNAL_IMAGE_RATIO_RESOLUTION_SIZE_PRESETS.get(size)
    if ratio_preset:
        return ratio_preset[normalized_resolution]
    if _is_explicit_image_size(size):
        width, _, height = size.lower().partition("x")
        width_value = int(width)
        height_value = int(height)
        if width_value <= 0 or height_value <= 0:
            return None
        return preset[_image_orientation(width_value, height_value)]
    ratio = EXTERNAL_IMAGE_RATIO_DIMENSIONS.get(size) or EXTERNAL_IMAGE_RATIO_DIMENSIONS["1:1"]
    width_ratio, height_ratio = ratio
    return preset[_image_orientation(width_ratio, height_ratio)]


def _normalize_external_image_request(prompt: object, size: object, resolution: object = None) -> tuple[str | None, str | None]:
    normalized_prompt = _clean(prompt) or None
    normalized_size = _clean(size)
    normalized_resolution = _clean(resolution)
    resolution_size = _resolve_image_resolution_size(normalized_size, normalized_resolution)
    if resolution_size:
        hint = EXTERNAL_IMAGE_RATIO_PROMPT_HINTS.get(normalized_size)
        if hint and normalized_prompt:
            normalized_prompt = f"{normalized_prompt}\n\n{hint}"
        return normalized_prompt, resolution_size
    if not normalized_size:
        return normalized_prompt, None
    if _is_explicit_image_size(normalized_size) or normalized_size.lower() == "auto":
        return normalized_prompt, normalized_size.lower()
    mapped_size = EXTERNAL_IMAGE_RATIO_SIZE_ALIASES.get(normalized_size)
    if mapped_size:
        hint = EXTERNAL_IMAGE_RATIO_PROMPT_HINTS.get(normalized_size)
        if hint and normalized_prompt:
            normalized_prompt = f"{normalized_prompt}\n\n{hint}"
        return normalized_prompt, mapped_size
    return normalized_prompt, normalized_size


def _gemini_image_config(payload: dict[str, Any]) -> dict[str, str]:
    image_config: dict[str, str] = {}
    model = _clean(payload.get("model")).lower()
    supported_ratios = dict(GEMINI_COMMON_IMAGE_ASPECT_RATIOS)
    if "flash" in model:
        supported_ratios.update(GEMINI_FLASH_IMAGE_ASPECT_RATIOS)

    size = _clean(payload.get("size")).lower().replace(" ", "")
    aspect_ratio = size if size in supported_ratios else ""
    if not aspect_ratio and _is_explicit_image_size(size):
        width, _, height = size.partition("x")
        width_value = int(width)
        height_value = int(height)
        if width_value > 0 and height_value > 0:
            requested_ratio = width_value / height_value
            aspect_ratio, dimensions = min(
                supported_ratios.items(),
                key=lambda item: abs(requested_ratio - (item[1][0] / item[1][1])),
            )
            matched_ratio = dimensions[0] / dimensions[1]
            if abs(requested_ratio - matched_ratio) / matched_ratio > 0.02:
                aspect_ratio = ""
    if aspect_ratio:
        image_config["aspectRatio"] = aspect_ratio

    image_size = GEMINI_IMAGE_SIZE_TIERS.get(_clean(payload.get("resolution")).lower())
    if image_size:
        image_config["imageSize"] = image_size
    return image_config


def _normalize_external_image_options(payload: dict[str, Any]) -> dict[str, object]:
    options: dict[str, object] = {}
    quality = _clean(payload.get("quality")).lower()
    if quality in {"auto", "low", "medium", "high"}:
        options["quality"] = quality
    output_format = _clean(payload.get("output_format")).lower()
    background = _clean(payload.get("background")).lower()
    transparent_background = background == "transparent"
    if transparent_background:
        options["output_format"] = "png"
    elif output_format in {"png", "jpeg", "webp"}:
        options["output_format"] = output_format
    if not transparent_background and output_format in {"jpeg", "webp"}:
        try:
            output_compression = int(payload.get("output_compression"))
        except (TypeError, ValueError):
            output_compression = None
        if output_compression is not None:
            options["output_compression"] = max(0, min(100, output_compression))
    moderation = _clean(payload.get("moderation")).lower()
    if moderation in {"auto", "low"}:
        options["moderation"] = moderation
    if background in {"auto", "opaque"}:
        options["background"] = background
    return options


def _response_preview(response, limit: int = 300) -> str:
    text = _clean(getattr(response, "text", ""))
    if text:
        return text[:limit]
    return ""


def _friendly_channel_error(error: object) -> str:
    message = _clean(error)
    normalized = message.lower()
    if "curl: (35)" in normalized or "connection was reset" in normalized or "recv failure" in normalized:
        return (
            "连接被上游重置（curl 35）。请检查渠道 Base URL 是否正确、API Key 是否有效、"
            "该渠道是否允许当前网络访问；如果系统设置里配置了代理，也请确认代理可用。"
        )
    if "curl: (28)" in normalized or "timed out" in normalized or "timeout" in normalized:
        return "连接上游渠道超时。请检查渠道地址、代理、渠道超时设置或上游服务状态。"
    if "proxy" in normalized and ("connect" in normalized or "failed" in normalized or "refused" in normalized):
        return "代理连接失败。请检查系统设置里的代理地址是否可用，或暂时清空代理后重试。"
    return message


def _is_timeout_error(error: object) -> bool:
    normalized = _clean(error).lower()
    return "curl: (28)" in normalized or "timed out" in normalized or "timeout" in normalized


class ChannelService:
    def __init__(self, storage: StorageBackend | RepositoryProvider, config_store=None):
        self.repositories = storage if isinstance(storage, RepositoryProvider) else None
        self.storage = RepositoryStorageAdapter(storage) if isinstance(storage, RepositoryProvider) else storage
        self.config_store = config_store or config
        self._lock = RLock()
        self._channels = self._load()
        self._enabled_cache: tuple[float, list[dict[str, object]]] | None = None

    def _normalize(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        channel_id = _clean(raw.get("id")) or uuid.uuid4().hex[:12]
        name = _clean(raw.get("name")) or "OpenAI 图片渠道"
        channel_type = _clean(raw.get("type")) or OPENAI_CHANNEL_TYPE
        if channel_type not in SUPPORTED_CHANNEL_TYPES:
            channel_type = OPENAI_CHANNEL_TYPE
        base_url = _clean(raw.get("base_url")).rstrip("/")
        if channel_type == GEMINI_CHANNEL_TYPE and not _clean(raw.get("name")):
            name = "Gemini native channel"
        api_key = _clean(raw.get("api_key"))
        try:
            weight = max(1, int(raw.get("weight") or 1))
        except (TypeError, ValueError):
            weight = 1
        try:
            priority = int(raw.get("priority") or 0)
        except (TypeError, ValueError):
            priority = 0
        try:
            timeout = max(5, int(raw.get("timeout") or DEFAULT_CHANNEL_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_CHANNEL_TIMEOUT
        return {
            "id": channel_id,
            "name": name,
            "type": channel_type,
            "base_url": base_url,
            "api_key": api_key,
            "models": _normalize_channel_models(raw.get("models"), channel_type),
            "weight": weight,
            "priority": priority,
            "timeout": timeout,
            "enabled": bool(raw.get("enabled", True)),
            "created_at": _clean(raw.get("created_at")) or _now_iso(),
            "updated_at": _clean(raw.get("updated_at")) or _now_iso(),
        }

    def _load(self) -> list[dict[str, object]]:
        try:
            items = self.storage.load_channels()
        except Exception:
            return []
        if not isinstance(items, list):
            return []
        return [normalized for item in items if (normalized := self._normalize(item)) is not None]

    def _save(self) -> None:
        self.storage.save_channels(self._channels)

    def _invalidate_cache(self) -> None:
        self._enabled_cache = None

    def _current_channels(self, *, cache_enabled: bool = False) -> list[dict[str, object]]:
        if self.repositories is None:
            return [dict(channel) for channel in self._channels]
        if cache_enabled and self._enabled_cache is not None:
            expires_at, channels = self._enabled_cache
            if expires_at > time.monotonic():
                return [dict(channel) for channel in channels]
        channels = self._load()
        if cache_enabled:
            self._enabled_cache = (time.monotonic() + 2.0, [dict(channel) for channel in channels])
        else:
            self._channels = [dict(channel) for channel in channels]
        return [dict(channel) for channel in channels]

    @staticmethod
    def _public(channel: dict[str, object]) -> dict[str, object]:
        return {
            "id": channel.get("id"),
            "name": channel.get("name"),
            "type": channel.get("type"),
            "base_url": channel.get("base_url"),
            "models": channel.get("models"),
            "weight": channel.get("weight"),
            "priority": channel.get("priority"),
            "timeout": channel.get("timeout"),
            "enabled": bool(channel.get("enabled", True)),
            "has_api_key": bool(_clean(channel.get("api_key"))),
            "created_at": channel.get("created_at"),
            "updated_at": channel.get("updated_at"),
        }

    def _image_model_mappings(self) -> dict[str, str]:
        defaults: dict[str, str] = {}
        raw = getattr(self.config_store, "image_model_mappings", None)
        if raw is None:
            raw = self.config_store.get().get("image_model_mappings")
        if not isinstance(raw, dict):
            return defaults
        mappings = dict(defaults)
        for key, value in raw.items():
            source_model = _clean(key)
            target_model = _clean(value)
            if source_model and target_model:
                mappings[source_model] = target_model
        return mappings

    @staticmethod
    def _is_gemini_channel(channel: dict[str, object]) -> bool:
        return _clean(channel.get("type")) == GEMINI_CHANNEL_TYPE

    def _external_model_candidates(self, model: str | None) -> list[str]:
        requested = _clean(model)
        if not requested:
            return []
        mapped = _clean(self._image_model_mappings().get(requested))
        return _dedupe_models([requested, *EXTERNAL_IMAGE_MODEL_ALIASES.get(requested, []), mapped])

    def _resolve_external_model_for_channel(
            self,
            channel: dict[str, object],
            model: str | None,
    ) -> str:
        candidates = self._external_model_candidates(model)
        channel_models = _normalize_models(channel.get("models"))
        if not candidates:
            return channel_models[0] if channel_models else ""
        if not channel_models:
            return candidates[0]
        for candidate in candidates:
            if candidate in channel_models:
                return candidate
        return ""

    def _resolve_chat_model_for_channel(
            self,
            channel: dict[str, object],
            model: str | None,
    ) -> str:
        requested = _clean(model) or "gpt-5.5"
        channel_models = _normalize_models(channel.get("models"))
        if not channel_models or requested in channel_models:
            return requested
        requested_alias_key = _model_alias_key(requested)
        for channel_model in channel_models:
            if _model_alias_key(channel_model) == requested_alias_key:
                return channel_model
        mapped_image_models = [
            image_model
            for image_model, text_model in self._image_model_mappings().items()
            if _clean(text_model) == requested and _clean(image_model) in channel_models
        ]
        if mapped_image_models:
            return requested
        return ""

    def _normalize_personal_channel(
            self,
            raw: object,
            *,
            owner_user_id: str = "",
            require_enabled: bool = True,
    ) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        if require_enabled and not _bool(raw.get("enabled"), False):
            return None
        channel = self._normalize({
            **raw,
            "id": f"{PERSONAL_CHANNEL_ID_PREFIX}:{_clean(owner_user_id) or 'current'}",
            "name": _clean(raw.get("name")) or "个人生图渠道",
            "type": "openai_image",
            "weight": 1,
            "priority": 100000,
            "enabled": _bool(raw.get("enabled"), True),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
        if channel is None:
            return None
        if not _clean(channel.get("base_url")) or not _clean(channel.get("api_key")):
            return None
        channel["_personal_channel"] = True
        channel["_owner_user_id"] = _clean(owner_user_id)
        return channel

    def _enabled_personal_and_external_channels(
            self,
            model: str | None,
            personal_channel: object = None,
            *,
            owner_user_id: str = "",
    ) -> list[dict[str, object]]:
        channels: list[dict[str, object]] = []
        if isinstance(personal_channel, dict) and _bool(personal_channel.get("enabled"), False):
            personal = self._normalize_personal_channel(
                personal_channel,
                owner_user_id=owner_user_id,
                require_enabled=True,
            )
            if personal is None:
                return []
            if self._resolve_external_model_for_channel(personal, model):
                return [personal]
            return []
        personal = self._normalize_personal_channel(
            personal_channel,
            owner_user_id=owner_user_id,
            require_enabled=True,
        )
        if personal is not None and self._resolve_external_model_for_channel(personal, model):
            channels.append(personal)
        channels.extend(self._enabled_external_channels(model))
        return channels

    def _personal_channel_error(
            self,
            model: str | None,
            personal_channel: object = None,
            *,
            owner_user_id: str = "",
    ) -> str:
        if not isinstance(personal_channel, dict) or not _bool(personal_channel.get("enabled"), False):
            return ""
        personal = self._normalize_personal_channel(
            personal_channel,
            owner_user_id=owner_user_id,
            require_enabled=True,
        )
        if personal is None:
            return "personal image channel is enabled but base_url and api_key are required"
        if not self._resolve_external_model_for_channel(personal, model):
            requested = _clean(model) or "default"
            return f"personal image channel does not support requested model: {requested}"
        return ""

    def has_usable_personal_channel(
            self,
            model: str | None,
            personal_channel: object = None,
            *,
            owner_user_id: str = "",
    ) -> bool:
        if not isinstance(personal_channel, dict) or not _bool(personal_channel.get("enabled"), False):
            return False
        return not self._personal_channel_error(
            model,
            personal_channel,
            owner_user_id=owner_user_id,
        )

    @staticmethod
    def _mark_personal_channel_error(payload: dict[str, Any], error: str) -> None:
        payload["_personal_channel_error"] = error
        payload["_channel_error"] = error

    @staticmethod
    def _channel_result_name(channel: dict[str, object]) -> str:
        name = str(channel.get("name") or channel.get("id") or "").strip()
        if channel.get("_personal_channel"):
            return f"个人渠道/{name or 'personal'}"
        return name or "external_channel"

    def list_channels(self, include_internal: bool = False) -> list[dict[str, object]]:
        with self._lock:
            channels = self._current_channels()
            items = [self._public(channel) for channel in channels]
        items.sort(key=lambda item: (int(item.get("weight") or 0), int(item.get("priority") or 0)), reverse=True)
        return items

    def get_channel(self, channel_id: str, *, include_internal: bool = False) -> dict[str, object] | None:
        normalized_id = _clean(channel_id)
        with self._lock:
            for channel in self._current_channels():
                if channel.get("id") == normalized_id:
                    return self._public(channel)
        return None

    def create_channel(self, data: dict[str, object]) -> dict[str, object]:
        channel = self._normalize({**data, "id": uuid.uuid4().hex[:12], "created_at": _now_iso(), "updated_at": _now_iso()})
        if channel is None:
            raise ValueError("channel payload is invalid")
        if channel.get("type") != GEMINI_CHANNEL_TYPE and not _clean(channel.get("base_url")):
            raise ValueError("base_url is required")
        if not _clean(channel.get("api_key")):
            raise ValueError("api_key is required")
        with self._lock:
            if self.repositories is not None:
                self.repositories.channels.upsert(dict(channel))
                self._channels = self._load()
            else:
                self._channels.append(channel)
                self._save()
            self._invalidate_cache()
            return self._public(channel)

    def update_channel(self, channel_id: str, updates: dict[str, object]) -> dict[str, object] | None:
        normalized_id = _clean(channel_id)
        with self._lock:
            channels = self._current_channels()
            for index, channel in enumerate(channels):
                if channel.get("id") != normalized_id:
                    continue
                merged = {**channel, **{key: value for key, value in updates.items() if value is not None}}
                merged["id"] = normalized_id
                merged["updated_at"] = _now_iso()
                normalized = self._normalize(merged)
                if normalized is None:
                    return None
                if self.repositories is not None:
                    self.repositories.channels.upsert(dict(normalized))
                    self._channels = self._load()
                else:
                    self._channels[index] = normalized
                    self._save()
                self._invalidate_cache()
                return self._public(normalized)
        return None

    def delete_channel(self, channel_id: str) -> bool:
        normalized_id = _clean(channel_id)
        with self._lock:
            if self.repositories is not None:
                removed = self.repositories.channels.delete(normalized_id)
                if removed:
                    self._channels = self._load()
                    self._invalidate_cache()
                return removed
            before = len(self._channels)
            self._channels = [channel for channel in self._channels if channel.get("id") != normalized_id]
            if len(self._channels) == before:
                return False
            self._save()
            self._invalidate_cache()
            return True

    @staticmethod
    def extract_model_ids(payload: object) -> list[str]:
        if isinstance(payload, dict):
            candidates = payload.get("data")
            if not isinstance(candidates, list):
                candidates = payload.get("models")
            if not isinstance(candidates, list):
                candidates = payload.get("items")
        else:
            candidates = payload
        if not isinstance(candidates, list):
            return []

        seen: set[str] = set()
        models: list[str] = []
        for item in candidates:
            if isinstance(item, str):
                model = _clean(item)
            elif isinstance(item, dict):
                model = _clean(item.get("id") or item.get("model") or item.get("name") or item.get("slug"))
            else:
                model = ""
            if not model or model in seen:
                continue
            seen.add(model)
            models.append(model)
        return models

    def _find_external_channel(self, channel_id: str) -> dict[str, object] | None:
        with self._lock:
            return next((dict(item) for item in self._current_channels() if item.get("id") == channel_id), None)

    def _fetch_external_channel_models(self, channel: dict[str, object]) -> list[str]:
        if self._is_gemini_channel(channel):
            return self._fetch_gemini_channel_models(channel)
        url = self._openai_compatible_url(channel, "/v1/models")
        response = self._session(channel).get(
            url,
            timeout=int(channel.get("timeout") or DEFAULT_CHANNEL_TIMEOUT),
        )
        if not response.ok:
            detail = _response_preview(response)
            suffix = f"：{detail}" if detail else ""
            if int(response.status_code) in {404, 405}:
                raise RuntimeError(
                    f"渠道模型列表接口不可用：GET /v1/models 返回 HTTP {response.status_code}{suffix}。"
                    "该渠道可能不支持模型列表接口；可保存渠道后直接生图，或更换支持 /v1/models 的 OpenAI 兼容地址。"
                )
            raise RuntimeError(f"模型列表请求失败：HTTP {response.status_code}{suffix}")
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError("channel model response is invalid") from exc
        models = self.extract_model_ids(payload)
        if not models:
            raise RuntimeError("channel model response contains no models")
        return models

    def _fetch_gemini_channel_models(self, channel: dict[str, object]) -> list[str]:
        response = self._session(channel).get(
            self._gemini_url(channel, "/models?pageSize=1000"),
            timeout=int(channel.get("timeout") or DEFAULT_CHANNEL_TIMEOUT),
        )
        if not response.ok:
            raise RuntimeError(f"gemini model list request failed HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        candidates = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(candidates, list):
            raise RuntimeError("gemini model response contains no models")
        seen: set[str] = set()
        models: list[str] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            actions = item.get("supportedGenerationMethods") or item.get("supported_actions") or []
            if isinstance(actions, list) and actions and "generateContent" not in actions:
                continue
            model = _clean(item.get("baseModelId") or item.get("base_model_id"))
            if not model:
                model = _clean(item.get("name")).removeprefix("models/")
            if not model or model in seen:
                continue
            seen.add(model)
            models.append(model)
        if not models:
            raise RuntimeError("gemini model response contains no generateContent models")
        return models

    def fetch_channel_models(self, channel_id: str) -> list[str] | None:
        normalized_id = _clean(channel_id)
        channel = self._find_external_channel(normalized_id)
        if channel is None:
            return None
        return self._fetch_external_channel_models(channel)

    def test_channel_models(self, channel_id: str, models: object = None) -> dict[str, object] | None:
        normalized_id = _clean(channel_id)
        requested_models = _requested_models(models)
        started_at = time.monotonic()
        channel = self._find_external_channel(normalized_id)
        if channel is None:
            return None
        try:
            models = self._fetch_external_channel_models(channel)
            model_set = set(models)
            tested_models = requested_models or models
            missing_models = [
                model
                for model in requested_models
                if not any(candidate in model_set for candidate in self._external_model_candidates(model))
            ]
            ok = not missing_models
            return {
                "ok": ok,
                "channel": self._public(channel),
                "models": models,
                "model_count": len(models),
                "tested_models": tested_models,
                "missing_models": missing_models,
                "latency_ms": int((time.monotonic() - started_at) * 1000),
                "error": "" if ok else f"models unavailable: {', '.join(missing_models)}",
            }
        except Exception as exc:
            return {
                "ok": False,
                "channel": self._public(channel),
                "models": [],
                "model_count": 0,
                "tested_models": requested_models,
                "missing_models": requested_models,
                "latency_ms": int((time.monotonic() - started_at) * 1000),
                "error": str(exc),
            }

    def test_personal_channel_models(
            self,
            channel_config: object,
            models: object = None,
            *,
            owner_user_id: str = "",
    ) -> dict[str, object]:
        requested_models = _requested_models(models)
        started_at = time.monotonic()
        channel = self._normalize_personal_channel(
            channel_config,
            owner_user_id=owner_user_id,
            require_enabled=False,
        )
        if channel is None:
            return {
                "ok": False,
                "channel": {
                    "id": f"{PERSONAL_CHANNEL_ID_PREFIX}:{_clean(owner_user_id) or 'current'}",
                    "name": "个人生图渠道",
                    "type": "openai_image",
                    "base_url": "",
                    "models": [],
                    "weight": 1,
                    "priority": 0,
                    "timeout": DEFAULT_CHANNEL_TIMEOUT,
                    "enabled": False,
                    "has_api_key": False,
                    "created_at": None,
                    "updated_at": None,
                },
                "models": [],
                "model_count": 0,
                "tested_models": requested_models,
                "missing_models": requested_models,
                "latency_ms": int((time.monotonic() - started_at) * 1000),
                "error": "personal image channel base_url and api_key are required",
            }
        try:
            models = self._fetch_external_channel_models(channel)
            model_set = set(models)
            tested_models = requested_models or models
            missing_models = [
                model
                for model in requested_models
                if not any(candidate in model_set for candidate in self._external_model_candidates(model))
            ]
            ok = not missing_models
            return {
                "ok": ok,
                "channel": self._public(channel),
                "models": models,
                "model_count": len(models),
                "tested_models": tested_models,
                "missing_models": missing_models,
                "latency_ms": int((time.monotonic() - started_at) * 1000),
                "error": "" if ok else f"models unavailable: {', '.join(missing_models)}",
            }
        except Exception as exc:
            return {
                "ok": False,
                "channel": self._public(channel),
                "models": [],
                "model_count": 0,
                "tested_models": requested_models,
                "missing_models": requested_models,
                "latency_ms": int((time.monotonic() - started_at) * 1000),
                "error": str(exc),
            }

    def refresh_channel_models(self, channel_id: str) -> dict[str, object] | None:
        normalized_id = _clean(channel_id)
        models = self.fetch_channel_models(normalized_id)
        if models is None:
            return None
        item = self.update_channel(normalized_id, {"models": models})
        if item is None:
            return None
        return {"channel": item, "models": models}

    def _enabled_external_channels(self, model: str | None = None) -> list[dict[str, object]]:
        with self._lock:
            channels = [
                dict(channel)
                for channel in self._current_channels(cache_enabled=True)
                if bool(channel.get("enabled", True))
            ]
        if model:
            channels = [
                channel
                for channel in channels
                if self._resolve_external_model_for_channel(channel, model)
            ]
        return self._weighted_distinct_channels(channels)

    def _enabled_external_chat_channels(self, model: str | None = None) -> list[dict[str, object]]:
        with self._lock:
            channels = [
                dict(channel)
                for channel in self._current_channels(cache_enabled=True)
                if bool(channel.get("enabled", True))
            ]
        if model:
            channels = [
                channel
                for channel in channels
                if self._resolve_chat_model_for_channel(channel, model)
            ]
        return self._weighted_distinct_channels(channels)

    @staticmethod
    def _weighted_distinct_channels(channels: list[dict[str, object]]) -> list[dict[str, object]]:
        selected: list[dict[str, object]] = []
        seen: set[str] = set()
        ordered = sorted(
            channels,
            key=lambda channel: (int(channel.get("weight") or 0), int(channel.get("priority") or 0)),
            reverse=True,
        )
        for channel in ordered:
            channel_id = _clean(channel.get("id"))
            if channel_id in seen:
                continue
            seen.add(channel_id)
            selected.append(dict(channel))
        return selected

    def has_external_channels(self, model: str | None = None) -> bool:
        return bool(self._enabled_external_channels(model))

    def _record_image_channel_attempt(
            self,
            payload: dict[str, Any],
            channel: dict[str, object],
            routed_payload: dict[str, Any],
            *,
            status: str,
            elapsed_ms: int,
    ) -> None:
        attempts = payload.get("_channel_attempts")
        if not isinstance(attempts, list):
            attempts = []
            payload["_channel_attempts"] = attempts
        attempt: dict[str, object] = {
            "channel": self._channel_result_name(channel),
            "channel_type": _clean(channel.get("type")),
            "model": _clean(routed_payload.get("model")),
            "status": status,
            "elapsed_ms": max(0, int(elapsed_ms)),
            "has_reference_images": bool(routed_payload.get("images")),
        }
        if self._is_gemini_channel(channel):
            image_config = _gemini_image_config(routed_payload)
            attempt.update({
                "aspect_ratio": image_config.get("aspectRatio") or "auto",
                "image_size": image_config.get("imageSize") or "auto",
                "response_format": _clean(routed_payload.get("response_format")) or "b64_json",
                "response_modalities": self._gemini_image_response_modalities(channel, routed_payload),
            })
        attempts.append(attempt)

    def _image_channel_error(
            self,
            channel: dict[str, object],
            routed_payload: dict[str, Any],
            error: object,
            *,
            elapsed_ms: int,
    ) -> str:
        friendly = _friendly_channel_error(error)
        if not self._is_gemini_channel(channel) or not _is_timeout_error(error):
            return friendly
        image_config = _gemini_image_config(routed_payload)
        aspect_ratio = image_config.get("aspectRatio") or "auto"
        image_size = image_config.get("imageSize") or "auto"
        elapsed_seconds = max(1, round(elapsed_ms / 1000))
        return (
            f"{friendly} 本次 Gemini 生图参数为 {aspect_ratio} / {image_size}，"
            f"已等待约 {elapsed_seconds} 秒；高分辨率任务可先尝试 1K/2K。"
        )

    def call_generation(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
        model = _clean(payload.get("model")) or "gpt-image-2"
        errors: list[str] = []
        personal_error = self._personal_channel_error(
            model,
            payload.get("_personal_image_channel"),
            owner_user_id=_clean(payload.get("_owner_user_id")),
        )
        if personal_error:
            self._mark_personal_channel_error(payload, personal_error)
            return None
        personal_required = (
            isinstance(payload.get("_personal_image_channel"), dict)
            and _bool(payload["_personal_image_channel"].get("enabled"), False)
        )
        for channel in self._enabled_personal_and_external_channels(
                model,
                payload.get("_personal_image_channel"),
                owner_user_id=_clean(payload.get("_owner_user_id")),
        ):
            resolved_model = self._resolve_external_model_for_channel(channel, model)
            routed_payload = {**payload, "model": resolved_model or model}
            started_at = time.monotonic()
            try:
                result = self._call_generation(channel, routed_payload)
                self._record_image_channel_attempt(
                    payload,
                    channel,
                    routed_payload,
                    status="success",
                    elapsed_ms=round((time.monotonic() - started_at) * 1000),
                )
                return result, self._channel_result_name(channel)
            except Exception as exc:
                elapsed_ms = round((time.monotonic() - started_at) * 1000)
                self._record_image_channel_attempt(
                    payload,
                    channel,
                    routed_payload,
                    status="error",
                    elapsed_ms=elapsed_ms,
                )
                error = self._image_channel_error(
                    channel,
                    routed_payload,
                    exc,
                    elapsed_ms=elapsed_ms,
                )
                errors.append(f"{self._channel_result_name(channel)}: {error}")
                print(f"[channel] generation failed channel={channel.get('name')} error={error}")
        if errors:
            message = "; ".join(errors)
            print(f"[channel] all external generation channels failed: {message}")
            payload["_channel_error"] = message
            if personal_required:
                payload["_personal_channel_error"] = message
        return None

    def call_edit(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
        model = _clean(payload.get("model")) or "gpt-image-2"
        errors: list[str] = []
        personal_error = self._personal_channel_error(
            model,
            payload.get("_personal_image_channel"),
            owner_user_id=_clean(payload.get("_owner_user_id")),
        )
        if personal_error:
            self._mark_personal_channel_error(payload, personal_error)
            return None
        personal_required = (
            isinstance(payload.get("_personal_image_channel"), dict)
            and _bool(payload["_personal_image_channel"].get("enabled"), False)
        )
        for channel in self._enabled_personal_and_external_channels(
                model,
                payload.get("_personal_image_channel"),
                owner_user_id=_clean(payload.get("_owner_user_id")),
        ):
            resolved_model = self._resolve_external_model_for_channel(channel, model)
            routed_payload = {**payload, "model": resolved_model or model}
            started_at = time.monotonic()
            try:
                result = self._call_edit(channel, routed_payload)
                self._record_image_channel_attempt(
                    payload,
                    channel,
                    routed_payload,
                    status="success",
                    elapsed_ms=round((time.monotonic() - started_at) * 1000),
                )
                return result, self._channel_result_name(channel)
            except Exception as exc:
                elapsed_ms = round((time.monotonic() - started_at) * 1000)
                self._record_image_channel_attempt(
                    payload,
                    channel,
                    routed_payload,
                    status="error",
                    elapsed_ms=elapsed_ms,
                )
                error = self._image_channel_error(
                    channel,
                    routed_payload,
                    exc,
                    elapsed_ms=elapsed_ms,
                )
                errors.append(f"{self._channel_result_name(channel)}: {error}")
                print(f"[channel] edit failed channel={channel.get('name')} error={error}")
        if errors:
            message = "; ".join(errors)
            print(f"[channel] all external edit channels failed: {message}")
            payload["_channel_error"] = message
            if personal_required:
                payload["_personal_channel_error"] = message
        return None

    def call_chat_completion(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
        model = _clean(payload.get("model")) or "gpt-5.5"
        errors: list[str] = []
        for channel in self._enabled_external_chat_channels(model):
            resolved_model = self._resolve_chat_model_for_channel(channel, model)
            routed_payload = {**payload, "model": resolved_model or model}
            try:
                return self._call_chat_completion(channel, routed_payload), self._channel_result_name(channel)
            except Exception as exc:
                error = _friendly_channel_error(exc)
                errors.append(f"{self._channel_result_name(channel)}: {error}")
                print(f"[channel] chat failed channel={channel.get('name')} error={error}")
        if errors:
            message = "; ".join(errors)
            print(f"[channel] all external chat channels failed: {message}")
            payload["_channel_error"] = message
        return None

    def call_chat_completion_stream(self, payload: dict[str, Any]):
        model = _clean(payload.get("model")) or "gpt-5.5"
        errors: list[str] = []
        for channel in self._enabled_external_chat_channels(model):
            resolved_model = self._resolve_chat_model_for_channel(channel, model)
            routed_payload = {**payload, "model": resolved_model or model, "stream": True}
            try:
                return self._call_chat_completion_stream(channel, routed_payload), self._channel_result_name(channel)
            except Exception as exc:
                error = _friendly_channel_error(exc)
                errors.append(f"{self._channel_result_name(channel)}: {error}")
                print(f"[channel] chat stream failed channel={channel.get('name')} error={error}")
        if errors:
            message = "; ".join(errors)
            print(f"[channel] all external chat stream channels failed: {message}")
            payload["_channel_error"] = message
        return None

    def _gemini_model_resource(self, model: object) -> str:
        model_id = _clean(model)
        if not model_id:
            raise ValueError("gemini model is required")
        if model_id.startswith("models/"):
            return "/".join(quote(part, safe="") for part in model_id.split("/"))
        return f"models/{quote(model_id, safe='')}"

    def _gemini_generate_url(self, channel: dict[str, object], model: object, *, stream: bool = False) -> str:
        method = "streamGenerateContent" if stream else "generateContent"
        url = self._gemini_url(channel, f"/{self._gemini_model_resource(model)}:{method}")
        if not self._gemini_uses_google_api_key_header(channel):
            url = f"{url}/"
        return f"{url}?alt=sse" if stream else url

    def _gemini_text_part(self, value: object) -> dict[str, str] | None:
        text = _clean(value)
        return {"text": text} if text else None

    def _gemini_parts_from_chat_content(self, content: object) -> list[dict[str, object]]:
        if isinstance(content, list):
            parts: list[dict[str, object]] = []
            for item in content:
                if isinstance(item, str):
                    part = self._gemini_text_part(item)
                    if part:
                        parts.append(part)
                    continue
                if not isinstance(item, dict):
                    continue
                item_type = _clean(item.get("type")).lower()
                if item_type == "text":
                    part = self._gemini_text_part(item.get("text") or item.get("content"))
                    if part:
                        parts.append(part)
                    continue
                if item_type == "image_url":
                    image_url = item.get("image_url")
                    if isinstance(image_url, dict):
                        url = _clean(image_url.get("url"))
                    else:
                        url = _clean(image_url)
                    inline_data = _data_url_to_inline_data(url)
                    if inline_data:
                        parts.append({"inlineData": inline_data})
                    elif url:
                        parts.append({"text": f"Image URL: {url}"})
            return parts
        part = self._gemini_text_part(content)
        return [part] if part else []

    def _gemini_contents_from_messages(self, messages: object) -> tuple[list[dict[str, object]], dict[str, object] | None]:
        if not isinstance(messages, list) or not messages:
            raise ValueError("chat messages are required")
        contents: list[dict[str, object]] = []
        system_parts: list[dict[str, object]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = _clean(message.get("role")).lower()
            parts = self._gemini_parts_from_chat_content(message.get("content"))
            if not parts:
                continue
            if role == "system":
                system_parts.extend(parts)
                continue
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": parts,
            })
        if not contents:
            raise ValueError("chat messages are required")
        system_instruction = {"parts": system_parts} if system_parts else None
        return contents, system_instruction

    def _gemini_generation_config(
            self,
            payload: dict[str, Any],
            *,
            image: bool = False,
            response_modalities: list[str] | None = None,
    ) -> dict[str, object]:
        config_payload: dict[str, object] = {}
        if image:
            config_payload["responseModalities"] = response_modalities or ["IMAGE"]
            image_config = _gemini_image_config(payload)
            if image_config:
                config_payload["imageConfig"] = image_config
        for source, target in {
            "temperature": "temperature",
            "top_p": "topP",
            "max_tokens": "maxOutputTokens",
            "max_completion_tokens": "maxOutputTokens",
        }.items():
            value = payload.get(source)
            if value is not None and value != "":
                config_payload[target] = value
        stop = payload.get("stop")
        if isinstance(stop, str) and stop:
            config_payload["stopSequences"] = [stop]
        elif isinstance(stop, list):
            config_payload["stopSequences"] = [_clean(item) for item in stop if _clean(item)]
        return config_payload

    def _gemini_request_body(
            self,
            payload: dict[str, Any],
            contents: list[dict[str, object]],
            *,
            image: bool = False,
            system_instruction: dict[str, object] | None = None,
            response_modalities: list[str] | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {"contents": contents}
        generation_config = self._gemini_generation_config(
            payload,
            image=image,
            response_modalities=response_modalities,
        )
        if generation_config:
            body["generationConfig"] = generation_config
        if system_instruction:
            body["systemInstruction"] = system_instruction
        return body

    def _gemini_image_contents(self, payload: dict[str, Any], prompt: str) -> list[dict[str, object]]:
        parts: list[dict[str, object]] = [{"text": prompt}]
        for image in payload.get("images") or []:
            if not isinstance(image, tuple) or len(image) != 3:
                continue
            data, _filename, content_type = image
            if not isinstance(data, bytes) or not data:
                continue
            parts.append({
                "inlineData": {
                    "mimeType": content_type or "image/png",
                    "data": base64.b64encode(data).decode("ascii"),
                }
            })
        return [{"role": "user", "parts": parts}]

    def _gemini_candidate_parts(self, payload: object) -> list[dict[str, object]]:
        if not isinstance(payload, dict):
            return []
        parts: list[dict[str, object]] = []
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            return parts
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            candidate_parts = content.get("parts")
            if isinstance(candidate_parts, list):
                parts.extend(part for part in candidate_parts if isinstance(part, dict))
        return parts

    def _gemini_text_from_payload(self, payload: object) -> str:
        texts: list[str] = []
        for part in self._gemini_candidate_parts(payload):
            text = part.get("text")
            if isinstance(text, str):
                texts.append(text)
        return "".join(texts)

    def _gemini_openai_chat_response(
            self,
            payload: object,
            model: str,
            request_id: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("gemini chat response is invalid")
        content = self._gemini_text_from_payload(payload)
        return {
            "id": f"chatcmpl-{request_id or uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": payload.get("usageMetadata") or payload.get("usage_metadata") or {},
        }

    def _gemini_image_response_diagnostic(self, payload: dict[str, Any]) -> str:
        details = [f"top_level={','.join(sorted(str(key) for key in payload.keys())) or 'empty'}"]
        prompt_feedback = payload.get("promptFeedback") or payload.get("prompt_feedback")
        if isinstance(prompt_feedback, dict):
            block_reason = _clean(prompt_feedback.get("blockReason") or prompt_feedback.get("block_reason"))
            if block_reason:
                details.append(f"block_reason={block_reason}")

        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            details.append(f"candidates={len(candidates)}")
            finish_reasons: list[str] = []
            part_shapes: list[str] = []
            for candidate in candidates[:4]:
                if not isinstance(candidate, dict):
                    continue
                finish_reason = _clean(candidate.get("finishReason") or candidate.get("finish_reason"))
                if finish_reason and finish_reason not in finish_reasons:
                    finish_reasons.append(finish_reason)
                content = candidate.get("content")
                parts = content.get("parts") if isinstance(content, dict) else None
                if isinstance(parts, list):
                    for part in parts[:6]:
                        if isinstance(part, dict):
                            shape = "+".join(sorted(str(key) for key in part.keys())) or "empty"
                            if shape not in part_shapes:
                                part_shapes.append(shape)
            if finish_reasons:
                details.append(f"finish_reason={','.join(finish_reasons)}")
            if part_shapes:
                details.append(f"part_keys={','.join(part_shapes)}")

        for key in ("data", "images", "predictions", "generatedImages", "generated_images"):
            items = payload.get(key)
            if isinstance(items, list):
                item_shapes = []
                for item in items[:4]:
                    if isinstance(item, dict):
                        shape = "+".join(sorted(str(item_key) for item_key in item.keys())) or "empty"
                    else:
                        shape = type(item).__name__
                    if shape not in item_shapes:
                        item_shapes.append(shape)
                details.append(f"{key}={len(items)}[{','.join(item_shapes)}]")
        return "; ".join(details)

    def _normalize_gemini_image_response(self, payload: object, original_payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("gemini image response is invalid")
        upstream_error = payload.get("error")
        if isinstance(upstream_error, dict):
            error_code = _clean(upstream_error.get("code") or upstream_error.get("type"))
            error_message = _clean(upstream_error.get("message") or upstream_error.get("detail"))
            error_detail = ": ".join(part for part in (error_code, error_message) if part)
            raise RuntimeError(f"gemini upstream error: {error_detail or 'unknown error'}")

        b64_items: list[dict[str, Any]] = []
        url_items: list[dict[str, Any]] = []
        for part in self._gemini_candidate_parts(payload):
            inline_data = _inline_data_from_part(part)
            if inline_data:
                data = _clean(inline_data.get("data"))
                if data:
                    b64_items.append({"b64_json": data})
            file_data = _file_data_from_part(part)
            if file_data:
                url_items.append({"url": file_data["fileUri"]})
            mapped_b64_items, mapped_url_items = _image_items_from_mapping(part)
            b64_items.extend(mapped_b64_items)
            url_items.extend(mapped_url_items)
            text_b64_items, text_url_items = _image_items_from_text(part.get("text"))
            b64_items.extend(text_b64_items)
            url_items.extend(text_url_items)

        for key in ("data", "images", "predictions", "generatedImages", "generated_images"):
            items = payload.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                mapped_b64_items, mapped_url_items = _image_items_from_mapping(item)
                b64_items.extend(mapped_b64_items)
                url_items.extend(mapped_url_items)
                if isinstance(item, str):
                    text_b64_items, text_url_items = _image_items_from_text(item)
                    b64_items.extend(text_b64_items)
                    url_items.extend(text_url_items)
        if not b64_items and not url_items:
            diagnostic = self._gemini_image_response_diagnostic(payload)
            raise RuntimeError(f"gemini response missing image data ({diagnostic})")

        response_format = _clean(original_payload.get("response_format")) or "url"
        base_url = _clean(original_payload.get("base_url")) or None
        transparent_background = _is_transparent_background_request(original_payload)
        localized_url_items = _localize_url_items(
            url_items,
            base_url,
            transparent_background=transparent_background,
        )
        if b64_items:
            result = _format_image_result(
                b64_items,
                _clean(original_payload.get("prompt")),
                response_format,
                base_url,
                transparent_background=transparent_background,
            )
            if localized_url_items:
                result["data"].extend(localized_url_items)
            return result
        return {"created": int(time.time()), "data": localized_url_items}

    def _gemini_image_response_modalities(
            self,
            channel: dict[str, object],
            payload: dict[str, Any],
    ) -> list[str]:
        response_format = _clean(payload.get("response_format")).lower()
        if response_format == "url" and self._gemini_supports_file_url_response(channel):
            return ["TEXT"]
        return ["IMAGE"]

    def _call_gemini_generation(self, channel: dict[str, object], payload: dict[str, Any]) -> dict[str, Any]:
        prompt = _clean(payload.get("prompt"))
        requested_size = _clean(payload.get("size"))
        image_config = _gemini_image_config(payload)
        if requested_size and requested_size.lower() != "auto" and "aspectRatio" not in image_config:
            prompt = f"{prompt}\n\nRequested image size or aspect ratio: {requested_size}".strip()
        if _is_transparent_background_request(payload):
            prompt = build_transparent_prompt(prompt)
        body = self._gemini_request_body(
            payload,
            self._gemini_image_contents(payload, prompt),
            image=True,
            response_modalities=self._gemini_image_response_modalities(channel, payload),
        )
        response = self._session(channel).post(
            self._gemini_generate_url(channel, payload.get("model")),
            json=body,
            timeout=int(channel.get("timeout") or DEFAULT_CHANNEL_TIMEOUT),
        )
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        return self._normalize_gemini_image_response(response.json(), payload)

    def _call_gemini_chat_completion(self, channel: dict[str, object], payload: dict[str, Any]) -> dict[str, Any]:
        model = _clean(payload.get("model")) or (channel.get("models") or [DEFAULT_GEMINI_MODELS[0]])[0]
        contents, system_instruction = self._gemini_contents_from_messages(payload.get("messages"))
        body = self._gemini_request_body(payload, contents, system_instruction=system_instruction)
        response = self._session(channel).post(
            self._gemini_generate_url(channel, model),
            json=body,
            timeout=int(channel.get("timeout") or DEFAULT_CHANNEL_TIMEOUT),
        )
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        return self._gemini_openai_chat_response(response.json(), model, _clean(payload.get("request_id")))

    def _call_gemini_chat_completion_stream(self, channel: dict[str, object], payload: dict[str, Any]):
        model = _clean(payload.get("model")) or (channel.get("models") or [DEFAULT_GEMINI_MODELS[0]])[0]
        contents, system_instruction = self._gemini_contents_from_messages(payload.get("messages"))
        body = self._gemini_request_body(payload, contents, system_instruction=system_instruction)
        session = self._session(channel)
        try:
            response = session.post(
                self._gemini_generate_url(channel, model, stream=True),
                json=body,
                timeout=int(channel.get("timeout") or DEFAULT_CHANNEL_TIMEOUT),
                stream=True,
            )
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        except Exception:
            session.close()
            raise

        def chunks():
            try:
                pending = b""
                for chunk in response.iter_content():
                    if not chunk:
                        continue
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    pending += chunk
                    lines = pending.split(b"\n")
                    pending = lines.pop() if lines else b""
                    for raw_line in lines:
                        text = raw_line.rstrip(b"\r").decode("utf-8", errors="replace").strip()
                        if not text:
                            continue
                        if text.startswith("data:"):
                            text = text.removeprefix("data:").strip()
                        if not text or text == "[DONE]":
                            continue
                        try:
                            event_payload = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        delta = self._gemini_text_from_payload(event_payload)
                        if delta:
                            yield delta
                if pending:
                    text = pending.rstrip(b"\r").decode("utf-8", errors="replace").strip()
                    if text.startswith("data:"):
                        text = text.removeprefix("data:").strip()
                    if text:
                        try:
                            event_payload = json.loads(text)
                        except json.JSONDecodeError:
                            event_payload = None
                        delta = self._gemini_text_from_payload(event_payload)
                        if delta:
                            yield delta
            finally:
                session.close()

        return chunks()

    def _call_generation(self, channel: dict[str, object], payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_gemini_channel(channel):
            return self._call_gemini_generation(channel, payload)
        prompt, size = _normalize_external_image_request(
            payload.get("prompt"),
            payload.get("size"),
            payload.get("resolution"),
        )
        if _is_transparent_background_request(payload) and prompt is not None:
            prompt = build_transparent_prompt(prompt)
        body = {
            key: value
            for key, value in payload.items()
            if key in {"model", "n", "response_format"} and value is not None
        }
        body.update(_normalize_external_image_options(payload))
        if prompt is not None:
            body["prompt"] = prompt
        if size is not None:
            body["size"] = size
        if "model" not in body:
            body["model"] = (channel.get("models") or ["gpt-image-1"])[0]
        response = self._session(channel).post(
            self._openai_compatible_url(channel, "/v1/images/generations"),
            json=body,
            timeout=int(channel.get("timeout") or DEFAULT_CHANNEL_TIMEOUT),
        )
        return self._normalize_response(response, payload)

    def _call_edit(self, channel: dict[str, object], payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_gemini_channel(channel):
            return self._call_gemini_generation(channel, payload)
        prompt, size = _normalize_external_image_request(
            payload.get("prompt"),
            payload.get("size"),
            payload.get("resolution"),
        )
        if _is_transparent_background_request(payload):
            prompt = build_transparent_prompt(prompt or "")
        form_data = {
            "prompt": prompt or "",
            "model": _clean(payload.get("model")) or (channel.get("models") or ["gpt-image-1"])[0],
            "n": str(int(payload.get("n") or 1)),
            "response_format": _clean(payload.get("response_format")) or "b64_json",
        }
        form_data.update(_normalize_external_image_options(payload))
        if size is not None:
            form_data["size"] = size
        multipart = CurlMime()
        for key, value in form_data.items():
            if value is None:
                continue
            multipart.addpart(key, data=str(value).encode("utf-8"))
        for index, image in enumerate(payload.get("images") or []):
            if not isinstance(image, tuple) or len(image) != 3:
                continue
            data, filename, content_type = image
            multipart.addpart(
                "image",
                filename=filename or f"image-{index}.png",
                content_type=content_type or "image/png",
                data=data,
            )
        try:
            response = self._session(channel).post(
                self._openai_compatible_url(channel, "/v1/images/edits"),
                multipart=multipart,
                timeout=int(channel.get("timeout") or DEFAULT_CHANNEL_TIMEOUT),
            )
        finally:
            multipart.close()
        return self._normalize_response(response, payload)

    def _chat_completion_body(self, channel: dict[str, object], payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("chat messages are required")
        body = {
            key: value
            for key, value in payload.items()
            if key
            in {
                "model",
                "messages",
                "temperature",
                "top_p",
                "max_tokens",
                "max_completion_tokens",
                "presence_penalty",
                "frequency_penalty",
                "response_format",
                "stop",
                "tools",
                "tool_choice",
            }
            and value is not None
        }
        body["stream"] = bool(payload.get("stream"))
        if "model" not in body:
            body["model"] = (channel.get("models") or ["gpt-5.5"])[0]
        return body

    def _call_chat_completion(self, channel: dict[str, object], payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_gemini_channel(channel):
            return self._call_gemini_chat_completion(channel, payload)
        body = self._chat_completion_body(channel, {**payload, "stream": False})
        response = self._session(channel).post(
            self._openai_compatible_url(channel, "/v1/chat/completions"),
            json=body,
            timeout=int(channel.get("timeout") or DEFAULT_CHANNEL_TIMEOUT),
        )
        return self._normalize_chat_response(response)

    def _call_chat_completion_stream(self, channel: dict[str, object], payload: dict[str, Any]):
        if self._is_gemini_channel(channel):
            return self._call_gemini_chat_completion_stream(channel, payload)
        body = self._chat_completion_body(channel, {**payload, "stream": True})
        session = self._session(channel)
        try:
            response = session.post(
                self._openai_compatible_url(channel, "/v1/chat/completions"),
                json=body,
                timeout=int(channel.get("timeout") or DEFAULT_CHANNEL_TIMEOUT),
                stream=True,
            )
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        except Exception:
            session.close()
            raise

        def chunks():
            try:
                pending = b""
                for chunk in response.iter_content():
                    if not chunk:
                        continue
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    pending += chunk
                    lines = pending.split(b"\n")
                    pending = lines.pop() if lines else b""
                    for raw_line in lines:
                        text = raw_line.rstrip(b"\r").decode("utf-8", errors="replace").strip()
                        if not text:
                            continue
                        if text.startswith("data:"):
                            text = text.removeprefix("data:").strip()
                        if text == "[DONE]":
                            return
                        delta = self._chat_stream_delta_text(text)
                        if delta:
                            yield delta
                if pending:
                    text = pending.rstrip(b"\r").decode("utf-8", errors="replace").strip()
                    if text.startswith("data:"):
                        text = text.removeprefix("data:").strip()
                    if text and text != "[DONE]":
                        delta = self._chat_stream_delta_text(text)
                        if delta:
                            yield delta
            finally:
                session.close()

        return chunks()

    def _session(self, channel: dict[str, object]) -> Session:
        session = Session(**proxy_settings.build_session_kwargs(verify=True))
        session.headers.update({"Accept": "application/json"})
        if self._is_gemini_channel(channel):
            session.headers.update({"Content-Type": "application/json"})
            if self._gemini_uses_google_api_key_header(channel):
                session.headers.update({"x-goog-api-key": _clean(channel.get("api_key"))})
            else:
                session.headers.update({"Authorization": f"Bearer {_clean(channel.get('api_key'))}"})
        else:
            session.headers.update({"Authorization": f"Bearer {_clean(channel.get('api_key'))}"})
        return session

    @staticmethod
    def _openai_compatible_url(channel: dict[str, object], path: str) -> str:
        base_url = _clean(channel.get("base_url")).rstrip("/")
        if not base_url:
            raise ValueError("channel base_url is required")
        normalized_path = "/" + _clean(path).lstrip("/")
        if base_url.lower().endswith("/v1") and normalized_path.startswith("/v1/"):
            normalized_path = normalized_path[3:]
        return f"{base_url}{normalized_path}"

    @staticmethod
    def _gemini_url(channel: dict[str, object], path: str) -> str:
        base_url = ChannelService._gemini_base_url(channel)
        normalized_path = "/" + _clean(path).lstrip("/")
        return f"{base_url}{normalized_path}"

    @staticmethod
    def _gemini_base_url(channel: dict[str, object]) -> str:
        base_url = (_clean(channel.get("base_url")) or DEFAULT_GEMINI_BASE_URL).rstrip("/")
        parsed = urlparse(base_url)
        segments = [segment for segment in parsed.path.strip("/").split("/") if segment]
        last_segment = segments[-1].lower() if segments else ""
        if last_segment not in {"v1", "v1beta", "v1alpha"}:
            base_url = f"{base_url}/v1beta"
        return base_url

    @staticmethod
    def _gemini_uses_google_api_key_header(channel: dict[str, object]) -> bool:
        api_key = _clean(channel.get("api_key"))
        host = (urlparse(_clean(channel.get("base_url")) or DEFAULT_GEMINI_BASE_URL).hostname or "").lower()
        return host == "generativelanguage.googleapis.com" or api_key.startswith("AIza")

    @staticmethod
    def _gemini_supports_file_url_response(channel: dict[str, object]) -> bool:
        host = (urlparse(_clean(channel.get("base_url"))).hostname or "").lower()
        return host == "rolldek.com" or host.endswith(".rolldek.com")

    @staticmethod
    def _normalize_response(response, original_payload: dict[str, Any]) -> dict[str, Any]:
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("channel response is invalid")
        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError("channel response missing data")
        b64_items = [item for item in data if isinstance(item, dict) and item.get("b64_json")]
        url_items = [item for item in data if isinstance(item, dict) and item.get("url") and not item.get("b64_json")]
        base_url = _clean(original_payload.get("base_url")) or None
        transparent_background = _is_transparent_background_request(original_payload)
        localized_url_items = _localize_url_items(
            url_items,
            base_url,
            transparent_background=transparent_background,
        )
        if b64_items:
            result = _format_image_result(
                b64_items,
                _clean(original_payload.get("prompt")),
                _clean(original_payload.get("response_format")) or "b64_json",
                base_url,
                transparent_background=transparent_background,
            )
            if localized_url_items:
                result["data"].extend(localized_url_items)
            return result
        normalized = {"created": int(payload.get("created") or datetime.now().timestamp()), "data": localized_url_items}
        if not normalized["data"]:
            # Some compatible servers return a raw base64 string in `data`.
            for item in data:
                if isinstance(item, str):
                    saved = _format_image_result(
                        [{"b64_json": item}],
                        _clean(original_payload.get("prompt")),
                        "b64_json",
                        base_url,
                        transparent_background=transparent_background,
                    )["data"][0]
                    normalized["data"].append({
                        "b64_json": item,
                        "url": saved["url"],
                    })
        return normalized

    @staticmethod
    def _normalize_chat_response(response) -> dict[str, Any]:
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("channel chat response is invalid")
        return payload

    @staticmethod
    def _chat_stream_delta_text(raw: str) -> str:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        if not isinstance(payload, dict):
            return ""
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                delta = first_choice.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        return "".join(
                            str(item.get("text") or item.get("content") or "")
                            for item in content
                            if isinstance(item, dict)
                        )
                message = first_choice.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return str(message.get("content") or "")
                text = first_choice.get("text")
                if isinstance(text, str):
                    return text
        delta = payload.get("delta")
        if isinstance(delta, str):
            return delta
        text = payload.get("text")
        if isinstance(text, str):
            return text
        return ""


channel_service = ChannelService(config.get_repository_provider() or config.get_storage_backend())
