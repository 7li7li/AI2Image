from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Condition, Lock
import time
from typing import Any, Callable

from services.observability import normalize_request_id, request_id_context


TaskRunner = Callable[[], dict[str, Any] | None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


class BackgroundTaskService:
    def __init__(self, *, max_workers: int = 4, retention_seconds: int = 86400) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="yanai-task")
        self._retention = timedelta(seconds=max(60, retention_seconds))
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._tasks: dict[str, dict[str, Any]] = {}

    def submit(
        self,
        *,
        task_id: str,
        owner_key: str,
        kind: str,
        runner: TaskRunner,
    ) -> dict[str, Any]:
        normalized_task_id = normalize_request_id(task_id)
        normalized_owner_key = str(owner_key or "").strip()
        normalized_kind = str(kind or "task").strip() or "task"
        self._cleanup_locked()
        with self._lock:
            existing = self._tasks.get(normalized_task_id)
            if existing is not None:
                self._require_owner(existing, normalized_owner_key)
                return self._serialize(existing)

            task = {
                "id": normalized_task_id,
                "task_id": normalized_task_id,
                "request_id": normalized_task_id,
                "owner_key": normalized_owner_key,
                "kind": normalized_kind,
                "status": "queued",
                "created_at": _iso_now(),
                "updated_at": _iso_now(),
                "result": None,
                "error": None,
                "future": None,
                "version": 0,
            }
            self._tasks[normalized_task_id] = task
            self._condition.notify_all()

        future = self._executor.submit(self._run, normalized_task_id, runner)
        with self._lock:
            current = self._tasks.get(normalized_task_id)
            if current is not None:
                current["future"] = future
                return self._serialize(current)
        return {
            "id": normalized_task_id,
            "task_id": normalized_task_id,
            "request_id": normalized_task_id,
            "kind": normalized_kind,
            "status": "queued",
        }

    def get(self, task_id: str, owner_key: str) -> dict[str, Any] | None:
        normalized_task_id = normalize_request_id(task_id)
        normalized_owner_key = str(owner_key or "").strip()
        self._cleanup_locked()
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if task is None:
                return None
            self._require_owner(task, normalized_owner_key)
            return self._serialize(task)

    def wait_for_update(
        self,
        task_id: str,
        owner_key: str,
        *,
        version: int = 0,
        timeout_seconds: float = 15,
    ) -> dict[str, Any] | None:
        normalized_task_id = normalize_request_id(task_id)
        normalized_owner_key = str(owner_key or "").strip()
        deadline = time.monotonic() + max(0.1, float(timeout_seconds or 15))
        with self._condition:
            task = self._tasks.get(normalized_task_id)
            if task is None:
                return None
            self._require_owner(task, normalized_owner_key)
            while int(task.get("version") or 0) <= int(version or 0) and task.get("status") in {"queued", "running"}:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
                task = self._tasks.get(normalized_task_id)
                if task is None:
                    return None
                self._require_owner(task, normalized_owner_key)
            return self._serialize(task)

    def update_result(self, task_id: str, result: dict[str, Any]) -> None:
        normalized_task_id = normalize_request_id(task_id)
        with self._condition:
            task = self._tasks.get(normalized_task_id)
            if task is None or task.get("status") not in {"queued", "running"}:
                return
            task["result"] = dict(result)
            task["updated_at"] = _iso_now()
            task["version"] = int(task.get("version") or 0) + 1
            self._condition.notify_all()

    def _run(self, task_id: str, runner: TaskRunner) -> None:
        with self._condition:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task["status"] = "running"
            task["updated_at"] = _iso_now()
            task["version"] = int(task.get("version") or 0) + 1
            self._condition.notify_all()

        try:
            with request_id_context(task_id):
                result = runner() or {}
            with self._condition:
                task = self._tasks.get(task_id)
                if task is None:
                    return
                task["status"] = "success"
                task["result"] = result
                task["error"] = None
                task["updated_at"] = _iso_now()
                task["version"] = int(task.get("version") or 0) + 1
                self._condition.notify_all()
        except Exception as exc:
            detail = getattr(exc, "detail", None)
            if isinstance(detail, dict):
                message = str(detail.get("error") or detail.get("message") or "").strip()
            elif isinstance(detail, str):
                message = detail.strip()
            else:
                message = ""
            message = message or str(exc).strip() or exc.__class__.__name__
            with self._condition:
                task = self._tasks.get(task_id)
                if task is None:
                    return
                task["status"] = "error"
                task["error"] = message
                task["updated_at"] = _iso_now()
                task["version"] = int(task.get("version") or 0) + 1
                self._condition.notify_all()

    def _cleanup_locked(self) -> None:
        cutoff = _utc_now() - self._retention
        with self._lock:
            expired_ids: list[str] = []
            for task_id, task in self._tasks.items():
                if task.get("status") in {"queued", "running"}:
                    continue
                updated_at = self._parse_time(task.get("updated_at"))
                if updated_at < cutoff:
                    expired_ids.append(task_id)
            for task_id in expired_ids:
                self._tasks.pop(task_id, None)

    @staticmethod
    def _parse_time(value: object) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value or ""))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return datetime.fromtimestamp(0, timezone.utc)

    @staticmethod
    def _require_owner(task: dict[str, Any], owner_key: str) -> None:
        if str(task.get("owner_key") or "") != owner_key:
            raise PermissionError("task does not belong to current user")

    @staticmethod
    def _serialize(task: dict[str, Any]) -> dict[str, Any]:
        serialized = {
            key: value
            for key, value in task.items()
            if key not in {"future", "owner_key"} and value is not None
        }
        future = task.get("future")
        if isinstance(future, Future) and future.cancelled():
            serialized["status"] = "error"
            serialized["error"] = "task was cancelled"
        return serialized


background_task_service = BackgroundTaskService()
