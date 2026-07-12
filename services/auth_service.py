from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import uuid
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Literal

from services.config import config
from services.repositories.base import RepositoryProvider
from services.repositories.storage_adapter import RepositoryStorageAdapter
from services.storage.base import StorageBackend

AuthRole = Literal["admin", "user"]

_SESSION_DAYS = 30
_PASSWORD_ITERATIONS = 210_000
_EMAIL_VERIFICATION_MINUTES = 10
IMAGE_CHANNEL_CONFIG_KEY = "image_channel_config"
DEFAULT_USER_IMAGE_CHANNEL_MODELS = ["gpt-image-2", "gpt-5.5"]
DEFAULT_USER_IMAGE_CHANNEL_TIMEOUT = 600
_UNSET = object()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_verification_code(email: str, code: str) -> str:
    return _hash_key(f"{email.strip().lower()}:{code.strip()}")


def _hash_password_reset_code(email: str, code: str) -> str:
    return _hash_key(f"password-reset:{email.strip().lower()}:{code.strip()}")


def _hash_password(password: str, salt: str | None = None) -> str:
    real_salt = salt or secrets.token_urlsafe(18)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        real_salt.encode("utf-8"),
        _PASSWORD_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${_PASSWORD_ITERATIONS}${real_salt}${digest}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = str(encoded or "").split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        rounds = int(iterations)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        rounds,
    ).hex()
    return hmac.compare_digest(candidate, digest)


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + max(0, int(months or 0))
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _normalize_subscription_entitlements(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, object]] = []
    for raw in value[-100:]:
        if not isinstance(raw, dict):
            continue
        expires_at = _parse_time(raw.get("expires_at"))
        starts_at = _parse_time(raw.get("starts_at"))
        try:
            concurrency = max(1, min(50, int(raw.get("concurrency") or 1)))
        except (TypeError, ValueError):
            concurrency = 1
        if expires_at is None:
            continue
        items.append({
            "plan_id": str(raw.get("plan_id") or "").strip(),
            "plan_name": str(raw.get("plan_name") or "").strip(),
            "order_id": str(raw.get("order_id") or "").strip(),
            "concurrency": concurrency,
            "starts_at": (starts_at or _now()).isoformat(),
            "expires_at": expires_at.isoformat(),
        })
    return items


def _active_subscription_summary(user: dict[str, object], now: datetime | None = None) -> dict[str, object] | None:
    current = now or _now()
    active = [
        item
        for item in _normalize_subscription_entitlements(user.get("subscription_entitlements"))
        if (_parse_time(item.get("starts_at")) or current) <= current
        and (_parse_time(item.get("expires_at")) or current) > current
    ]
    if not active:
        return None
    selected = max(
        active,
        key=lambda item: (int(item.get("concurrency") or 1), _parse_time(item.get("expires_at")) or current),
    )
    return {
        "plan_id": selected.get("plan_id"),
        "plan_name": selected.get("plan_name"),
        "concurrency": max(int(item.get("concurrency") or 1) for item in active),
        "expires_at": selected.get("expires_at"),
    }


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _quota_value(value: object) -> float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, parsed), 8) if math.isfinite(parsed) else 0.0


def _normalize_channel_models(value: object) -> list[str]:
    if isinstance(value, str):
        candidates = value.replace(";", ",").replace("\n", ",").split(",")
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = DEFAULT_USER_IMAGE_CHANNEL_MODELS
    seen: set[str] = set()
    models: list[str] = []
    for item in candidates:
        model = _clean_text(item)
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return models or list(DEFAULT_USER_IMAGE_CHANNEL_MODELS)


def _normalize_user_image_channel_config(
    raw: object,
    current: object = None,
    *,
    include_api_key: bool = False,
) -> dict[str, object]:
    raw_config = raw if isinstance(raw, dict) else {}
    current_config = current if isinstance(current, dict) else {}

    def pick(key: str, default: object = "") -> object:
        return raw_config[key] if key in raw_config else current_config.get(key, default)

    api_key = _clean_text(raw_config.get("api_key")) if "api_key" in raw_config else ""
    if not api_key:
        api_key = _clean_text(current_config.get("api_key"))

    try:
        timeout = max(
            5,
            int(pick("timeout", DEFAULT_USER_IMAGE_CHANNEL_TIMEOUT) or DEFAULT_USER_IMAGE_CHANNEL_TIMEOUT),
        )
    except (TypeError, ValueError):
        timeout = DEFAULT_USER_IMAGE_CHANNEL_TIMEOUT

    normalized = {
        "enabled": _bool(pick("enabled", False), False),
        "name": _clean_text(pick("name", "")) or "个人生图渠道",
        "base_url": _clean_text(pick("base_url", "")).rstrip("/"),
        "models": _normalize_channel_models(pick("models", DEFAULT_USER_IMAGE_CHANNEL_MODELS)),
        "timeout": timeout,
    }
    if include_api_key:
        normalized["api_key"] = api_key
    else:
        normalized["has_api_key"] = bool(api_key)
    return normalized


class AuthService:
    def __init__(self, storage: StorageBackend | RepositoryProvider):
        self.repositories = storage if isinstance(storage, RepositoryProvider) else None
        self.storage = RepositoryStorageAdapter(storage) if isinstance(storage, RepositoryProvider) else storage
        self._lock = RLock()
        self._items = self._load_keys()
        self._users = self._load_users()
        self._sessions = self._load_sessions()
        self._redeem_codes = self._load_redeem_codes()
        self._quota_reservations: dict[str, dict[str, object]] = {}
        self._last_used_flush_at: dict[str, datetime] = {}
        self.expire_quota_reservations()

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _clean_email(value: object) -> str:
        return str(value or "").strip().lower()

    def _normalize_item(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        role = self._clean(raw.get("role")).lower()
        if role not in {"admin", "user"}:
            return None
        key_hash = self._clean(raw.get("key_hash"))
        if not key_hash:
            return None
        item_id = self._clean(raw.get("id")) or uuid.uuid4().hex[:12]
        name = self._clean(raw.get("name")) or ("管理员密钥" if role == "admin" else "普通用户")
        created_at = self._clean(raw.get("created_at")) or _now_iso()
        last_used_at = self._clean(raw.get("last_used_at")) or None
        return {
            "id": item_id,
            "name": name,
            "role": role,
            "key_hash": key_hash,
            "enabled": bool(raw.get("enabled", True)),
            "created_at": created_at,
            "last_used_at": last_used_at,
        }

    def _normalize_user(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        email = self._clean_email(raw.get("email"))
        role = self._clean(raw.get("role")).lower() or "user"
        if role not in {"admin", "user"} or not email:
            return None
        item_id = self._clean(raw.get("id")) or uuid.uuid4().hex[:12]
        status = self._clean(raw.get("status")).lower() or "active"
        if status not in {"active", "disabled", "pending"}:
            status = "active"
        try:
            quota = _quota_value(raw.get("quota"))
        except (TypeError, ValueError):
            quota = 0
        try:
            quota_used = _quota_value(raw.get("quota_used"))
        except (TypeError, ValueError):
            quota_used = 0
        name = self._clean(raw.get("name")) or email.split("@")[0]
        quota_expires_at = self._clean(raw.get("quota_expires_at")) or None
        return {
            "id": item_id,
            "email": email,
            "name": name,
            "role": role,
            "status": status,
            "password_hash": self._clean(raw.get("password_hash")),
            "quota": quota,
            "quota_used": quota_used,
            "quota_expires_at": quota_expires_at,
            "subscription_entitlements": _normalize_subscription_entitlements(raw.get("subscription_entitlements")),
            "subscription_admin_override": _bool(raw.get("subscription_admin_override"), False),
            "email_verified": _bool(raw.get("email_verified"), status != "pending"),
            "email_verified_at": self._clean(raw.get("email_verified_at")) or None,
            "email_verification_hash": self._clean(raw.get("email_verification_hash")),
            "email_verification_expires_at": self._clean(raw.get("email_verification_expires_at")) or None,
            "email_verification_sent_at": self._clean(raw.get("email_verification_sent_at")) or None,
            "password_reset_hash": self._clean(raw.get("password_reset_hash")),
            "password_reset_expires_at": self._clean(raw.get("password_reset_expires_at")) or None,
            "password_reset_sent_at": self._clean(raw.get("password_reset_sent_at")) or None,
            "auth_provider": self._clean(raw.get("auth_provider")) or "password",
            "webdav_config": raw.get("webdav_config") if isinstance(raw.get("webdav_config"), dict) else {},
            IMAGE_CHANNEL_CONFIG_KEY: _normalize_user_image_channel_config(
                raw.get(IMAGE_CHANNEL_CONFIG_KEY),
                include_api_key=True,
            ),
            "created_at": self._clean(raw.get("created_at")) or _now_iso(),
            "updated_at": self._clean(raw.get("updated_at")) or _now_iso(),
            "last_login_at": self._clean(raw.get("last_login_at")) or None,
        }

    def _normalize_session(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        session_id = self._clean(raw.get("id")) or uuid.uuid4().hex[:16]
        token_hash = self._clean(raw.get("token_hash"))
        user_id = self._clean(raw.get("user_id"))
        if not token_hash or not user_id:
            return None
        expires_at = self._clean(raw.get("expires_at")) or (_now() + timedelta(days=_SESSION_DAYS)).isoformat()
        return {
            "id": session_id,
            "token_hash": token_hash,
            "user_id": user_id,
            "created_at": self._clean(raw.get("created_at")) or _now_iso(),
            "last_used_at": self._clean(raw.get("last_used_at")) or None,
            "expires_at": expires_at,
        }

    def _normalize_redeem_code(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        code = self._clean(raw.get("code")).upper()
        if not code:
            return None
        try:
            quota = max(1, int(raw.get("quota") or raw.get("amount") or 1))
        except (TypeError, ValueError):
            quota = 1
        try:
            max_uses = max(1, int(raw.get("max_uses") or 1))
        except (TypeError, ValueError):
            max_uses = 1
        try:
            valid_months = max(0, int(raw.get("valid_months") or raw.get("quota_valid_months") or 0))
        except (TypeError, ValueError):
            valid_months = 0
        used_by = raw.get("used_by") if isinstance(raw.get("used_by"), list) else []
        status = self._clean(raw.get("status")).lower() or "enabled"
        if status not in {"enabled", "disabled"}:
            status = "enabled"
        return {
            "id": self._clean(raw.get("id")) or uuid.uuid4().hex[:12],
            "code": code,
            "quota": quota,
            "status": status,
            "max_uses": max_uses,
            "valid_months": valid_months,
            "used_count": min(max_uses, int(raw.get("used_count") or len(used_by))),
            "used_by": used_by,
            "expires_at": self._clean(raw.get("expires_at")) or None,
            "created_at": self._clean(raw.get("created_at")) or _now_iso(),
            "created_by": self._clean(raw.get("created_by")),
            "note": self._clean(raw.get("note")),
        }

    def _load_keys(self) -> list[dict[str, object]]:
        try:
            items = self.storage.load_auth_keys()
        except Exception:
            return []
        if not isinstance(items, list):
            return []
        return [normalized for item in items if (normalized := self._normalize_item(item)) is not None]

    def _load_users(self) -> list[dict[str, object]]:
        try:
            items = self.storage.load_users()
        except Exception:
            return []
        if not isinstance(items, list):
            return []
        return [normalized for item in items if (normalized := self._normalize_user(item)) is not None]

    def _load_sessions(self) -> list[dict[str, object]]:
        try:
            items = self.storage.load_sessions()
        except Exception:
            return []
        if not isinstance(items, list):
            return []
        now = _now()
        return [
            normalized
            for item in items
            if (normalized := self._normalize_session(item)) is not None
            and ((_parse_time(normalized.get("expires_at")) or now) >= now)
        ]

    def _load_redeem_codes(self) -> list[dict[str, object]]:
        try:
            items = self.storage.load_redeem_codes()
        except Exception:
            return []
        if not isinstance(items, list):
            return []
        return [normalized for item in items if (normalized := self._normalize_redeem_code(item)) is not None]

    def _save_keys(self) -> None:
        self.storage.save_auth_keys(self._items)

    def _save_users(self) -> None:
        self.storage.save_users(self._users)

    def _save_sessions(self) -> None:
        self.storage.save_sessions(self._sessions)

    def _save_redeem_codes(self) -> None:
        self.storage.save_redeem_codes(self._redeem_codes)

    @staticmethod
    def _public_item(item: dict[str, object]) -> dict[str, object]:
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "role": item.get("role"),
            "enabled": bool(item.get("enabled", True)),
            "created_at": item.get("created_at"),
            "last_used_at": item.get("last_used_at"),
        }

    @staticmethod
    def _public_user(user: dict[str, object], stats: dict[str, object] | None = None) -> dict[str, object]:
        subscription = _active_subscription_summary(user)
        return {
            "id": user.get("id"),
            "email": user.get("email"),
            "name": user.get("name"),
            "role": user.get("role"),
            "status": user.get("status"),
            "quota": _quota_value(user.get("quota")),
            "quota_used": _quota_value(user.get("quota_used")),
            "quota_expires_at": user.get("quota_expires_at"),
            "subscription": subscription,
            "subscription_concurrency": int((subscription or {}).get("concurrency") or 0),
            "email_verified": bool(user.get("email_verified", user.get("status") != "pending")),
            "email_verified_at": user.get("email_verified_at"),
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
            "last_login_at": user.get("last_login_at"),
            "auth_provider": user.get("auth_provider"),
            "image_channel": _normalize_user_image_channel_config(
                user.get(IMAGE_CHANNEL_CONFIG_KEY),
                include_api_key=False,
            ),
            "image_count": int((stats or {}).get("image_count") or 0),
            "spent_quota": _quota_value(user.get("quota_used")),
        }

    def _find_user_index_by_id(self, user_id: str) -> int:
        for index, user in enumerate(self._users):
            if self._clean(user.get("id")) == user_id:
                return index
        return -1

    def _find_user_index_by_email(self, email: str) -> int:
        normalized_email = self._clean_email(email)
        for index, user in enumerate(self._users):
            if self._clean_email(user.get("email")) == normalized_email:
                return index
        return -1

    def _image_stats_by_user(self) -> dict[str, dict[str, int | float]]:
        stats: dict[str, dict[str, int | float]] = {}
        try:
            records = self.storage.load_image_records()
        except Exception:
            records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            user_id = self._clean(record.get("owner_user_id"))
            if not user_id:
                continue
            item = stats.setdefault(user_id, {"image_count": 0, "spent_quota": 0})
            item["image_count"] += 1
            item["spent_quota"] = _quota_value(item["spent_quota"] + _quota_value(record.get("quota_cost")))
        return stats

    @staticmethod
    def _quota_is_expired(user: dict[str, object], now: datetime | None = None) -> bool:
        expires_at = _parse_time(user.get("quota_expires_at"))
        return expires_at is not None and expires_at <= (now or _now())

    def _clear_expired_quota_locked(self, user: dict[str, object], *, now: datetime | None = None) -> dict[str, object]:
        if not self._quota_is_expired(user, now):
            return user
        next_user = dict(user)
        if _quota_value(next_user.get("quota")) > 0:
            next_user["quota"] = 0
            next_user["updated_at"] = (now or _now()).isoformat()
        return self._normalize_user(next_user) or next_user

    @staticmethod
    def _next_quota_expiry(valid_months: int, now: datetime) -> str | None:
        if valid_months <= 0:
            return None
        return _add_months(now, valid_months).isoformat()

    def list_keys(self, role: AuthRole | None = None) -> list[dict[str, object]]:
        with self._lock:
            items = [item for item in self._items if role is None or item.get("role") == role]
            return [self._public_item(item) for item in items]

    def create_key(self, *, role: AuthRole, name: str = "") -> tuple[dict[str, object], str]:
        normalized_name = self._clean(name) or ("管理员密钥" if role == "admin" else "普通用户")
        raw_key = f"sk-{secrets.token_urlsafe(24)}"
        item = {
            "id": uuid.uuid4().hex[:12],
            "name": normalized_name,
            "role": role,
            "key_hash": _hash_key(raw_key),
            "enabled": True,
            "created_at": _now_iso(),
            "last_used_at": None,
        }
        with self._lock:
            self._items.append(item)
            self._save_keys()
            return self._public_item(item), raw_key

    def update_key(
        self,
        key_id: str,
        updates: dict[str, object],
        *,
        role: AuthRole | None = None,
    ) -> dict[str, object] | None:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                if role is not None and item.get("role") != role:
                    return None
                next_item = dict(item)
                if "name" in updates and updates.get("name") is not None:
                    next_item["name"] = self._clean(updates.get("name")) or next_item.get("name") or "普通用户"
                if "enabled" in updates and updates.get("enabled") is not None:
                    next_item["enabled"] = bool(updates.get("enabled"))
                self._items[index] = next_item
                self._save_keys()
                return self._public_item(next_item)
        return None

    def delete_key(self, key_id: str, *, role: AuthRole | None = None) -> bool:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return False
        with self._lock:
            before = len(self._items)
            self._items = [
                item
                for item in self._items
                if not (item.get("id") == normalized_id and (role is None or item.get("role") == role))
            ]
            if len(self._items) == before:
                return False
            self._save_keys()
            return True

    def email_exists(self, email: str) -> bool:
        with self._lock:
            return self._find_user_index_by_email(email) >= 0

    def create_user(
        self,
        *,
        email: str,
        password: str,
        name: str = "",
        quota: float = 0,
        quota_expires_at: str | None = None,
        role: AuthRole = "user",
        status: str = "active",
        email_verified: bool | None = None,
        create_session: bool = True,
    ) -> tuple[dict[str, object], str]:
        normalized_email = self._clean_email(email)
        if "@" not in normalized_email:
            raise ValueError("email is invalid")
        if len(str(password or "")) < 6:
            raise ValueError("password must be at least 6 characters")
        with self._lock:
            if self._find_user_index_by_email(normalized_email) >= 0:
                raise ValueError("email already exists")
            now = _now_iso()
            normalized_status = self._clean(status).lower() or "active"
            verified = bool(email_verified) if email_verified is not None else normalized_status != "pending"
            user = self._normalize_user({
                "id": uuid.uuid4().hex[:12],
                "email": normalized_email,
                "name": name or normalized_email.split("@")[0],
                "role": role,
                "status": normalized_status,
                "password_hash": _hash_password(password),
                "quota": quota,
                "quota_used": 0,
                "quota_expires_at": quota_expires_at,
                "email_verified": verified,
                "email_verified_at": now if verified else None,
                "created_at": now,
                "updated_at": now,
                "last_login_at": None,
            })
            if user is None:
                raise ValueError("user payload is invalid")
            self._users.append(user)
            token = self._create_session_locked(str(user["id"])) if create_session and user.get("status") == "active" else ""
            self._save_users()
            if token:
                self._save_sessions()
            return self._public_user(user), token

    def create_email_verification(self, email: str, password: str | None = None) -> tuple[dict[str, object], str]:
        normalized_email = self._clean_email(email)
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = _now()
        expires_at = now + timedelta(minutes=_EMAIL_VERIFICATION_MINUTES)
        with self._lock:
            index = self._find_user_index_by_email(normalized_email)
            if index < 0:
                raise ValueError("user not found")
            user = dict(self._users[index])
            if user.get("status") == "active" and bool(user.get("email_verified", True)):
                raise ValueError("email is already verified")
            if user.get("status") == "disabled":
                raise ValueError("user is disabled")
            if password is not None and not _verify_password(str(password or ""), self._clean(user.get("password_hash"))):
                raise ValueError("email or password is invalid")
            user["email_verification_hash"] = _hash_verification_code(normalized_email, code)
            user["email_verification_expires_at"] = expires_at.isoformat()
            user["email_verification_sent_at"] = now.isoformat()
            user["email_verified"] = False
            user["updated_at"] = now.isoformat()
            normalized = self._normalize_user(user)
            if normalized is None:
                raise ValueError("user payload is invalid")
            self._users[index] = normalized
            self._save_users()
            return self._public_user(normalized), code

    def create_password_reset(self, email: str) -> tuple[dict[str, object], str]:
        normalized_email = self._clean_email(email)
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = _now()
        expires_at = now + timedelta(minutes=_EMAIL_VERIFICATION_MINUTES)
        with self._lock:
            index = self._find_user_index_by_email(normalized_email)
            if index < 0:
                raise ValueError("user not found")
            user = dict(self._users[index])
            if user.get("status") == "pending" or not bool(user.get("email_verified", True)):
                raise ValueError("email verification is required")
            if user.get("status") != "active":
                raise ValueError("user is disabled")
            user["password_reset_hash"] = _hash_password_reset_code(normalized_email, code)
            user["password_reset_expires_at"] = expires_at.isoformat()
            user["password_reset_sent_at"] = now.isoformat()
            user["updated_at"] = now.isoformat()
            normalized = self._normalize_user(user)
            if normalized is None:
                raise ValueError("user payload is invalid")
            self._users[index] = normalized
            self._save_users()
            return self._public_user(normalized), code

    def reset_password_with_code(self, *, email: str, code: str, password: str) -> dict[str, object]:
        normalized_email = self._clean_email(email)
        normalized_code = self._clean(code)
        next_password = str(password or "").strip()
        if not normalized_code:
            raise ValueError("verification code is required")
        if len(next_password) < 6:
            raise ValueError("password must be at least 6 characters")
        with self._lock:
            index = self._find_user_index_by_email(normalized_email)
            if index < 0:
                raise ValueError("email or verification code is invalid")
            user = self._users[index]
            if user.get("status") == "pending" or not bool(user.get("email_verified", True)):
                raise ValueError("email verification is required")
            if user.get("status") != "active":
                raise ValueError("user is disabled")
            expires_at = _parse_time(user.get("password_reset_expires_at"))
            if expires_at is None or expires_at < _now():
                raise ValueError("verification code is expired")
            expected_hash = self._clean(user.get("password_reset_hash"))
            candidate_hash = _hash_password_reset_code(normalized_email, normalized_code)
            if not expected_hash or not hmac.compare_digest(expected_hash, candidate_hash):
                raise ValueError("email or verification code is invalid")
            now = _now_iso()
            next_user = dict(user)
            next_user["password_hash"] = _hash_password(next_password)
            next_user["password_reset_hash"] = ""
            next_user["password_reset_expires_at"] = None
            next_user["password_reset_sent_at"] = None
            next_user["updated_at"] = now
            self._users[index] = self._normalize_user(next_user) or next_user
            user_id = self._clean(next_user.get("id"))
            self._sessions = [
                session
                for session in self._sessions
                if self._clean(session.get("user_id")) != user_id
            ]
            self._save_users()
            self._save_sessions()
            return self._public_user(self._users[index])

    def verify_email(self, *, email: str, code: str) -> tuple[dict[str, object], str]:
        normalized_email = self._clean_email(email)
        normalized_code = self._clean(code)
        if not normalized_code:
            raise ValueError("verification code is required")
        with self._lock:
            index = self._find_user_index_by_email(normalized_email)
            if index < 0:
                raise ValueError("email or verification code is invalid")
            user = self._users[index]
            if user.get("status") == "active" and bool(user.get("email_verified", True)):
                raise ValueError("email is already verified")
            if user.get("status") == "disabled":
                raise ValueError("user is disabled")
            expires_at = _parse_time(user.get("email_verification_expires_at"))
            if expires_at is None or expires_at < _now():
                raise ValueError("verification code is expired")
            expected_hash = self._clean(user.get("email_verification_hash"))
            candidate_hash = _hash_verification_code(normalized_email, normalized_code)
            if not expected_hash or not hmac.compare_digest(expected_hash, candidate_hash):
                raise ValueError("email or verification code is invalid")
            now = _now_iso()
            next_user = dict(user)
            next_user["status"] = "active"
            next_user["email_verified"] = True
            next_user["email_verified_at"] = now
            next_user["email_verification_hash"] = ""
            next_user["email_verification_expires_at"] = None
            next_user["updated_at"] = now
            self._users[index] = self._normalize_user(next_user) or next_user
            token = self._create_session_locked(str(next_user["id"]))
            self._save_users()
            self._save_sessions()
            return self._public_user(self._users[index]), token

    def login_user(self, *, email: str, password: str) -> tuple[dict[str, object], str]:
        normalized_email = self._clean_email(email)
        with self._lock:
            index = self._find_user_index_by_email(normalized_email)
            if index < 0:
                raise ValueError("email or password is invalid")
            user = self._users[index]
            if user.get("status") == "pending" or not bool(user.get("email_verified", True)):
                raise ValueError("email verification is required")
            if user.get("status") != "active":
                raise ValueError("user is disabled")
            if not _verify_password(str(password or ""), self._clean(user.get("password_hash"))):
                raise ValueError("email or password is invalid")
            next_user = dict(user)
            next_user["last_login_at"] = _now_iso()
            next_user["updated_at"] = next_user["last_login_at"]
            self._users[index] = next_user
            token = self._create_session_locked(str(next_user["id"]))
            self._save_users()
            self._save_sessions()
            return self._public_user(next_user), token

    def _create_session_locked(self, user_id: str) -> str:
        token = f"yai-{secrets.token_urlsafe(32)}"
        session = {
            "id": uuid.uuid4().hex[:16],
            "token_hash": _hash_key(token),
            "user_id": user_id,
            "created_at": _now_iso(),
            "last_used_at": None,
            "expires_at": (_now() + timedelta(days=_SESSION_DAYS)).isoformat(),
        }
        self._sessions.append(session)
        return token

    def get_user(self, user_id: str) -> dict[str, object] | None:
        with self._lock:
            index = self._find_user_index_by_id(self._clean(user_id))
            if index < 0:
                return None
            normalized_user = self._clear_expired_quota_locked(self._users[index])
            if normalized_user != self._users[index]:
                self._users[index] = normalized_user
                self._save_users()
            stats = self._image_stats_by_user().get(user_id)
            return self._public_user(self._users[index], stats)

    def list_users(self, query: str = "", status: str = "", role: str = "") -> list[dict[str, object]]:
        query_text = self._clean(query).lower()
        status_text = self._clean(status).lower()
        role_text = self._clean(role).lower()
        with self._lock:
            stats = self._image_stats_by_user()
            users = []
            changed = False
            for index, user in enumerate(self._users):
                normalized_user = self._clear_expired_quota_locked(user)
                if normalized_user != user:
                    self._users[index] = normalized_user
                    user = normalized_user
                    changed = True
                if status_text and user.get("status") != status_text:
                    continue
                if role_text and user.get("role") != role_text:
                    continue
                searchable = f"{user.get('email')} {user.get('name')}".lower()
                if query_text and query_text not in searchable:
                    continue
                users.append(self._public_user(user, stats.get(str(user.get("id")))))
            if changed:
                self._save_users()
            users.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
            return users

    def update_user(self, user_id: str, updates: dict[str, object]) -> dict[str, object] | None:
        normalized_id = self._clean(user_id)
        with self._lock:
            index = self._find_user_index_by_id(normalized_id)
            if index < 0:
                return None
            current = dict(self._users[index])
            if "email" in updates and updates.get("email") is not None:
                email = self._clean_email(updates.get("email"))
                if "@" not in email:
                    raise ValueError("email is invalid")
                existing = self._find_user_index_by_email(email)
                if existing >= 0 and existing != index:
                    raise ValueError("email already exists")
                current["email"] = email
            if "name" in updates and updates.get("name") is not None:
                current["name"] = self._clean(updates.get("name")) or current.get("name")
            if "status" in updates and updates.get("status") is not None:
                status = self._clean(updates.get("status")).lower()
                if status not in {"active", "disabled", "pending"}:
                    raise ValueError("status is invalid")
                current["status"] = status
                if status == "active" and "email_verified" not in updates:
                    current["email_verified"] = True
                    current["email_verified_at"] = current.get("email_verified_at") or _now_iso()
            if "quota" in updates and updates.get("quota") is not None:
                current["quota"] = _quota_value(updates.get("quota"))
            if "quota_expires_at" in updates:
                current["quota_expires_at"] = self._clean(updates.get("quota_expires_at")) or None
            if IMAGE_CHANNEL_CONFIG_KEY in updates and isinstance(updates.get(IMAGE_CHANNEL_CONFIG_KEY), dict):
                current[IMAGE_CHANNEL_CONFIG_KEY] = _normalize_user_image_channel_config(
                    updates.get(IMAGE_CHANNEL_CONFIG_KEY),
                    current.get(IMAGE_CHANNEL_CONFIG_KEY),
                    include_api_key=True,
                )
            current["updated_at"] = _now_iso()
            user = self._normalize_user(current)
            if user is None:
                return None
            self._users[index] = user
            self._save_users()
            return self._public_user(user)

    def get_user_image_channel_config(self, user_id: str, *, include_api_key: bool = False) -> dict[str, object]:
        with self._lock:
            index = self._find_user_index_by_id(self._clean(user_id))
            if index < 0:
                raise ValueError("user not found")
            return _normalize_user_image_channel_config(
                self._users[index].get(IMAGE_CHANNEL_CONFIG_KEY),
                include_api_key=include_api_key,
            )

    def merge_user_image_channel_config(
        self,
        user_id: str,
        updates: dict[str, object],
        *,
        include_api_key: bool = False,
    ) -> dict[str, object]:
        with self._lock:
            index = self._find_user_index_by_id(self._clean(user_id))
            if index < 0:
                raise ValueError("user not found")
            normalized = _normalize_user_image_channel_config(
                updates,
                self._users[index].get(IMAGE_CHANNEL_CONFIG_KEY),
                include_api_key=True,
            )
            if include_api_key:
                return normalized
            return _normalize_user_image_channel_config(normalized, include_api_key=False)

    def save_user_image_channel_config(self, user_id: str, updates: dict[str, object]) -> dict[str, object]:
        normalized_id = self._clean(user_id)
        with self._lock:
            index = self._find_user_index_by_id(normalized_id)
            if index < 0:
                raise ValueError("user not found")
            normalized = _normalize_user_image_channel_config(
                updates,
                self._users[index].get(IMAGE_CHANNEL_CONFIG_KEY),
                include_api_key=True,
            )
            if _bool(normalized.get("enabled")):
                if not _clean_text(normalized.get("base_url")):
                    raise ValueError("base_url is required when personal image channel is enabled")
                if not _clean_text(normalized.get("api_key")):
                    raise ValueError("api_key is required when personal image channel is enabled")
            current = dict(self._users[index])
            current[IMAGE_CHANNEL_CONFIG_KEY] = normalized
            current["updated_at"] = _now_iso()
            user = self._normalize_user(current)
            if user is None:
                raise ValueError("user payload is invalid")
            self._users[index] = user
            self._save_users()
            return _normalize_user_image_channel_config(user.get(IMAGE_CHANNEL_CONFIG_KEY), include_api_key=False)

    def delete_user(self, user_id: str) -> bool:
        normalized_id = self._clean(user_id)
        if not normalized_id:
            return False
        with self._lock:
            index = self._find_user_index_by_id(normalized_id)
            if index < 0:
                return False
            self._users.pop(index)
            self._sessions = [
                session
                for session in self._sessions
                if self._clean(session.get("user_id")) != normalized_id
            ]
            self._save_users()
            self._save_sessions()
            return True

    def delete_users(self, user_ids: list[str]) -> int:
        normalized_ids = {self._clean(user_id) for user_id in user_ids}
        normalized_ids.discard("")
        if not normalized_ids:
            return 0
        with self._lock:
            before = len(self._users)
            self._users = [
                user
                for user in self._users
                if self._clean(user.get("id")) not in normalized_ids
            ]
            removed = before - len(self._users)
            if removed <= 0:
                return 0
            self._sessions = [
                session
                for session in self._sessions
                if self._clean(session.get("user_id")) not in normalized_ids
            ]
            self._save_users()
            self._save_sessions()
            return removed

    def reset_password(self, user_id: str, password: str | None = None) -> tuple[dict[str, object], str] | None:
        next_password = str(password or "").strip() or secrets.token_urlsafe(10)
        if len(next_password) < 6:
            raise ValueError("password must be at least 6 characters")
        normalized_id = self._clean(user_id)
        if not normalized_id:
            return None
        with self._lock:
            index = self._find_user_index_by_id(normalized_id)
            if index < 0:
                return None
            user = dict(self._users[index])
            user["password_hash"] = _hash_password(next_password)
            user["password_reset_hash"] = ""
            user["password_reset_expires_at"] = None
            user["password_reset_sent_at"] = None
            user["updated_at"] = _now_iso()
            self._users[index] = user
            self._sessions = [
                session
                for session in self._sessions
                if self._clean(session.get("user_id")) != normalized_id
            ]
            self._save_users()
            self._save_sessions()
            return self._public_user(user), next_password

    def adjust_user_quota(
        self,
        user_id: str,
        amount: float,
        mode: str = "add",
        quota_expires_at: object = _UNSET,
    ) -> dict[str, object] | None:
        normalized_id = self._clean(user_id)
        with self._lock:
            index = self._find_user_index_by_id(normalized_id)
            if index < 0:
                return None
            user = dict(self._users[index])
            if mode != "set":
                user = self._clear_expired_quota_locked(user)
            current_quota = _quota_value(user.get("quota"))
            next_quota = amount if mode == "set" else current_quota + amount
            user["quota"] = _quota_value(next_quota)
            if quota_expires_at is not _UNSET:
                user["quota_expires_at"] = self._clean(quota_expires_at) or None
            user["updated_at"] = _now_iso()
            self._users[index] = self._normalize_user(user) or user
            self._save_users()
            return self._public_user(self._users[index])

    def grant_subscription(
        self,
        user_id: str,
        *,
        plan_id: str,
        plan_name: str,
        order_id: str,
        quota: float,
        valid_months: int,
        concurrency: int,
    ) -> dict[str, object] | None:
        normalized_id = self._clean(user_id)
        now = _now()
        months = max(1, min(120, int(valid_months or 1)))
        normalized_concurrency = max(1, min(50, int(concurrency or 1)))
        with self._lock:
            index = self._find_user_index_by_id(normalized_id)
            if index < 0:
                return None
            user = self._clear_expired_quota_locked(dict(self._users[index]), now=now)
            entitlements = _normalize_subscription_entitlements(user.get("subscription_entitlements"))
            matching_index = next(
                (
                    item_index
                    for item_index, item in enumerate(entitlements)
                    if str(item.get("plan_id") or "") == self._clean(plan_id)
                    and (_parse_time(item.get("expires_at")) or now) > now
                ),
                -1,
            )
            base_time = now
            if matching_index >= 0:
                base_time = max(now, _parse_time(entitlements[matching_index].get("expires_at")) or now)
            expires_at = _add_months(base_time, months)
            entitlement = {
                "plan_id": self._clean(plan_id),
                "plan_name": self._clean(plan_name),
                "order_id": self._clean(order_id),
                "concurrency": normalized_concurrency,
                "starts_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
            if matching_index >= 0:
                entitlements[matching_index] = entitlement
            else:
                entitlements.append(entitlement)

            user["quota"] = _quota_value(_quota_value(user.get("quota")) + _quota_value(quota))
            current_quota_expiry = _parse_time(user.get("quota_expires_at"))
            user["quota_expires_at"] = max(current_quota_expiry or now, expires_at).isoformat()
            user["subscription_entitlements"] = entitlements
            user["subscription_admin_override"] = False
            user["updated_at"] = now.isoformat()
            self._users[index] = self._normalize_user(user) or user
            self._save_users()
            return self._public_user(self._users[index])

    def task_concurrency(self, user_id: str, default: int = 1) -> int:
        normalized_id = self._clean(user_id)
        with self._lock:
            index = self._find_user_index_by_id(normalized_id)
            if index < 0:
                return max(1, int(default or 1))
            subscription = _active_subscription_summary(self._users[index])
            return max(1, int((subscription or {}).get("concurrency") or default or 1))

    def set_user_subscription(
        self,
        user_id: str,
        *,
        plan_id: str = "",
        plan_name: str = "",
        concurrency: int = 1,
        valid_months: int = 1,
        expires_at: str | None = None,
    ) -> dict[str, object] | None:
        normalized_id = self._clean(user_id)
        now = _now()
        normalized_plan_id = self._clean(plan_id)
        normalized_expiry = _parse_time(expires_at) if expires_at else _add_months(
            now,
            max(1, min(120, int(valid_months or 1))),
        )
        if normalized_plan_id and (normalized_expiry is None or normalized_expiry <= now):
            raise ValueError("subscription expiry must be in the future")
        with self._lock:
            index = self._find_user_index_by_id(normalized_id)
            if index < 0:
                return None
            user = dict(self._users[index])
            entitlements = [
                item
                for item in _normalize_subscription_entitlements(user.get("subscription_entitlements"))
                if (_parse_time(item.get("expires_at")) or now) <= now
            ]
            if normalized_plan_id:
                entitlements.append({
                    "plan_id": normalized_plan_id,
                    "plan_name": self._clean(plan_name),
                    "order_id": f"admin-{int(now.timestamp())}",
                    "concurrency": max(1, min(50, int(concurrency or 1))),
                    "starts_at": now.isoformat(),
                    "expires_at": normalized_expiry.isoformat(),
                })
            user["subscription_entitlements"] = entitlements
            user["subscription_admin_override"] = True
            user["updated_at"] = now.isoformat()
            self._users[index] = self._normalize_user(user) or user
            self._save_users()
            return self._public_user(self._users[index])

    def subscription_is_admin_overridden(self, user_id: str) -> bool:
        with self._lock:
            index = self._find_user_index_by_id(self._clean(user_id))
            return index >= 0 and bool(self._users[index].get("subscription_admin_override"))

    def ensure_quota(self, user_id: str, amount: float) -> None:
        if amount <= 0:
            return
        with self._lock:
            index = self._find_user_index_by_id(self._clean(user_id))
            if index < 0:
                raise ValueError("user not found")
            user = self._users[index]
            if user.get("role") == "admin":
                return
            normalized_user = self._clear_expired_quota_locked(user)
            if normalized_user != user:
                self._users[index] = normalized_user
                self._save_users()
                user = normalized_user
            if _quota_value(user.get("quota")) < _quota_value(amount):
                raise ValueError("剩余额度不足")

    def deduct_quota(self, user_id: str, amount: float) -> dict[str, object] | None:
        if amount <= 0:
            return self.get_user(user_id)
        request_id = f"legacy-deduct-{uuid.uuid4().hex}"
        self.reserve_quota(user_id, amount, request_id)
        self.confirm_quota(request_id)
        return self.get_user(user_id)

    def reserve_quota(
        self,
        user_id: str,
        amount: float,
        request_id: str,
        *,
        ttl_seconds: int = 900,
    ) -> dict[str, object] | None:
        normalized_user_id = self._clean(user_id)
        normalized_request_id = self._clean(request_id)
        normalized_amount = _quota_value(amount)
        if normalized_amount <= 0:
            return None
        if not normalized_request_id:
            raise ValueError("request id is required")
        with self._lock:
            index = self._find_user_index_by_id(normalized_user_id)
            if index < 0:
                raise ValueError("user not found")
            user = self._users[index]
            if user.get("role") == "admin":
                return None
            normalized_user = self._clear_expired_quota_locked(user)
            if normalized_user != user:
                self._users[index] = normalized_user
                user = normalized_user
                self._save_users()
            if self.repositories is not None:
                reservation = self.repositories.quota_reservations.reserve(
                    normalized_user_id,
                    normalized_amount,
                    normalized_request_id,
                    ttl_seconds=ttl_seconds,
                )
                self._users = self._load_users()
                return reservation
            self._expire_quota_reservations_locked()
            existing = self._quota_reservations.get(normalized_request_id)
            if existing is not None:
                return dict(existing)
            user = dict(self._users[index])
            if _quota_value(user.get("quota")) < normalized_amount:
                raise ValueError("剩余额度不足")
            now = _now()
            expires_at = now + timedelta(seconds=max(1, int(ttl_seconds or 900)))
            user["quota"] = _quota_value(_quota_value(user.get("quota")) - normalized_amount)
            user["updated_at"] = now.isoformat()
            self._users[index] = self._normalize_user(user) or user
            reservation = {
                "id": uuid.uuid4().hex,
                "user_id": normalized_user_id,
                "request_id": normalized_request_id,
                "amount": normalized_amount,
                "status": "reserved",
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
            self._quota_reservations[normalized_request_id] = reservation
            self._save_users()
            return dict(reservation)

    def confirm_quota(self, request_id: str, amount: float | None = None) -> dict[str, object] | None:
        normalized_request_id = self._clean(request_id)
        if not normalized_request_id:
            return None
        with self._lock:
            if self.repositories is not None:
                reservation = self.repositories.quota_reservations.confirm(normalized_request_id, amount=amount)
                self._users = self._load_users()
                return reservation
            reservation = self._quota_reservations.get(normalized_request_id)
            if reservation is None:
                return None
            if reservation.get("status") != "reserved":
                return dict(reservation)
            reserved_amount = _quota_value(reservation.get("amount"))
            confirmed_amount = reserved_amount if amount is None else min(_quota_value(amount), reserved_amount)
            refund_amount = _quota_value(reserved_amount - confirmed_amount)
            index = self._find_user_index_by_id(self._clean(reservation.get("user_id")))
            if index >= 0:
                user = dict(self._users[index])
                user["quota"] = _quota_value(_quota_value(user.get("quota")) + refund_amount)
                user["quota_used"] = _quota_value(_quota_value(user.get("quota_used")) + confirmed_amount)
                user["updated_at"] = _now_iso()
                self._users[index] = self._normalize_user(user) or user
                self._save_users()
            reservation.update(
                {
                    "status": "confirmed",
                    "confirmed_at": _now_iso(),
                    "confirmed_amount": confirmed_amount,
                    "released_amount": refund_amount,
                }
            )
            return dict(reservation)

    def release_quota(self, request_id: str) -> dict[str, object] | None:
        normalized_request_id = self._clean(request_id)
        if not normalized_request_id:
            return None
        with self._lock:
            if self.repositories is not None:
                reservation = self.repositories.quota_reservations.release(normalized_request_id)
                self._users = self._load_users()
                return reservation
            reservation = self._quota_reservations.get(normalized_request_id)
            if reservation is None:
                return None
            if reservation.get("status") != "reserved":
                return dict(reservation)
            index = self._find_user_index_by_id(self._clean(reservation.get("user_id")))
            if index >= 0:
                user = dict(self._users[index])
                user["quota"] = _quota_value(_quota_value(user.get("quota")) + _quota_value(reservation.get("amount")))
                user["updated_at"] = _now_iso()
                self._users[index] = self._normalize_user(user) or user
                self._save_users()
            reservation.update({"status": "released", "released_at": _now_iso()})
            return dict(reservation)

    def expire_quota_reservations(self) -> int:
        with self._lock:
            if self.repositories is not None:
                expired = self.repositories.quota_reservations.expire()
                if expired:
                    self._users = self._load_users()
                return expired
            return self._expire_quota_reservations_locked()

    def _expire_quota_reservations_locked(self) -> int:
        now = _now()
        expired = 0
        for reservation in list(self._quota_reservations.values()):
            if reservation.get("status") != "reserved":
                continue
            expires_at = _parse_time(reservation.get("expires_at"))
            if expires_at is None or expires_at > now:
                continue
            index = self._find_user_index_by_id(self._clean(reservation.get("user_id")))
            if index >= 0:
                user = dict(self._users[index])
                user["quota"] = _quota_value(_quota_value(user.get("quota")) + _quota_value(reservation.get("amount")))
                user["updated_at"] = now.isoformat()
                self._users[index] = self._normalize_user(user) or user
            reservation.update({"status": "expired", "expired_at": now.isoformat()})
            expired += 1
        if expired:
            self._save_users()
        return expired

    def list_redeem_codes(self, query: str = "", status: str = "") -> list[dict[str, object]]:
        query_text = self._clean(query).upper()
        status_text = self._clean(status).lower()
        with self._lock:
            if self.repositories is not None:
                self._redeem_codes = self._load_redeem_codes()
            items = []
            for item in self._redeem_codes:
                if query_text and query_text not in str(item.get("code") or ""):
                    continue
                if status_text and item.get("status") != status_text:
                    continue
                items.append(dict(item))
            items.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
            return items

    def create_redeem_codes(
        self,
        *,
        quota: int,
        count: int = 1,
        max_uses: int = 1,
        valid_months: int = 0,
        expires_at: str | None = None,
        created_by: str = "",
        note: str = "",
    ) -> list[dict[str, object]]:
        total = max(1, min(500, int(count or 1)))
        amount = max(1, int(quota or 1))
        uses = max(1, int(max_uses or 1))
        months = max(0, int(valid_months or 0))
        with self._lock:
            if self.repositories is not None:
                self._redeem_codes = self._load_redeem_codes()
            existing_codes = {str(item.get("code") or "") for item in self._redeem_codes}
            created: list[dict[str, object]] = []
            while len(created) < total:
                code = f"YAI-{secrets.token_urlsafe(9).replace('-', '').replace('_', '').upper()[:12]}"
                if code in existing_codes:
                    continue
                item = self._normalize_redeem_code({
                    "id": uuid.uuid4().hex[:12],
                    "code": code,
                    "quota": amount,
                    "status": "enabled",
                    "max_uses": uses,
                    "valid_months": months,
                    "used_count": 0,
                    "used_by": [],
                    "expires_at": expires_at,
                    "created_at": _now_iso(),
                    "created_by": created_by,
                    "note": note,
                })
                if item is None:
                    continue
                existing_codes.add(code)
                created.append(item)
            if self.repositories is not None:
                for item in reversed(created):
                    self.repositories.redeem_codes.upsert(dict(item))
                self._redeem_codes = self._load_redeem_codes()
            else:
                self._redeem_codes = [*created, *self._redeem_codes]
                self._save_redeem_codes()
            return [dict(item) for item in created]

    def update_redeem_code(self, code_id: str, updates: dict[str, object]) -> dict[str, object] | None:
        normalized_id = self._clean(code_id)
        with self._lock:
            if self.repositories is not None:
                self._redeem_codes = self._load_redeem_codes()
            for index, item in enumerate(self._redeem_codes):
                if item.get("id") != normalized_id:
                    continue
                next_item = dict(item)
                for key in ("status", "expires_at", "note", "max_uses", "quota", "valid_months"):
                    if key in updates and updates.get(key) is not None:
                        next_item[key] = updates.get(key)
                normalized = self._normalize_redeem_code(next_item)
                if normalized is None:
                    return None
                if self.repositories is not None:
                    self.repositories.redeem_codes.upsert(dict(normalized))
                    self._redeem_codes = self._load_redeem_codes()
                else:
                    self._redeem_codes[index] = normalized
                    self._save_redeem_codes()
                return dict(normalized)
        return None

    def delete_redeem_codes(self, code_ids: list[str]) -> int:
        normalized_ids = {self._clean(code_id) for code_id in code_ids}
        normalized_ids.discard("")
        if not normalized_ids:
            return 0
        with self._lock:
            if self.repositories is not None:
                removed = 0
                for code_id in normalized_ids:
                    if self.repositories.redeem_codes.delete(code_id):
                        removed += 1
                if removed:
                    self._redeem_codes = self._load_redeem_codes()
                return removed
            before = len(self._redeem_codes)
            self._redeem_codes = [
                item
                for item in self._redeem_codes
                if self._clean(item.get("id")) not in normalized_ids
            ]
            removed = before - len(self._redeem_codes)
            if removed <= 0:
                return 0
            self._save_redeem_codes()
            return removed

    def redeem_code(self, user_id: str, raw_code: str) -> tuple[dict[str, object], dict[str, object]]:
        code = self._clean(raw_code).upper()
        if not code:
            raise ValueError("redeem code is required")
        with self._lock:
            if self.repositories is not None:
                user, item = self.repositories.redeem_codes.redeem(self._clean(user_id), code)
                self._users = self._load_users()
                self._redeem_codes = self._load_redeem_codes()
                return self._public_user(self._normalize_user(user) or user), dict(item)
            user_index = self._find_user_index_by_id(self._clean(user_id))
            if user_index < 0:
                raise ValueError("user not found")
            user = self._users[user_index]
            code_index = next((index for index, item in enumerate(self._redeem_codes) if item.get("code") == code), -1)
            if code_index < 0:
                raise ValueError("redeem code is invalid")
            item = dict(self._redeem_codes[code_index])
            if item.get("status") != "enabled":
                raise ValueError("redeem code is disabled")
            expires_at = _parse_time(item.get("expires_at"))
            if expires_at and expires_at < _now():
                raise ValueError("redeem code is expired")
            max_uses = int(item.get("max_uses") or 1)
            used_by = list(item.get("used_by") or [])
            if int(item.get("used_count") or len(used_by)) >= max_uses:
                raise ValueError("redeem code has been used")
            if any(entry.get("user_id") == user_id for entry in used_by if isinstance(entry, dict)):
                raise ValueError("redeem code has already been used by this user")
            now = _now()
            normalized_user = self._clear_expired_quota_locked(user, now=now)
            if normalized_user != user:
                user = normalized_user
            quota = int(item.get("quota") or 0)
            valid_months = int(item.get("valid_months") or 0)
            quota_expires_at = self._next_quota_expiry(valid_months, now)
            used_by.append({
                "user_id": user.get("id"),
                "email": user.get("email"),
                "quota": quota,
                "valid_months": valid_months,
                "quota_expires_at": quota_expires_at,
                "used_at": now.isoformat(),
            })
            item["used_by"] = used_by
            item["used_count"] = len(used_by)
            if item["used_count"] >= max_uses:
                item["status"] = "disabled"
            next_user = dict(user)
            next_user["quota"] = _quota_value(_quota_value(next_user.get("quota")) + quota)
            if valid_months > 0:
                next_user["quota_expires_at"] = quota_expires_at
            else:
                next_user["quota_expires_at"] = None
            next_user["updated_at"] = now.isoformat()
            self._users[user_index] = self._normalize_user(next_user) or next_user
            self._redeem_codes[code_index] = self._normalize_redeem_code(item) or item
            self._save_users()
            self._save_redeem_codes()
            return self._public_user(self._users[user_index]), dict(self._redeem_codes[code_index])

    def authenticate(self, raw_key: str) -> dict[str, object] | None:
        candidate = self._clean(raw_key)
        if not candidate:
            return None
        candidate_hash = _hash_key(candidate)
        now = _now()
        with self._lock:
            for index, item in enumerate(self._items):
                if not bool(item.get("enabled", True)):
                    continue
                stored_hash = self._clean(item.get("key_hash"))
                if not stored_hash or not hmac.compare_digest(stored_hash, candidate_hash):
                    continue
                next_item = dict(item)
                next_item["last_used_at"] = now.isoformat()
                self._items[index] = next_item
                item_id = self._clean(next_item.get("id"))
                last_flush_at = self._last_used_flush_at.get(item_id)
                if last_flush_at is None or (now - last_flush_at).total_seconds() >= 60:
                    try:
                        self._save_keys()
                        self._last_used_flush_at[item_id] = now
                    except Exception:
                        pass
                return self._public_item(next_item)

            for index, session in enumerate(self._sessions):
                if not hmac.compare_digest(self._clean(session.get("token_hash")), candidate_hash):
                    continue
                expires_at = _parse_time(session.get("expires_at"))
                if expires_at and expires_at < now:
                    self._sessions.pop(index)
                    self._save_sessions()
                    return None
                user_index = self._find_user_index_by_id(self._clean(session.get("user_id")))
                if user_index < 0:
                    return None
                user = self._users[user_index]
                if user.get("status") != "active":
                    return None
                next_session = dict(session)
                next_session["last_used_at"] = now.isoformat()
                self._sessions[index] = next_session
                session_id = self._clean(next_session.get("id"))
                last_flush_at = self._last_used_flush_at.get(session_id)
                if last_flush_at is None or (now - last_flush_at).total_seconds() >= 60:
                    try:
                        self._save_sessions()
                        self._last_used_flush_at[session_id] = now
                    except Exception:
                        pass
                return self._public_user(user)
        return None


auth_service = AuthService(config.get_repository_provider() or config.get_storage_backend())
