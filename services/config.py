from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
SYSTEM_SETTING_SECRET_KEYS = {"auth-key", "smtp_password", "linuxdo_client_secret", "image_webdav_config", "epay_key"}
SYSTEM_SETTING_TRANSIENT_KEYS = {
    "smtp_password_set",
    "linuxdo_client_secret_set",
    "image_webdav_password_set",
    "epay_key_set",
}
DEFAULT_SITE_TITLE = "Image Studio"
DEFAULT_SITE_ICON = "/favicon.ico"
DEFAULT_SITE_BACKGROUND = ""
DEFAULT_QUOTA_PURCHASE_URL = ""
DEFAULT_QUOTA_PURCHASE_MODE = "url"
DEFAULT_EPAY_URL = ""
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_TEXT_MODEL = "gpt-5.5"
DEFAULT_IMAGE_PROMPT_POLISH_MODEL = DEFAULT_TEXT_MODEL
DEFAULT_BACKGROUND_TASK_MAX_WORKERS = 12
DEFAULT_BACKGROUND_TASK_QUEUE_LIMIT = 100
DEFAULT_BACKGROUND_TASK_USER_LIMIT = 3
DEFAULT_BACKGROUND_TASK_USER_QUEUE_LIMIT = 20
DEFAULT_SMTP_PORT = 587
DEFAULT_VERIFICATION_CODE_MINUTES = 10


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


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value if value is not None and value != "" else default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _strict_bounded_int(value: object, *, minimum: int, maximum: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum or parsed > maximum:
        return None
    return parsed


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


def _clean_email(value: object) -> str:
    return str(value or "").strip().lower()


def _public_email_domain_choices(value: object) -> list[str]:
    seen: set[str] = set()
    domains: list[str] = []
    for entry in _clean_list(value):
        domain = entry.lstrip("@")
        if not domain or "@" in domain or domain.startswith("*.") or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
    return domains


def _clean_site_text(value: object, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return text[:max_length]


def _clean_subscription_plan_id(value: object, *, fallback: str, seen: set[str]) -> str:
    raw = str(value or "").strip().lower()
    candidate = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in raw).strip("-_")
    candidate = (candidate or fallback)[:80]
    if candidate not in seen:
        seen.add(candidate)
        return candidate
    index = 2
    while f"{candidate}-{index}" in seen:
        index += 1
    unique = f"{candidate}-{index}"
    seen.add(unique)
    return unique


def _normalize_quota_purchase_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"subscription", "subscriptions", "plan", "plans"}:
        return "subscription"
    return DEFAULT_QUOTA_PURCHASE_MODE


def _normalize_epay_url(value: object) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return DEFAULT_EPAY_URL
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return DEFAULT_EPAY_URL
    return text[:1000]


def _normalize_epay_type(value: object) -> str:
    text = str(value or "").strip().lower()
    candidate = "".join(char for char in text if char.isalnum() or char in {"_", "-"})
    return candidate[:40]


def _clean_subscription_plans(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    plans: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value[:20]):
        if not isinstance(raw, dict):
            continue
        quota = _strict_bounded_int(raw.get("quota"), minimum=1, maximum=1_000_000)
        valid_months = _strict_bounded_int(
            raw.get("valid_months") or raw.get("quota_valid_months") or raw.get("validity_months"),
            minimum=1,
            maximum=120,
        )
        price = str(raw.get("price", "")).strip()[:80]
        concurrency = _strict_bounded_int(raw.get("concurrency", 1), minimum=1, maximum=50)
        if quota is None or valid_months is None or concurrency is None or not price:
            continue
        plan_id = _clean_subscription_plan_id(raw.get("id"), fallback=f"plan-{index + 1}", seen=seen)
        name = _clean_site_text(raw.get("name"), default="", max_length=80)
        if not name:
            name = f"{quota} 点 / {valid_months} 个月"
        plans.append(
            {
                "id": plan_id,
                "name": name,
                "quota": quota,
                "valid_months": valid_months,
                "concurrency": concurrency,
                "price": price,
            }
        )
    return plans


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


def _normalize_update_data(data: dict[str, object]) -> dict[str, object]:
    updates = dict(data or {})
    for transient_key in SYSTEM_SETTING_TRANSIENT_KEYS:
        updates.pop(transient_key, None)

    for secret_key in ("smtp_password", "linuxdo_client_secret", "epay_key"):
        if secret_key not in updates:
            continue
        secret_value = str(updates.get(secret_key) or "").strip()
        if not secret_value:
            updates.pop(secret_key, None)
        else:
            updates[secret_key] = secret_value

    for key in ("allow_user_registration", "email_verification_enabled", "email_domain_whitelist_enabled"):
        if key in updates:
            updates[key] = _bool(updates.get(key), False)
    for key in ("smtp_use_ssl", "smtp_use_starttls", "smtp_force_auth_login"):
        if key in updates:
            updates[key] = _bool(updates.get(key), key != "smtp_use_ssl")

    if "email_domain_whitelist" in updates:
        updates["email_domain_whitelist"] = _clean_list(updates.get("email_domain_whitelist"))
    if "new_user_initial_quota" in updates:
        updates["new_user_initial_quota"] = _bounded_int(
            updates.get("new_user_initial_quota"),
            default=0,
            minimum=0,
            maximum=1_000_000,
        )
    if "new_user_quota_valid_days" in updates:
        updates["new_user_quota_valid_days"] = _bounded_int(
            updates.get("new_user_quota_valid_days"),
            default=0,
            minimum=0,
            maximum=3650,
        )
    if "smtp_port" in updates:
        updates["smtp_port"] = _bounded_int(
            updates.get("smtp_port"),
            default=DEFAULT_SMTP_PORT,
            minimum=1,
            maximum=65535,
        )

    for key in ("proxy", "smtp_host", "smtp_username"):
        if key in updates:
            updates[key] = str(updates.get(key) or "").strip()
    if "base_url" in updates:
        updates["base_url"] = str(updates.get("base_url") or "").strip().rstrip("/")
    if "smtp_from_email" in updates:
        updates["smtp_from_email"] = _clean_email(updates.get("smtp_from_email"))

    if "site_title" in updates:
        updates["site_title"] = _clean_site_text(updates.get("site_title"), default=DEFAULT_SITE_TITLE, max_length=80)
    if "site_icon" in updates:
        updates["site_icon"] = _clean_site_text(updates.get("site_icon"), default=DEFAULT_SITE_ICON, max_length=500)
    if "site_background" in updates:
        updates["site_background"] = _clean_site_text(
            updates.get("site_background"),
            default=DEFAULT_SITE_BACKGROUND,
            max_length=1000,
        )
    if "quota_purchase_url" in updates:
        updates["quota_purchase_url"] = _clean_site_text(
            updates.get("quota_purchase_url"),
            default=DEFAULT_QUOTA_PURCHASE_URL,
            max_length=1000,
        )
    if "quota_purchase_mode" in updates:
        updates["quota_purchase_mode"] = _normalize_quota_purchase_mode(updates.get("quota_purchase_mode"))
    if "subscription_plans" in updates:
        updates["subscription_plans"] = _clean_subscription_plans(updates.get("subscription_plans"))
    if "epay_enabled" in updates:
        updates["epay_enabled"] = _bool(updates.get("epay_enabled"), False)
    if "epay_url" in updates:
        updates["epay_url"] = _normalize_epay_url(updates.get("epay_url"))
    if "epay_pid" in updates:
        updates["epay_pid"] = str(updates.get("epay_pid") or "").strip()[:80]
    if "epay_type" in updates:
        updates["epay_type"] = _normalize_epay_type(updates.get("epay_type"))
    if "default_image_model" in updates:
        updates["default_image_model"] = _clean_site_text(
            updates.get("default_image_model"),
            default=DEFAULT_IMAGE_MODEL,
            max_length=120,
        )
    if "default_text_model" in updates:
        updates["default_text_model"] = _clean_site_text(
            updates.get("default_text_model"),
            default=DEFAULT_TEXT_MODEL,
            max_length=120,
        )
    if "default_image_prompt_polish_model" in updates:
        updates["default_image_prompt_polish_model"] = _clean_site_text(
            updates.get("default_image_prompt_polish_model"),
            default=DEFAULT_IMAGE_PROMPT_POLISH_MODEL,
            max_length=120,
        )

    if "background_task_max_workers" in updates:
        updates["background_task_max_workers"] = _bounded_int(
            updates.get("background_task_max_workers"),
            default=DEFAULT_BACKGROUND_TASK_MAX_WORKERS,
            minimum=1,
            maximum=128,
        )
    if "background_task_queue_limit" in updates:
        updates["background_task_queue_limit"] = _bounded_int(
            updates.get("background_task_queue_limit"),
            default=DEFAULT_BACKGROUND_TASK_QUEUE_LIMIT,
            minimum=1,
            maximum=10000,
        )
    if "background_task_user_limit" in updates:
        updates["background_task_user_limit"] = _bounded_int(
            updates.get("background_task_user_limit"),
            default=DEFAULT_BACKGROUND_TASK_USER_LIMIT,
            minimum=0,
            maximum=50,
        )
    if "background_task_user_queue_limit" in updates:
        updates["background_task_user_queue_limit"] = _bounded_int(
            updates.get("background_task_user_queue_limit"),
            default=DEFAULT_BACKGROUND_TASK_USER_QUEUE_LIMIT,
            minimum=1,
            maximum=1000,
        )
    if "image_retention_days" in updates:
        updates["image_retention_days"] = _bounded_int(
            updates.get("image_retention_days"),
            default=30,
            minimum=1,
            maximum=3650,
        )
    if "log_levels" in updates:
        allowed = {"debug", "info", "warning", "error"}
        levels = updates.get("log_levels")
        updates["log_levels"] = [
            level
            for item in (levels if isinstance(levels, list) else [])
            if (level := str(item or "").strip().lower()) in allowed
        ]

    return updates


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
                "auth-key is not set.\n"
                "Set a long random admin key in config.json:\n"
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
        return _normalize_auth_key(self.data.get("auth-key"))

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
    def quota_purchase_url(self) -> str:
        return _clean_site_text(
            os.getenv("YANAI_QUOTA_PURCHASE_URL") or self._get_config_value("quota_purchase_url"),
            default=DEFAULT_QUOTA_PURCHASE_URL,
            max_length=1000,
        )

    @property
    def quota_purchase_mode(self) -> str:
        return _normalize_quota_purchase_mode(
            os.getenv("YANAI_QUOTA_PURCHASE_MODE") or self._get_config_value("quota_purchase_mode")
        )

    @property
    def subscription_plans(self) -> list[dict[str, object]]:
        return _clean_subscription_plans(self._get_config_value("subscription_plans"))

    @property
    def epay_enabled(self) -> bool:
        return _bool(os.getenv("YANAI_EPAY_ENABLED") or self._get_config_value("epay_enabled"), False)

    @property
    def epay_url(self) -> str:
        return _normalize_epay_url(os.getenv("YANAI_EPAY_URL") or self._get_config_value("epay_url"))

    @property
    def epay_pid(self) -> str:
        return str(os.getenv("YANAI_EPAY_PID") or self._get_config_value("epay_pid") or "").strip()

    @property
    def epay_key(self) -> str:
        return str(os.getenv("YANAI_EPAY_KEY") or self.data.get("epay_key") or "").strip()

    @property
    def epay_type(self) -> str:
        return _normalize_epay_type(os.getenv("YANAI_EPAY_TYPE") or self._get_config_value("epay_type"))

    @property
    def epay_configured(self) -> bool:
        return bool(self.epay_enabled and self.epay_url and self.epay_pid and self.epay_key)

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
    def default_image_prompt_polish_model(self) -> str:
        return _clean_site_text(
            os.getenv("YANAI_DEFAULT_IMAGE_PROMPT_POLISH_MODEL")
            or self._get_config_value("default_image_prompt_polish_model"),
            default=DEFAULT_IMAGE_PROMPT_POLISH_MODEL,
            max_length=120,
        )

    @property
    def background_task_max_workers(self) -> int:
        return _bounded_int(
            os.getenv("YANAI_BACKGROUND_TASK_MAX_WORKERS")
            or self._get_config_value("background_task_max_workers"),
            default=DEFAULT_BACKGROUND_TASK_MAX_WORKERS,
            minimum=1,
            maximum=128,
        )

    @property
    def background_task_queue_limit(self) -> int:
        return _bounded_int(
            os.getenv("YANAI_BACKGROUND_TASK_QUEUE_LIMIT")
            or self._get_config_value("background_task_queue_limit"),
            default=DEFAULT_BACKGROUND_TASK_QUEUE_LIMIT,
            minimum=1,
            maximum=10000,
        )

    @property
    def background_task_user_limit(self) -> int:
        return _bounded_int(
            os.getenv("YANAI_BACKGROUND_TASK_USER_LIMIT")
            or self._get_config_value("background_task_user_limit"),
            default=DEFAULT_BACKGROUND_TASK_USER_LIMIT,
            minimum=0,
            maximum=50,
        )

    @property
    def background_task_user_queue_limit(self) -> int:
        return _bounded_int(
            os.getenv("YANAI_BACKGROUND_TASK_USER_QUEUE_LIMIT")
            or self._get_config_value("background_task_user_queue_limit"),
            default=DEFAULT_BACKGROUND_TASK_USER_QUEUE_LIMIT,
            minimum=1,
            maximum=1000,
        )

    @property
    def allow_user_registration(self) -> bool:
        return _bool(self._get_config_value("allow_user_registration"), False)

    @property
    def email_verification_enabled(self) -> bool:
        return _bool(self._get_config_value("email_verification_enabled"), False)

    @property
    def email_domain_whitelist_enabled(self) -> bool:
        return _bool(self._get_config_value("email_domain_whitelist_enabled"), False)

    @property
    def email_domain_whitelist(self) -> list[str]:
        return _clean_list(self._get_config_value("email_domain_whitelist"))

    @property
    def public_email_domain_whitelist(self) -> list[str]:
        return _public_email_domain_choices(self.email_domain_whitelist)

    @property
    def new_user_initial_quota(self) -> int:
        return _bounded_int(
            self._get_config_value("new_user_initial_quota"),
            default=0,
            minimum=0,
            maximum=1_000_000,
        )

    @property
    def new_user_quota_valid_days(self) -> int:
        return _bounded_int(
            self._get_config_value("new_user_quota_valid_days"),
            default=0,
            minimum=0,
            maximum=3650,
        )

    def new_user_quota_expires_at(self, now: datetime | None = None) -> str | None:
        if self.new_user_initial_quota <= 0 or self.new_user_quota_valid_days <= 0:
            return None
        base_time = now or datetime.now(timezone.utc)
        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)
        return (base_time.astimezone(timezone.utc) + timedelta(days=self.new_user_quota_valid_days)).isoformat()

    @property
    def smtp_host(self) -> str:
        return str(self._get_config_value("smtp_host") or "").strip()

    @property
    def smtp_port(self) -> int:
        return _bounded_int(
            self._get_config_value("smtp_port"),
            default=DEFAULT_SMTP_PORT,
            minimum=1,
            maximum=65535,
        )

    @property
    def smtp_username(self) -> str:
        return str(self._get_config_value("smtp_username") or "").strip()

    @property
    def smtp_password(self) -> str:
        return str(self.data.get("smtp_password") or "").strip()

    @property
    def smtp_from_email(self) -> str:
        return _clean_email(self._get_config_value("smtp_from_email")) or _clean_email(self.smtp_username)

    @property
    def smtp_use_ssl(self) -> bool:
        return _bool(self._get_config_value("smtp_use_ssl"), False)

    @property
    def smtp_use_starttls(self) -> bool:
        return _bool(self._get_config_value("smtp_use_starttls"), True)

    @property
    def smtp_force_auth_login(self) -> bool:
        return _bool(self._get_config_value("smtp_force_auth_login"), True)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from_email)

    def email_allowed_for_registration(self, email: str) -> bool:
        normalized_email = _clean_email(email)
        if not self.email_domain_whitelist_enabled:
            return True
        if "@" not in normalized_email:
            return False
        _, domain = normalized_email.rsplit("@", 1)
        if not domain:
            return False
        for entry in self.email_domain_whitelist:
            if "@" in entry and normalized_email == entry:
                return True
            candidate = entry.lstrip("@")
            if candidate.startswith("*."):
                base_domain = candidate[2:]
                if domain.endswith(f".{base_domain}"):
                    return True
                continue
            if domain == candidate:
                return True
        return False

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
        for transient_key in SYSTEM_SETTING_TRANSIENT_KEYS:
            data.pop(transient_key, None)
        data["site_title"] = self.site_title
        data["site_icon"] = self.site_icon
        data["site_background"] = self.site_background
        data["quota_purchase_url"] = self.quota_purchase_url
        data["quota_purchase_mode"] = self.quota_purchase_mode
        data["subscription_plans"] = self.subscription_plans
        data["epay_enabled"] = self.epay_enabled
        data["epay_url"] = self.epay_url
        data["epay_pid"] = self.epay_pid
        data["epay_type"] = self.epay_type
        data["epay_key_set"] = bool(self.epay_key)
        data["default_image_model"] = self.default_image_model
        data["default_text_model"] = self.default_text_model
        data["default_image_prompt_polish_model"] = self.default_image_prompt_polish_model
        data["image_retention_days"] = self.image_retention_days
        data["log_levels"] = self.log_levels
        data["image_model_mappings"] = self.image_model_mappings
        data["background_task_max_workers"] = self.background_task_max_workers
        data["background_task_queue_limit"] = self.background_task_queue_limit
        data["background_task_user_limit"] = self.background_task_user_limit
        data["background_task_user_queue_limit"] = self.background_task_user_queue_limit
        data["allow_user_registration"] = self.allow_user_registration
        data["email_verification_enabled"] = self.email_verification_enabled
        data["email_domain_whitelist_enabled"] = self.email_domain_whitelist_enabled
        data["email_domain_whitelist"] = self.email_domain_whitelist
        data["new_user_initial_quota"] = self.new_user_initial_quota
        data["new_user_quota_valid_days"] = self.new_user_quota_valid_days
        data["smtp_host"] = self.smtp_host
        data["smtp_port"] = self.smtp_port
        data["smtp_username"] = self.smtp_username
        data["smtp_from_email"] = self.smtp_from_email
        data["smtp_use_ssl"] = self.smtp_use_ssl
        data["smtp_use_starttls"] = self.smtp_use_starttls
        data["smtp_force_auth_login"] = self.smtp_force_auth_login
        data["smtp_password_set"] = bool(self.smtp_password)
        data.pop("auth-key", None)
        data.pop("smtp_password", None)
        data.pop("linuxdo_client_secret", None)
        data.pop("image_webdav_config", None)
        data.pop("epay_key", None)
        return data

    def public_settings(self) -> dict[str, object]:
        return {
            "site_title": self.site_title,
            "site_icon": self.site_icon,
            "site_background": self.site_background,
            "quota_purchase_url": self.quota_purchase_url,
            "quota_purchase_mode": self.quota_purchase_mode,
            "subscription_plans": self.subscription_plans,
            "default_image_model": self.default_image_model,
            "default_text_model": self.default_text_model,
            "default_image_prompt_polish_model": self.default_image_prompt_polish_model,
        }

    def public_auth_settings(self) -> dict[str, object]:
        return {
            "allow_user_registration": self.allow_user_registration,
            "email_verification_enabled": self.email_verification_enabled,
            "email_domain_whitelist_enabled": self.email_domain_whitelist_enabled,
            "email_domain_whitelist": self.public_email_domain_whitelist if self.email_domain_whitelist_enabled else [],
        }

    def get_proxy_settings(self) -> str:
        return str(self._get_config_value("proxy") or "").strip()

    def update(self, data: dict[str, object]) -> dict[str, object]:
        updates = _normalize_update_data(data)
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
        self._sync_runtime_settings()
        return self.get()

    def _sync_runtime_settings(self) -> None:
        try:
            from services.background_task_service import background_task_service

            background_task_service.configure(
                max_workers=self.background_task_max_workers,
                max_pending_tasks=self.background_task_queue_limit,
                max_tasks_per_owner=self.background_task_user_limit,
                max_pending_tasks_per_owner=self.background_task_user_queue_limit,
            )
        except Exception:
            return

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
