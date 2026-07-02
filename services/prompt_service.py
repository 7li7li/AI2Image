from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from threading import RLock
import uuid
from typing import Any

from services.config import config
from services.repositories.base import RepositoryProvider
from services.repositories.storage_adapter import RepositoryStorageAdapter
from services.storage.base import StorageBackend

ALLOWED_IMAGE_EXTENSIONS = {
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
}
CONTENT_TYPE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}
MAX_PROMPT_ASSET_BYTES = 10 * 1024 * 1024
PUBLIC_PROMPT_STATUS = "public"
PERSONAL_PROMPT_STATUS = "personal"
SUBMITTED_PROMPT_STATUS = "submitted"
REJECTED_PROMPT_STATUS = "rejected"
SHARED_PROMPT_STATUS = "shared"
USER_VISIBLE_PROMPT_STATUSES = {
    PERSONAL_PROMPT_STATUS,
    SUBMITTED_PROMPT_STATUS,
    REJECTED_PROMPT_STATUS,
    PUBLIC_PROMPT_STATUS,
}
ADMIN_VISIBLE_PROMPT_STATUSES = {
    PUBLIC_PROMPT_STATUS,
    SUBMITTED_PROMPT_STATUS,
    REJECTED_PROMPT_STATUS,
}
PROMPT_PAYLOAD_KEYS = (
    "title",
    "description",
    "preview",
    "reference_image_urls",
    "prompt",
    "author",
    "link",
    "mode",
    "image_size",
    "image_count",
    "icon",
    "quick_access",
    "sort_order",
    "category",
    "sub_category",
)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object) -> str:
    return str(value or "").strip()


def _stable_id(raw: dict[str, Any]) -> str:
    seed = "\0".join(
        [
            _clean(raw.get("title")),
            _clean(raw.get("prompt")),
            _clean(raw.get("created")),
        ],
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _normalize_mode(value: object) -> str:
    normalized = _clean(value).lower()
    if normalized in {"edit", "image", "image-to-image", "i2i", "图生图"}:
        return "edit"
    return "generate"


def _normalize_status(value: object) -> str:
    normalized = _clean(value).lower()
    if normalized in {"personal", "private", "mine", "user"}:
        return PERSONAL_PROMPT_STATUS
    if normalized in {"submitted", "pending", "review", "reviewing"}:
        return SUBMITTED_PROMPT_STATUS
    if normalized in {"rejected", "declined"}:
        return REJECTED_PROMPT_STATUS
    if normalized in {"shared", "share"}:
        return SHARED_PROMPT_STATUS
    return PUBLIC_PROMPT_STATUS


def _identity_id(identity: dict[str, object] | None) -> str:
    if not isinstance(identity, dict):
        return ""
    return _clean(identity.get("id") or identity.get("subject_id") or identity.get("user_id"))


def _identity_name(identity: dict[str, object] | None) -> str:
    if not isinstance(identity, dict):
        return ""
    return _clean(identity.get("name") or identity.get("email") or identity.get("id"))


def _identity_email(identity: dict[str, object] | None) -> str:
    if not isinstance(identity, dict):
        return ""
    return _clean(identity.get("email"))


def _identity_role(identity: dict[str, object] | None) -> str:
    if not isinstance(identity, dict):
        return ""
    return _clean(identity.get("role"))


def _is_admin_identity(identity: dict[str, object] | None) -> bool:
    return _identity_role(identity) == "admin"


def _normalize_url_list(value: object) -> list[str]:
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, str):
        candidates = value.replace(",", "\n").splitlines()
    else:
        candidates = []
    return [url for item in candidates if (url := _clean(item))]


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _normalize_prompt(raw: object, *, generated_id: bool = True) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = _clean(raw.get("title"))
    prompt = _clean(raw.get("prompt"))
    if not title or not prompt:
        return None
    item_id = _clean(raw.get("id")) or (_stable_id(raw) if generated_id else uuid.uuid4().hex[:16])
    created = _clean(raw.get("created")) or _clean(raw.get("created_at")) or _now_iso()
    item = {
        "id": item_id,
        "title": title,
        "description": _clean(raw.get("description")),
        "preview": _clean(raw.get("preview")),
        "reference_image_urls": _normalize_url_list(raw.get("reference_image_urls")),
        "prompt": prompt,
        "author": _clean(raw.get("author")),
        "link": _clean(raw.get("link")),
        "mode": _normalize_mode(raw.get("mode")),
        "image_size": _clean(raw.get("image_size")),
        "image_count": _clean(raw.get("image_count")),
        "icon": _clean(raw.get("icon")),
        "quick_access": _bool(raw.get("quick_access"), False),
        "category": _clean(raw.get("category")),
        "sub_category": _clean(raw.get("sub_category")),
        "created": created,
        "updated_at": _clean(raw.get("updated_at")) or created,
        "status": _normalize_status(raw.get("status")),
        "owner_id": _clean(raw.get("owner_id")),
        "owner_name": _clean(raw.get("owner_name")),
        "owner_email": _clean(raw.get("owner_email")),
        "owner_role": _clean(raw.get("owner_role")),
        "source_prompt_id": _clean(raw.get("source_prompt_id")),
        "imported_from_share_id": _clean(raw.get("imported_from_share_id")),
        "submitted_at": _clean(raw.get("submitted_at")),
        "reviewed_at": _clean(raw.get("reviewed_at")),
        "reviewed_by": _clean(raw.get("reviewed_by")),
        "reviewed_by_name": _clean(raw.get("reviewed_by_name")),
        "rejected_at": _clean(raw.get("rejected_at")),
        "rejection_reason": _clean(raw.get("rejection_reason")),
        "share_id": _clean(raw.get("share_id")),
        "shared_at": _clean(raw.get("shared_at")),
    }
    sort_order = _int_or_none(raw.get("sort_order"))
    if sort_order is not None:
        item["sort_order"] = sort_order
    return item


def _status(item: dict[str, Any]) -> str:
    return _normalize_status(item.get("status"))


def _owner_id(item: dict[str, Any]) -> str:
    return _clean(item.get("owner_id"))


def _is_public_prompt(item: dict[str, Any]) -> bool:
    return _status(item) == PUBLIC_PROMPT_STATUS


def _is_shared_prompt(item: dict[str, Any]) -> bool:
    return _status(item) == SHARED_PROMPT_STATUS


def _is_owned_by(item: dict[str, Any], identity: dict[str, object] | None) -> bool:
    owner_id = _owner_id(item)
    return bool(owner_id and owner_id == _identity_id(identity))


def _can_read_prompt(item: dict[str, Any], identity: dict[str, object] | None) -> bool:
    if _is_shared_prompt(item):
        return False
    return _is_public_prompt(item) or _is_owned_by(item, identity)


def _can_user_mutate_prompt(item: dict[str, Any], identity: dict[str, object] | None) -> bool:
    if not _is_owned_by(item, identity):
        return False
    return _status(item) in {PERSONAL_PROMPT_STATUS, SUBMITTED_PROMPT_STATUS, REJECTED_PROMPT_STATUS}


def _prompt_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in PROMPT_PAYLOAD_KEYS if key in item}


def _with_owner(payload: dict[str, Any], identity: dict[str, object], *, status: str) -> dict[str, Any]:
    return {
        **payload,
        "status": status,
        "owner_id": _identity_id(identity),
        "owner_name": _identity_name(identity),
        "owner_email": _identity_email(identity),
        "owner_role": _identity_role(identity),
    }


class PromptLibraryService:
    def __init__(
        self,
        storage: StorageBackend | RepositoryProvider,
        *,
        assets_dir: Path | None = None,
    ):
        self.repositories = storage if isinstance(storage, RepositoryProvider) else None
        self.storage = RepositoryStorageAdapter(storage) if isinstance(storage, RepositoryProvider) else storage
        self.assets_dir = assets_dir or config.prompt_assets_dir
        self._lock = RLock()
        self._items = self._load_items()

    def _load_items(self) -> list[dict[str, Any]]:
        try:
            stored = self.storage.load_prompt_library()
        except Exception:
            stored = []
        items = [_normalize_prompt(item) for item in stored if isinstance(item, dict)]
        normalized = [item for item in items if item is not None]
        return normalized

    def _save(self) -> None:
        self.storage.save_prompt_library(self._items)

    def _current_items(self) -> list[dict[str, Any]]:
        if self.repositories is not None:
            self._items = self._load_items()
        return [dict(item) for item in self._items]

    def _upsert_item(self, item: dict[str, Any], index: int | None = None) -> None:
        if self.repositories is not None:
            self.repositories.prompts.upsert(dict(item))
            self._items = self._load_items()
            return
        if index is None:
            self._items = [item, *self._items]
        else:
            self._items[index] = item
        self._save()

    def _delete_item(self, prompt_id: str) -> bool:
        if self.repositories is not None:
            removed = self.repositories.prompts.delete(prompt_id)
            if removed:
                self._items = self._load_items()
            return removed
        before = len(self._items)
        self._items = [item for item in self._items if item.get("id") != prompt_id]
        if len(self._items) == before:
            return False
        self._save()
        return True

    def _find_item(self, prompt_id: str) -> tuple[int, dict[str, Any]] | None:
        normalized_id = _clean(prompt_id)
        if not normalized_id:
            return None
        for index, current in enumerate(self._current_items()):
            if current.get("id") == normalized_id:
                return index, current
        return None

    def list_prompts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [item for item in self._current_items() if _is_public_prompt(item)]

    def list_available_prompts(self, identity: dict[str, object] | None) -> list[dict[str, Any]]:
        with self._lock:
            return [item for item in self._current_items() if _can_read_prompt(item, identity)]

    def list_admin_prompts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                item
                for item in self._current_items()
                if _status(item) in ADMIN_VISIBLE_PROMPT_STATUSES and not _is_shared_prompt(item)
            ]

    def list_user_prompts(self, identity: dict[str, object]) -> list[dict[str, Any]]:
        with self._lock:
            return [
                item
                for item in self._current_items()
                if _is_owned_by(item, identity) and _status(item) in USER_VISIBLE_PROMPT_STATUSES
            ]

    def create_prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = _normalize_prompt(
            {**payload, "id": uuid.uuid4().hex[:16], "status": PUBLIC_PROMPT_STATUS},
            generated_id=False,
        )
        if item is None:
            raise ValueError("title and prompt are required")
        now = _now_iso()
        item["created"] = item.get("created") or now
        item["updated_at"] = now
        with self._lock:
            self._upsert_item(item)
        return dict(item)

    def create_user_prompt(self, payload: dict[str, Any], identity: dict[str, object]) -> dict[str, Any]:
        item = _normalize_prompt(
            {**_with_owner(payload, identity, status=PERSONAL_PROMPT_STATUS), "id": uuid.uuid4().hex[:16]},
            generated_id=False,
        )
        if item is None:
            raise ValueError("title and prompt are required")
        now = _now_iso()
        item["created"] = item.get("created") or now
        item["updated_at"] = now
        with self._lock:
            self._upsert_item(item)
        return dict(item)

    def update_prompt(self, prompt_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        normalized_id = _clean(prompt_id)
        if not normalized_id:
            return None
        with self._lock:
            items = self._current_items()
            for index, current in enumerate(items):
                if current.get("id") != normalized_id:
                    continue
                candidate = dict(current)
                for key in PROMPT_PAYLOAD_KEYS:
                    if key in payload:
                        candidate[key] = payload.get(key)
                candidate["status"] = PUBLIC_PROMPT_STATUS
                candidate["updated_at"] = _now_iso()
                item = _normalize_prompt(candidate)
                if item is None:
                    raise ValueError("title and prompt are required")
                self._upsert_item(item, index)
                return dict(item)
        return None

    def update_user_prompt(
        self,
        prompt_id: str,
        payload: dict[str, Any],
        identity: dict[str, object],
    ) -> dict[str, Any] | None:
        with self._lock:
            found = self._find_item(prompt_id)
            if found is None:
                return None
            index, current = found
            if not _can_user_mutate_prompt(current, identity):
                return None
            candidate = dict(current)
            for key in PROMPT_PAYLOAD_KEYS:
                if key in payload:
                    candidate[key] = payload.get(key)
            if _status(candidate) == REJECTED_PROMPT_STATUS:
                candidate["status"] = PERSONAL_PROMPT_STATUS
                candidate["rejection_reason"] = ""
            candidate["updated_at"] = _now_iso()
            item = _normalize_prompt(candidate)
            if item is None:
                raise ValueError("title and prompt are required")
            self._upsert_item(item, index)
            return dict(item)

    def submit_user_prompt(self, prompt_id: str, identity: dict[str, object]) -> dict[str, Any] | None:
        with self._lock:
            found = self._find_item(prompt_id)
            if found is None:
                return None
            index, current = found
            if not _can_user_mutate_prompt(current, identity):
                return None
            candidate = dict(current)
            candidate["status"] = SUBMITTED_PROMPT_STATUS
            candidate["submitted_at"] = _now_iso()
            candidate["updated_at"] = candidate["submitted_at"]
            item = _normalize_prompt(candidate)
            if item is None:
                raise ValueError("title and prompt are required")
            self._upsert_item(item, index)
            return dict(item)

    def approve_prompt(self, prompt_id: str, identity: dict[str, object]) -> dict[str, Any] | None:
        with self._lock:
            found = self._find_item(prompt_id)
            if found is None:
                return None
            index, current = found
            if _is_shared_prompt(current):
                return None
            candidate = dict(current)
            now = _now_iso()
            candidate["status"] = PUBLIC_PROMPT_STATUS
            candidate["reviewed_at"] = now
            candidate["reviewed_by"] = _identity_id(identity)
            candidate["reviewed_by_name"] = _identity_name(identity)
            candidate["rejected_at"] = ""
            candidate["rejection_reason"] = ""
            candidate["updated_at"] = now
            item = _normalize_prompt(candidate)
            if item is None:
                raise ValueError("title and prompt are required")
            self._upsert_item(item, index)
            return dict(item)

    def reject_prompt(
        self,
        prompt_id: str,
        identity: dict[str, object],
        *,
        reason: str = "",
    ) -> dict[str, Any] | None:
        with self._lock:
            found = self._find_item(prompt_id)
            if found is None:
                return None
            index, current = found
            if _is_shared_prompt(current):
                return None
            candidate = dict(current)
            now = _now_iso()
            candidate["status"] = REJECTED_PROMPT_STATUS
            candidate["reviewed_at"] = now
            candidate["reviewed_by"] = _identity_id(identity)
            candidate["reviewed_by_name"] = _identity_name(identity)
            candidate["rejected_at"] = now
            candidate["rejection_reason"] = _clean(reason)
            candidate["updated_at"] = now
            item = _normalize_prompt(candidate)
            if item is None:
                raise ValueError("title and prompt are required")
            self._upsert_item(item, index)
            return dict(item)

    def delete_prompt(self, prompt_id: str) -> bool:
        normalized_id = _clean(prompt_id)
        if not normalized_id:
            return False
        with self._lock:
            return self._delete_item(normalized_id)

    def delete_user_prompt(self, prompt_id: str, identity: dict[str, object]) -> bool:
        normalized_id = _clean(prompt_id)
        if not normalized_id:
            return False
        with self._lock:
            found = self._find_item(normalized_id)
            if found is None:
                return False
            _, current = found
            if not _can_user_mutate_prompt(current, identity):
                return False
            return self._delete_item(normalized_id)

    def create_share(
        self,
        payload: dict[str, Any],
        identity: dict[str, object],
        *,
        source_prompt_id: str = "",
    ) -> dict[str, Any]:
        share_id = uuid.uuid4().hex[:16]
        item = _normalize_prompt(
            {
                **_with_owner(payload, identity, status=SHARED_PROMPT_STATUS),
                "id": uuid.uuid4().hex[:16],
                "source_prompt_id": _clean(source_prompt_id),
                "share_id": share_id,
                "shared_at": _now_iso(),
            },
            generated_id=False,
        )
        if item is None:
            raise ValueError("title and prompt are required")
        item["created"] = item.get("created") or item["shared_at"]
        item["updated_at"] = item["shared_at"]
        with self._lock:
            self._upsert_item(item)
        return dict(item)

    def share_prompt(self, prompt_id: str, identity: dict[str, object]) -> dict[str, Any] | None:
        with self._lock:
            found = self._find_item(prompt_id)
            if found is None:
                return None
            _, current = found
            if not _can_read_prompt(current, identity):
                return None
            return self.create_share(_prompt_payload(current), identity, source_prompt_id=_clean(current.get("id")))

    def get_shared_prompt(self, share_id: str) -> dict[str, Any] | None:
        normalized_share_id = _clean(share_id)
        if not normalized_share_id:
            return None
        with self._lock:
            for item in self._current_items():
                if _is_shared_prompt(item) and _clean(item.get("share_id")) == normalized_share_id:
                    return dict(item)
        return None

    def import_shared_prompt(
        self,
        share_id: str,
        identity: dict[str, object],
        *,
        target_scope: str = "",
    ) -> dict[str, Any] | None:
        shared = self.get_shared_prompt(share_id)
        if shared is None:
            return None
        is_public_import = _is_admin_identity(identity) and _clean(target_scope).lower() != "personal"
        status = PUBLIC_PROMPT_STATUS if is_public_import else PERSONAL_PROMPT_STATUS
        payload = _prompt_payload(shared)
        item = _normalize_prompt(
            {
                **_with_owner(payload, identity, status=status),
                "id": uuid.uuid4().hex[:16],
                "source_prompt_id": _clean(shared.get("source_prompt_id") or shared.get("id")),
                "imported_from_share_id": _clean(shared.get("share_id")),
            },
            generated_id=False,
        )
        if item is None:
            raise ValueError("title and prompt are required")
        now = _now_iso()
        item["created"] = now
        item["updated_at"] = now
        with self._lock:
            self._upsert_item(item)
        return dict(item)

    def save_asset(self, data: bytes, *, filename: str = "", content_type: str = "") -> str:
        if not data:
            raise ValueError("image file is empty")
        if len(data) > MAX_PROMPT_ASSET_BYTES:
            raise ValueError("image file is too large")
        suffix = Path(filename or "").suffix.lower()
        content_suffix = CONTENT_TYPE_EXTENSIONS.get(_clean(content_type).lower(), "")
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            suffix = content_suffix
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError("unsupported image type")

        day = datetime.now().strftime("%Y/%m/%d")
        target_dir = self.assets_dir / day
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{uuid.uuid4().hex}{suffix}"
        target.write_bytes(data)
        return f"/prompt-assets/{day}/{target.name}"


prompt_library_service = PromptLibraryService(config.get_repository_provider() or config.get_storage_backend())
