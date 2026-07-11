from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from services.storage.base import StorageBackend
from services.storage.database_storage import DatabaseStorageBackend
from services.storage.git_storage import GitStorageBackend
from services.storage.json_storage import JSONStorageBackend


PROMPT_LIBRARY_JSON_IMPORT_MARKER = "storage_migration.prompt_library_seed_v2"
BUNDLED_PROMPT_LIBRARY_PATH = (
    Path(__file__).resolve().parents[2] / "web_dist" / "banana-prompt-quicker" / "prompts.json"
)


def create_storage_backend(data_dir: Path, settings: Mapping[str, object] | None = None) -> StorageBackend:
    """
    Create the configured storage backend.

    Environment variables override values in config.json:
    - STORAGE_BACKEND: json|sqlite|postgres|git
    - DATABASE_URL: database connection string
    - GIT_REPO_URL/GIT_TOKEN/GIT_BRANCH: Git storage connection settings
    - GIT_*_FILE_PATH: Git paths for individual datasets
    """
    resolved_settings = settings if settings is not None else _load_config_settings(data_dir)
    backend_type = _get_setting("STORAGE_BACKEND", "json", resolved_settings).lower()

    print(f"[storage] Initializing storage backend: {backend_type}")

    if backend_type == "json":
        print(f"[storage] Using JSON storage: {data_dir}")
        return JSONStorageBackend(data_dir)

    if backend_type in ("sqlite", "postgres", "postgresql", "mysql", "database"):
        database_url = _get_setting("DATABASE_URL", "", resolved_settings)
        if not database_url:
            database_url = f"sqlite:///{data_dir / 'storage.db'}"
            print(f"[storage] No DATABASE_URL provided, using local SQLite: {database_url}")
        else:
            database_url = _normalize_database_url(database_url)
            print(f"[storage] Using database storage: {_mask_password(database_url)}")
        backend = DatabaseStorageBackend(database_url)
        _import_json_prompt_library_once(backend, data_dir)
        return backend

    if backend_type == "git":
        repo_url = _get_setting("GIT_REPO_URL", "", resolved_settings)
        token = _get_setting("GIT_TOKEN", "", resolved_settings)
        branch = _get_setting("GIT_BRANCH", "main", resolved_settings)
        auth_keys_file_path = _get_setting("GIT_AUTH_KEYS_FILE_PATH", "auth_keys.json", resolved_settings)
        users_file_path = _get_setting("GIT_USERS_FILE_PATH", "users.json", resolved_settings)
        sessions_file_path = _get_setting("GIT_SESSIONS_FILE_PATH", "sessions.json", resolved_settings)
        redeem_codes_file_path = _get_setting("GIT_REDEEM_CODES_FILE_PATH", "redeem_codes.json", resolved_settings)
        channels_file_path = _get_setting("GIT_CHANNELS_FILE_PATH", "channels.json", resolved_settings)
        prompt_library_file_path = _get_setting("GIT_PROMPT_LIBRARY_FILE_PATH", "prompt_library.json", resolved_settings)
        image_records_file_path = _get_setting("GIT_IMAGE_RECORDS_FILE_PATH", "image_records.json", resolved_settings)

        if not repo_url:
            raise ValueError(
                "GIT_REPO_URL is required when using git storage backend. "
                "Please set GIT_REPO_URL environment variable."
            )

        print(f"[storage] Using Git storage: {_mask_token(repo_url)}, branch: {branch}")
        return GitStorageBackend(
            repo_url=repo_url,
            token=token,
            branch=branch,
            auth_keys_file_path=auth_keys_file_path,
            users_file_path=users_file_path,
            sessions_file_path=sessions_file_path,
            redeem_codes_file_path=redeem_codes_file_path,
            channels_file_path=channels_file_path,
            prompt_library_file_path=prompt_library_file_path,
            image_records_file_path=image_records_file_path,
            local_cache_dir=data_dir / "git_cache",
        )

    raise ValueError(
        f"Unknown storage backend: {backend_type}. "
        "Supported backends: json, sqlite, postgres, git"
    )


def _import_json_prompt_library_once(backend: DatabaseStorageBackend, data_dir: Path) -> None:
    """Seed an empty database from a mounted or image-bundled prompt library."""
    provider = backend.repository_provider
    settings = provider.system_config
    try:
        if settings.get_setting(PROMPT_LIBRARY_JSON_IMPORT_MARKER, False):
            print("[storage] Prompt library seed already completed")
            return

        existing_prompts = provider.prompts.list()
        public_prompts = [
            item
            for item in existing_prompts
            if str(item.get("status") or "public").strip().lower() == "public"
        ]
        if public_prompts:
            settings.set_setting(PROMPT_LIBRARY_JSON_IMPORT_MARKER, True)
            print(f"[storage] Prompt library already contains {len(public_prompts)} public items; skipping seed")
            return

        json_prompts, source_path = _load_prompt_library_seed(data_dir)
        if not json_prompts:
            print("[storage] No prompt library seed data found")
            return

        existing_ids = {str(item.get("id") or "").strip() for item in existing_prompts}
        new_prompts = [item for item in json_prompts if str(item.get("id") or "").strip() not in existing_ids]
        provider.prompts.replace_all([*existing_prompts, *new_prompts])
        settings.set_setting(PROMPT_LIBRARY_JSON_IMPORT_MARKER, True)
        print(f"[storage] Imported {len(new_prompts)} public prompts from {source_path}")
    except Exception as exc:
        print(f"[storage] Failed to import JSON prompt library: {exc}")


def _load_prompt_library_seed(data_dir: Path) -> tuple[list[dict[str, Any]], Path | None]:
    candidates = (data_dir / "prompt_library.json", BUNDLED_PROMPT_LIBRARY_PATH)
    for source_path in candidates:
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        raw_prompts = payload.get("prompts") if isinstance(payload, dict) else payload
        if not isinstance(raw_prompts, list):
            continue
        prompts = [_with_prompt_id(item) for item in raw_prompts if isinstance(item, dict)]
        prompts = [item for item in prompts if item.get("title") and item.get("prompt")]
        if prompts:
            return prompts, source_path
    return [], None


def _with_prompt_id(item: dict[str, Any]) -> dict[str, Any]:
    prompt = dict(item)
    if str(prompt.get("id") or "").strip():
        return prompt
    seed = "\0".join(
        str(prompt.get(key) or "").strip()
        for key in ("title", "prompt", "created")
    )
    prompt["id"] = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
    return prompt


def _mask_password(url: str) -> str:
    if "://" not in url:
        return url
    try:
        protocol, rest = url.split("://", 1)
        if "@" in rest:
            credentials, host = rest.split("@", 1)
            if ":" in credentials:
                username, _ = credentials.split(":", 1)
                return f"{protocol}://{username}:****@{host}"
        return url
    except Exception:
        return url


def _load_config_settings(data_dir: Path) -> dict[str, object]:
    config_path = data_dir.resolve().parent / "config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _get_setting(name: str, default: str, settings: Mapping[str, object]) -> str:
    env_value = os.getenv(name)
    if env_value is not None and env_value.strip():
        return _strip_wrapping_quotes(env_value)

    value = _lookup_setting(settings, name, default)
    return _strip_wrapping_quotes(str(default if value is None else value))


def _lookup_setting(settings: Mapping[str, object], name: str, default: str) -> object:
    if name in settings:
        return settings[name]

    normalized_name = name.lower()
    for key, value in settings.items():
        if str(key).lower() == normalized_name:
            return value
    return default


def _strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1].strip()
    return value


def _normalize_database_url(url: str) -> str:
    """URL-encode user info so raw password characters do not break SQLAlchemy parsing."""
    url = _strip_wrapping_quotes(url)
    if "://" not in url or "@" not in url:
        return url

    protocol, rest = url.split("://", 1)
    if protocol.startswith("sqlite") or rest.startswith("/"):
        return url

    authority_end = min(
        [index for marker in ("/", "?", "#") if (index := rest.find(marker)) != -1],
        default=len(rest),
    )
    authority = rest[:authority_end]
    suffix = rest[authority_end:]
    if "@" not in authority:
        return url

    credentials, host = authority.rsplit("@", 1)
    if not credentials:
        return url

    if ":" in credentials:
        username, password = credentials.split(":", 1)
        encoded_credentials = f"{quote(unquote(username), safe='')}:{quote(unquote(password), safe='')}"
    else:
        encoded_credentials = quote(unquote(credentials), safe="")

    return f"{protocol}://{encoded_credentials}@{host}{suffix}"


def _mask_token(url: str) -> str:
    if "@" in url and "://" in url:
        protocol, rest = url.split("://", 1)
        if "@" in rest:
            _, host = rest.split("@", 1)
            return f"{protocol}://****@{host}"
    return url
