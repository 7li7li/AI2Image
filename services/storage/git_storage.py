from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from git import Repo
from git.exc import GitCommandError

from services.storage.base import StorageBackend


class GitStorageBackend(StorageBackend):
    """Git-backed storage for application datasets."""

    def __init__(
        self,
        repo_url: str,
        token: str,
        branch: str = "main",
        auth_keys_file_path: str = "auth_keys.json",
        users_file_path: str = "users.json",
        sessions_file_path: str = "sessions.json",
        redeem_codes_file_path: str = "redeem_codes.json",
        channels_file_path: str = "channels.json",
        prompt_library_file_path: str = "prompt_library.json",
        image_records_file_path: str = "image_records.json",
        local_cache_dir: Path | None = None,
    ):
        self.repo_url = repo_url
        self.token = token
        self.branch = branch
        self.auth_keys_file_path = auth_keys_file_path
        self.users_file_path = users_file_path
        self.sessions_file_path = sessions_file_path
        self.redeem_codes_file_path = redeem_codes_file_path
        self.channels_file_path = channels_file_path
        self.prompt_library_file_path = prompt_library_file_path
        self.image_records_file_path = image_records_file_path

        if local_cache_dir is None:
            local_cache_dir = Path(tempfile.gettempdir()) / "chatgpt2api_git_cache"
        self.local_cache_dir = local_cache_dir
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)
        self.auth_repo_url = self._build_auth_url(repo_url, token)

    @staticmethod
    def _build_auth_url(repo_url: str, token: str) -> str:
        if not token:
            return repo_url
        if repo_url.startswith("https://"):
            return repo_url.replace("https://", f"https://{token}@")
        if repo_url.startswith("git@"):
            repo_url = repo_url.replace("git@", "https://")
            repo_url = repo_url.replace(".com:", ".com/")
            return repo_url.replace("https://", f"https://{token}@")
        return repo_url

    def _clone_or_pull(self) -> Repo:
        repo_path = self.local_cache_dir / "repo"

        if repo_path.exists() and (repo_path / ".git").exists():
            try:
                repo = Repo(repo_path)
                repo.remote("origin").pull(self.branch)
                return repo
            except GitCommandError:
                shutil.rmtree(repo_path)

        return Repo.clone_from(
            self.auth_repo_url,
            repo_path,
            branch=self.branch,
        )

    def load_auth_keys(self) -> list[dict[str, Any]]:
        data = self._load_json_value(self.auth_keys_file_path)
        if isinstance(data, dict):
            data = data.get("items")
        return data if isinstance(data, list) else []

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        self._save_json_file(self.auth_keys_file_path, {"items": auth_keys}, "Update auth keys data")

    def load_users(self) -> list[dict[str, Any]]:
        return self._load_json_file(self.users_file_path)

    def save_users(self, users: list[dict[str, Any]]) -> None:
        self._save_json_file(self.users_file_path, users, "Update users data")

    def load_sessions(self) -> list[dict[str, Any]]:
        return self._load_json_file(self.sessions_file_path)

    def save_sessions(self, sessions: list[dict[str, Any]]) -> None:
        self._save_json_file(self.sessions_file_path, sessions, "Update sessions data")

    def load_redeem_codes(self) -> list[dict[str, Any]]:
        return self._load_json_file(self.redeem_codes_file_path)

    def save_redeem_codes(self, redeem_codes: list[dict[str, Any]]) -> None:
        self._save_json_file(self.redeem_codes_file_path, redeem_codes, "Update redeem codes data")

    def load_channels(self) -> list[dict[str, Any]]:
        return self._load_json_file(self.channels_file_path)

    def save_channels(self, channels: list[dict[str, Any]]) -> None:
        self._save_json_file(self.channels_file_path, channels, "Update channels data")

    def load_prompt_library(self) -> list[dict[str, Any]]:
        return self._load_json_file(self.prompt_library_file_path)

    def save_prompt_library(self, prompts: list[dict[str, Any]]) -> None:
        self._save_json_file(self.prompt_library_file_path, prompts, "Update prompt library data")

    def load_image_records(self) -> list[dict[str, Any]]:
        return self._load_json_file(self.image_records_file_path)

    def save_image_records(self, image_records: list[dict[str, Any]]) -> None:
        self._save_json_file(self.image_records_file_path, image_records, "Update image records data")

    def _load_json_file(self, file_path: str) -> list[dict[str, Any]]:
        data = self._load_json_value(file_path)
        return data if isinstance(data, list) else []

    def _load_json_value(self, file_path: str) -> Any:
        repo = self._clone_or_pull()
        file_full_path = Path(repo.working_dir) / file_path
        if not file_full_path.exists():
            return None
        return json.loads(file_full_path.read_text(encoding="utf-8"))

    def _save_json_file(self, file_path: str, items: Any, message: str) -> None:
        repo = self._clone_or_pull()
        file_full_path = Path(repo.working_dir) / file_path
        file_full_path.parent.mkdir(parents=True, exist_ok=True)
        file_full_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        repo.index.add([file_path])
        if repo.is_dirty():
            repo.index.commit(message)
            repo.remote("origin").push(self.branch)

    def health_check(self) -> dict[str, Any]:
        try:
            repo = self._clone_or_pull()
            return {
                "status": "healthy",
                "backend": "git",
                "repo_url": self._mask_token(self.repo_url),
                "branch": self.branch,
                "auth_keys_file_path": self.auth_keys_file_path,
                "users_file_path": self.users_file_path,
                "sessions_file_path": self.sessions_file_path,
                "redeem_codes_file_path": self.redeem_codes_file_path,
                "channels_file_path": self.channels_file_path,
                "prompt_library_file_path": self.prompt_library_file_path,
                "image_records_file_path": self.image_records_file_path,
                "last_commit": repo.head.commit.hexsha[:8],
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "git",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        return {
            "type": "git",
            "description": "Git private repository storage",
            "repo_url": self._mask_token(self.repo_url),
            "branch": self.branch,
            "auth_keys_file_path": self.auth_keys_file_path,
            "users_file_path": self.users_file_path,
            "sessions_file_path": self.sessions_file_path,
            "redeem_codes_file_path": self.redeem_codes_file_path,
            "channels_file_path": self.channels_file_path,
            "prompt_library_file_path": self.prompt_library_file_path,
            "image_records_file_path": self.image_records_file_path,
        }

    @staticmethod
    def _mask_token(url: str) -> str:
        if "@" in url and "://" in url:
            protocol, rest = url.split("://", 1)
            if "@" in rest:
                _, host = rest.split("@", 1)
                return f"{protocol}://****@{host}"
        return url
