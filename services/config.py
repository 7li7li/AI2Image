from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path
import time
from urllib.parse import urlparse

from services.storage.base import StorageBackend
from services.repositories.base import RepositoryProvider

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.json"
VERSION_FILE = BASE_DIR / "VERSION"
SYSTEM_SETTING_SECRET_KEYS = {"auth-key", "smtp_password", "linuxdo_client_secret", "image_webdav_config"}
SYSTEM_SETTING_TRANSIENT_KEYS = {"smtp_password_set", "linuxdo_client_secret_set", "image_webdav_password_set"}
REMOVED_PUBLIC_SETTING_KEYS = {
    "account_lease_ttl_seconds",
    "allow_user_registration",
    "auto_remove_invalid_accounts",
    "auto_remove_rate_limited_accounts",
    "email_alias_restriction_enabled",
    "email_domain_whitelist",
    "email_domain_whitelist_enabled",
    "email_verification_enabled",
    "internal_pool_enabled",
    "linuxdo_callback_url",
    "linuxdo_client_id",
    "linuxdo_minimum_trust_level",
    "linuxdo_oauth_enabled",
    "linuxdo_start_url",
    "new_user_initial_quota",
    "refresh_account_interval_minute",
    "smtp_force_auth_login",
    "smtp_from_email",
    "smtp_host",
    "smtp_password",
    "smtp_password_set",
    "smtp_port",
    "smtp_use_ssl",
    "smtp_use_starttls",
    "smtp_username",
}
DEFAULT_SITE_TITLE = "Image Studio"
DEFAULT_SITE_ICON = "/favicon.ico"
DEFAULT_SITE_BACKGROUND = ""
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_TEXT_MODEL = "gpt-5.5"


def _normalize_auth_key(value: object) -> str:
    return str(value or "").strip()


def _is_invalid_auth_key(value: object) -> bool:
    return _normalize_auth_key(value) == ""


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clean_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw_items = value.replace(";", "\n").replace(",", "\n").splitlines()
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    seen: set[str] = set()
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip().lower().lstrip("@")
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _clean_site_text(value: object, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return text[:max_length]


def _parse_timestamp(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _image_relative_path(url: object) -> str:
    parsed_path = urlparse(str(url or "").strip()).path
    if not parsed_path.startswith("/images/"):
        return ""
    return parsed_path.removeprefix("/images/").strip("/")


def _read_json_object(path: Path, *, name: str) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_dir():
        print(
            f"Warning: {name} at '{path}' is a directory, ignoring it and falling back to other configuration sources.",
            file=sys.stderr,
        )
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self._storage_backend: StorageBackend | None = None
        self._system_settings_seeded = False
        if _is_invalid_auth_key(self.auth_key):
            raise ValueError(
                "鉂?auth-key 鏈缃紒\n"
                "璇锋寜浠ヤ笅浠绘剰涓€绉嶆柟寮忚В鍐筹細\n"
                "1. 鍦?Render 鐨?Environment 鍙橀噺涓坊鍔狅細\n"
                "   CHATGPT2API_AUTH_KEY = your_real_auth_key\n"
                "2. 鎴栬€呭湪 config.json 涓～鍐欙細\n"
                '   "auth-key": "your_real_auth_key"'
            )

    def _load(self) -> dict[str, object]:
        return _read_json_object(self.path, name="config.json")

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _provider_if_initialized(self) -> RepositoryProvider | None:
        if self._storage_backend is None:
            return None
        provider = getattr(self._storage_backend, "repository_provider", None)
        if not isinstance(provider, RepositoryProvider):
            return None
        self._ensure_system_settings_seeded(provider)
        return provider

    def _ensure_system_settings_seeded(self, provider: RepositoryProvider) -> None:
        if self._system_settings_seeded:
            return
        try:
            existing = provider.system_config.list_settings()
            for key, value in self.data.items():
                if key in SYSTEM_SETTING_SECRET_KEYS or key in SYSTEM_SETTING_TRANSIENT_KEYS:
                    continue
                if key not in existing:
                    provider.system_config.set_setting(key, value)
            self._system_settings_seeded = True
        except Exception:
            return

    def _effective_data(self) -> dict[str, object]:
        data = dict(self.data)
        provider = self._provider_if_initialized()
        if provider is None:
            return data
        try:
            data.update(provider.system_config.list_settings())
        except Exception:
            pass
        return data

    def _get_config_value(self, key: str, default: object = None) -> object:
        return self._effective_data().get(key, default)

    @property
    def auth_key(self) -> str:
        return _normalize_auth_key(os.getenv("CHATGPT2API_AUTH_KEY") or self.data.get("auth-key"))

    @property
    def image_retention_days(self) -> int:
        try:
            return max(1, int(self._get_config_value("image_retention_days", 30)))
        except (TypeError, ValueError):
            return 30

    @property
    def log_levels(self) -> list[str]:
        levels = self._get_config_value("log_levels")
        if not isinstance(levels, list):
            return []
        allowed = {"debug", "info", "warning", "error"}
        return [level for item in levels if (level := str(item or "").strip().lower()) in allowed]

    @property
    def images_dir(self) -> Path:
        path = DATA_DIR / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def prompt_assets_dir(self) -> Path:
        path = DATA_DIR / "prompt-assets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_old_images(self) -> int:
        cutoff = time.time() - self.image_retention_days * 86400
        record_times = self._image_record_file_times()
        removed = 0
        for path in self.images_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(self.images_dir).as_posix()
                stat = path.stat()
            except OSError:
                continue
            record_time = None if record_times is None else record_times.get(rel)
            if record_times is not None and rel in record_times:
                should_remove = (record_time if record_time is not None else stat.st_mtime) < cutoff
            else:
                should_remove = stat.st_mtime < cutoff
            if should_remove:
                path.unlink()
                removed += 1
        for path in sorted((p for p in self.images_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
        return removed

    def _image_record_file_times(self) -> dict[str, float | None] | None:
        try:
            provider = self.get_repository_provider()
            records = provider.image_records.list() if provider is not None else self.get_storage_backend().load_image_records()
        except Exception:
            return None
        result: dict[str, float | None] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            rel = _image_relative_path(record.get("url"))
            if not rel:
                continue
            timestamp = _parse_timestamp(record.get("created_at"))
            current = result.get(rel)
            if current is None or (timestamp is not None and timestamp > current):
                result[rel] = timestamp
        return result

    @property
    def base_url(self) -> str:
        return str(
            os.getenv("CHATGPT2API_BASE_URL")
            or self._get_config_value("base_url")
            or ""
        ).strip().rstrip("/")

    @property
    def site_title(self) -> str:
        return _clean_site_text(
            os.getenv("YANAI_SITE_TITLE") or self._get_config_value("site_title"),
            default=DEFAULT_SITE_TITLE,
            max_length=80,
        )

    @property
    def site_icon(self) -> str:
        return _clean_site_text(
            os.getenv("YANAI_SITE_ICON") or self._get_config_value("site_icon"),
            default=DEFAULT_SITE_ICON,
            max_length=500,
        )

    @property
    def site_background(self) -> str:
        return _clean_site_text(
            os.getenv("YANAI_SITE_BACKGROUND") or self._get_config_value("site_background"),
            default=DEFAULT_SITE_BACKGROUND,
            max_length=1000,
        )

    @property
    def default_image_model(self) -> str:
        return _clean_site_text(
            os.getenv("YANAI_DEFAULT_IMAGE_MODEL") or self._get_config_value("default_image_model"),
            default=DEFAULT_IMAGE_MODEL,
            max_length=120,
        )

    @property
    def default_text_model(self) -> str:
        return _clean_site_text(
            os.getenv("YANAI_DEFAULT_TEXT_MODEL") or self._get_config_value("default_text_model"),
            default=DEFAULT_TEXT_MODEL,
            max_length=120,
        )

    @property
    def image_model_mappings(self) -> dict[str, str]:
        defaults: dict[str, str] = {}
        raw = self._get_config_value("image_model_mappings")
        if not isinstance(raw, dict):
            return defaults
        mappings = dict(defaults)
        for key, value in raw.items():
            source_model = str(key or "").strip()
            target_model = str(value or "").strip()
            if source_model and target_model:
                mappings[source_model] = target_model
        return mappings

    @property
    def app_version(self) -> str:
        try:
            value = VERSION_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return "0.0.0"
        return value or "0.0.0"

    def get(self) -> dict[str, object]:
        data = self._effective_data()
        data["site_title"] = self.site_title
        data["site_icon"] = self.site_icon
        data["site_background"] = self.site_background
        data["default_image_model"] = self.default_image_model
        data["default_text_model"] = self.default_text_model
        data["image_retention_days"] = self.image_retention_days
        data["log_levels"] = self.log_levels
        data["image_model_mappings"] = self.image_model_mappings
        data.pop("auth-key", None)
        data.pop("smtp_password", None)
        data.pop("linuxdo_client_secret", None)
        data.pop("image_webdav_config", None)
        for key in REMOVED_PUBLIC_SETTING_KEYS:
            data.pop(key, None)
        return data

    def public_settings(self) -> dict[str, object]:
        return {
            "site_title": self.site_title,
            "site_icon": self.site_icon,
            "site_background": self.site_background,
            "default_image_model": self.default_image_model,
            "default_text_model": self.default_text_model,
        }

    def get_proxy_settings(self) -> str:
        return str(self._get_config_value("proxy") or "").strip()

    def update(self, data: dict[str, object]) -> dict[str, object]:
        updates = dict(data or {})
        for transient_key in ("smtp_password_set", "linuxdo_client_secret_set"):
            updates.pop(transient_key, None)
        for secret_key in ("smtp_password", "linuxdo_client_secret"):
            if secret_key in updates and not str(updates.get(secret_key) or "").strip():
                updates.pop(secret_key, None)
        provider = self._provider_if_initialized()
        if provider is not None:
            for key, value in updates.items():
                if key in SYSTEM_SETTING_SECRET_KEYS or key in SYSTEM_SETTING_TRANSIENT_KEYS:
                    continue
                provider.system_config.set_setting(key, value)
        next_data = dict(self.data)
        next_data.update(updates)
        self.data = next_data
        self._save()
        return self.get()

    def get_storage_backend(self) -> StorageBackend:
        """Return the singleton storage backend."""
        if self._storage_backend is None:
            from services.storage.factory import create_storage_backend
            self._storage_backend = create_storage_backend(DATA_DIR, self.data)
        return self._storage_backend

    def get_repository_provider(self) -> RepositoryProvider | None:
        """Return the database repository provider when available."""
        storage = self.get_storage_backend()
        provider = getattr(storage, "repository_provider", None)
        return provider if isinstance(provider, RepositoryProvider) else None


config = ConfigStore(CONFIG_FILE)
