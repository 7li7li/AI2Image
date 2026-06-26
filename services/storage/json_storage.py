from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.storage.base import StorageBackend


class JSONStorageBackend(StorageBackend):
    """Local JSON-file storage backend."""

    def __init__(self, data_path: Path, auth_keys_path: Path | None = None):
        data_path = Path(data_path)
        self.data_dir = data_path.parent if data_path.suffix else data_path
        self.auth_keys_path = auth_keys_path or self.data_dir / "auth_keys.json"
        self.users_path = self.data_dir / "users.json"
        self.sessions_path = self.data_dir / "sessions.json"
        self.redeem_codes_path = self.data_dir / "redeem_codes.json"
        self.channels_path = self.data_dir / "channels.json"
        self.prompt_library_path = self.data_dir / "prompt_library.json"
        self.image_records_path = self.data_dir / "image_records.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_json_list(file_path: Path) -> list[dict[str, Any]]:
        if not file_path.exists():
            return []
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, Exception):
            return []

    @staticmethod
    def _save_json_list(file_path: Path, items: list[dict[str, Any]]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_auth_keys(self) -> list[dict[str, Any]]:
        if not self.auth_keys_path.exists():
            return []
        try:
            data = json.loads(self.auth_keys_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return []
        if isinstance(data, dict):
            data = data.get("items")
        return data if isinstance(data, list) else []

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.write_text(
            json.dumps({"items": auth_keys}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_users(self) -> list[dict[str, Any]]:
        return self._load_json_list(self.users_path)

    def save_users(self, users: list[dict[str, Any]]) -> None:
        self._save_json_list(self.users_path, users)

    def load_sessions(self) -> list[dict[str, Any]]:
        return self._load_json_list(self.sessions_path)

    def save_sessions(self, sessions: list[dict[str, Any]]) -> None:
        self._save_json_list(self.sessions_path, sessions)

    def load_redeem_codes(self) -> list[dict[str, Any]]:
        return self._load_json_list(self.redeem_codes_path)

    def save_redeem_codes(self, redeem_codes: list[dict[str, Any]]) -> None:
        self._save_json_list(self.redeem_codes_path, redeem_codes)

    def load_channels(self) -> list[dict[str, Any]]:
        return self._load_json_list(self.channels_path)

    def save_channels(self, channels: list[dict[str, Any]]) -> None:
        self._save_json_list(self.channels_path, channels)

    def load_prompt_library(self) -> list[dict[str, Any]]:
        return self._load_json_list(self.prompt_library_path)

    def save_prompt_library(self, prompts: list[dict[str, Any]]) -> None:
        self._save_json_list(self.prompt_library_path, prompts)

    def load_image_records(self) -> list[dict[str, Any]]:
        return self._load_json_list(self.image_records_path)

    def save_image_records(self, image_records: list[dict[str, Any]]) -> None:
        self._save_json_list(self.image_records_path, image_records)

    def health_check(self) -> dict[str, Any]:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            return {
                "status": "healthy",
                "backend": "json",
                "data_dir": str(self.data_dir),
                "auth_keys_file_exists": self.auth_keys_path.exists(),
                "auth_keys_file_path": str(self.auth_keys_path),
                "users_file_exists": self.users_path.exists(),
                "sessions_file_exists": self.sessions_path.exists(),
                "redeem_codes_file_exists": self.redeem_codes_path.exists(),
                "channels_file_exists": self.channels_path.exists(),
                "prompt_library_file_exists": self.prompt_library_path.exists(),
                "image_records_file_exists": self.image_records_path.exists(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "json",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        return {
            "type": "json",
            "description": "Local JSON file storage",
            "data_dir": str(self.data_dir),
            "auth_keys_file_path": str(self.auth_keys_path),
            "auth_keys_file_exists": self.auth_keys_path.exists(),
            "users_file_path": str(self.users_path),
            "sessions_file_path": str(self.sessions_path),
            "redeem_codes_file_path": str(self.redeem_codes_path),
            "channels_file_path": str(self.channels_path),
            "prompt_library_file_path": str(self.prompt_library_path),
            "image_records_file_path": str(self.image_records_path),
        }
