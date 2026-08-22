from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from services.observability import get_current_request_id
from utils.timezone import china_now_text

LOG_TYPE_CALL = "call"
LOG_TYPE_ACCOUNT = "account"
LOG_TYPE_AUDIT = "audit"

_USER_SEARCH_FIELDS = (
    "key_id",
    "key_name",
    "user_id",
    "user_name",
    "user_email",
    "email",
    "name",
    "owner_user_id",
    "owner_name",
    "owner_email",
    "actor_id",
    "actor_name",
    "target_id",
    "target_name",
    "target_email",
)


def _clean_search(value: object) -> str:
    return str(value or "").strip().lower()


def _log_matches_user(item: dict[str, Any], user: str) -> bool:
    query = _clean_search(user)
    if not query:
        return True
    detail = item.get("detail")
    detail_values = detail if isinstance(detail, dict) else {}
    values: list[object] = []
    for key in _USER_SEARCH_FIELDS:
        values.append(item.get(key))
        values.append(detail_values.get(key))
    return any(query in _clean_search(value) for value in values if value is not None)


class LogService:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _system_log_repository(self):
        try:
            from services.config import config

            provider = config.get_repository_provider()
            return provider.system_logs if provider is not None else None
        except Exception:
            return None

    def add(
        self,
        type: str,
        summary: str = "",
        detail: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        **data: Any,
    ) -> None:
        log_detail = dict(detail or data or {})
        normalized_request_id = str(request_id or log_detail.get("request_id") or get_current_request_id() or "").strip()
        if normalized_request_id:
            log_detail["request_id"] = normalized_request_id
        item = {
            "id": uuid.uuid4().hex,
            "time": china_now_text(),
            "type": type,
            "summary": summary,
            "detail": log_detail,
        }
        if normalized_request_id:
            item["request_id"] = normalized_request_id
        repo = self._system_log_repository()
        if repo is not None:
            try:
                repo.add(item)
            except Exception:
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        else:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")

        detail_status = log_detail.get("status")
        if str(detail_status or item.get("status") or "").strip().lower() in {"error", "failed", "failure", "critical"}:
            try:
                from services.telegram_service import notify_error_log

                notify_error_log(item)
            except Exception:
                # Notification delivery is best-effort and must not break log persistence.
                pass

    def query(
        self,
        type: str = "",
        start_date: str = "",
        end_date: str = "",
        request_id: str = "",
        status: str = "",
        user: str = "",
        page: int = 1,
        page_size: int = 200,
    ) -> dict[str, Any]:
        repo = self._system_log_repository()
        if repo is not None:
            try:
                return repo.query(
                    type=type,
                    start_date=start_date,
                    end_date=end_date,
                    request_id=request_id,
                    status=status,
                    user=user,
                    page=page,
                    page_size=page_size,
                )
            except Exception:
                pass
        items = self._list_file(
            type=type,
            start_date=start_date,
            end_date=end_date,
            request_id=request_id,
            status=status,
            user=user,
        )
        normalized_page = max(1, int(page or 1))
        normalized_page_size = max(1, min(200, int(page_size or 200)))
        total = len(items)
        page_count = max(1, (total + normalized_page_size - 1) // normalized_page_size)
        safe_page = min(normalized_page, page_count)
        start = (safe_page - 1) * normalized_page_size
        return {
            "items": items[start:start + normalized_page_size],
            "total": total,
            "page": safe_page,
            "page_size": normalized_page_size,
            "page_count": page_count,
        }

    def list(
        self,
        type: str = "",
        start_date: str = "",
        end_date: str = "",
        limit: int = 200,
        request_id: str = "",
        status: str = "",
        user: str = "",
    ) -> list[dict[str, Any]]:
        return self.query(
            type=type,
            start_date=start_date,
            end_date=end_date,
            request_id=request_id,
            status=status,
            user=user,
            page=1,
            page_size=limit,
        )["items"]

    def _list_file(
        self,
        type: str = "",
        start_date: str = "",
        end_date: str = "",
        request_id: str = "",
        status: str = "",
        user: str = "",
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items: list[dict[str, Any]] = []
        normalized_status = str(status or "").strip()
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                item = json.loads(line)
            except Exception:
                continue
            t = str(item.get("time") or "")
            day = t[:10]
            if type and item.get("type") != type:
                continue
            item_detail = item.get("detail")
            detail_request_id = item_detail.get("request_id") if isinstance(item_detail, dict) else ""
            if request_id and str(item.get("request_id") or detail_request_id or "") != request_id:
                continue
            detail_status = item_detail.get("status") if isinstance(item_detail, dict) else ""
            if normalized_status and str(item.get("status") or detail_status or "").strip() != normalized_status:
                continue
            if user and not _log_matches_user(item, user):
                continue
            if start_date and day < start_date:
                continue
            if end_date and day > end_date:
                continue
            items.append(item)
        return items


log_service = LogService(DATA_DIR / "logs.jsonl")


class AuditService:
    def _audit_log_repository(self):
        try:
            from services.config import config

            provider = config.get_repository_provider()
            return provider.audit_logs if provider is not None else None
        except Exception:
            return None

    def add(
        self,
        *,
        actor: dict[str, object] | None,
        action: str,
        resource: str = "",
        target_id: str = "",
        detail: dict[str, Any] | None = None,
        status: str = "success",
        request_id: str | None = None,
    ) -> None:
        normalized_detail = dict(detail or {})
        normalized_request_id = str(request_id or normalized_detail.get("request_id") or get_current_request_id() or "").strip()
        if normalized_request_id:
            normalized_detail["request_id"] = normalized_request_id
        item = {
            "id": uuid.uuid4().hex,
            "time": china_now_text(),
            "type": LOG_TYPE_AUDIT,
            "summary": action,
            "actor_id": str((actor or {}).get("id") or ""),
            "actor_name": str((actor or {}).get("name") or ""),
            "actor_role": str((actor or {}).get("role") or ""),
            "action": action,
            "resource": resource,
            "target_id": target_id,
            "status": status,
            "detail": normalized_detail,
        }
        if normalized_request_id:
            item["request_id"] = normalized_request_id
        repo = self._audit_log_repository()
        if repo is not None:
            try:
                repo.add(item)
            except Exception:
                pass
        log_service.add(LOG_TYPE_AUDIT, action, item, request_id=normalized_request_id)

    def query(
        self,
        *,
        action: str = "",
        resource: str = "",
        start_date: str = "",
        end_date: str = "",
        request_id: str = "",
        user: str = "",
        page: int = 1,
        page_size: int = 200,
    ) -> dict[str, Any]:
        repo = self._audit_log_repository()
        if repo is not None:
            try:
                return repo.query(
                    action=action,
                    resource=resource,
                    start_date=start_date,
                    end_date=end_date,
                    request_id=request_id,
                    user=user,
                    page=page,
                    page_size=page_size,
                )
            except Exception:
                pass
        return log_service.query(
            type=LOG_TYPE_AUDIT,
            start_date=start_date,
            end_date=end_date,
            request_id=request_id,
            user=user,
            page=page,
            page_size=page_size,
        )


audit_service = AuditService()
