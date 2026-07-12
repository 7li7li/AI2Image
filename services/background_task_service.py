from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Condition, Lock
import time
from typing import Any, Callable

from services.config import config
from services.observability import normalize_request_id, request_id_context


TaskRunner = Callable[[], dict[str, Any] | None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


class BackgroundTaskService:
    def __init__(
        self,
        *,
        max_workers: int = 4,
        max_pending_tasks: int = 100,
        max_tasks_per_owner: int = 2,
        max_pending_tasks_per_owner: int = 20,
        retention_seconds: int = 86400,
    ) -> None:
        self._max_workers = max(1, int(max_workers or 4))
        self._max_pending_tasks = max(1, int(max_pending_tasks or 100))
        self._max_tasks_per_owner = max(0, int(max_tasks_per_owner or 0))
        self._max_pending_tasks_per_owner = max(1, int(max_pending_tasks_per_owner or 20))
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="yanai-task")
        self._retention = timedelta(seconds=max(60, retention_seconds))
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._tasks: dict[str, dict[str, Any]] = {}

    def configure(
        self,
        *,
        max_workers: int,
        max_pending_tasks: int,
        max_tasks_per_owner: int,
        max_pending_tasks_per_owner: int | None = None,
    ) -> dict[str, Any]:
        normalized_max_workers = max(1, int(max_workers or 1))
        normalized_max_pending_tasks = max(1, int(max_pending_tasks or 1))
        normalized_max_tasks_per_owner = max(0, int(max_tasks_per_owner or 0))
        normalized_max_pending_tasks_per_owner = max(
            1,
            int(max_pending_tasks_per_owner or self._max_pending_tasks_per_owner),
        )
        old_executor: ThreadPoolExecutor | None = None

        with self._condition:
            if normalized_max_workers != self._max_workers:
                old_executor = self._executor
                self._executor = ThreadPoolExecutor(
                    max_workers=normalized_max_workers,
                    thread_name_prefix="yanai-task",
                )
            self._max_workers = normalized_max_workers
            self._max_pending_tasks = normalized_max_pending_tasks
            self._max_tasks_per_owner = normalized_max_tasks_per_owner
            self._max_pending_tasks_per_owner = normalized_max_pending_tasks_per_owner
            self._dispatch_locked()
            self._condition.notify_all()

        if old_executor is not None:
            old_executor.shutdown(wait=False, cancel_futures=False)
        return self.stats()

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def submit(
        self,
        *,
        task_id: str,
        owner_key: str,
        kind: str,
        runner: TaskRunner,
        owner_concurrency: int | None = None,
        owner_concurrency_resolver: Callable[[], int] | None = None,
    ) -> dict[str, Any]:
        normalized_task_id = normalize_request_id(task_id)
        normalized_owner_key = str(owner_key or "").strip()
        normalized_kind = str(kind or "task").strip() or "task"
        normalized_owner_concurrency = max(1, int(owner_concurrency or self._max_tasks_per_owner or 1))
        self._cleanup_locked()
        with self._lock:
            existing = self._tasks.get(normalized_task_id)
            if existing is not None:
                self._require_owner(existing, normalized_owner_key)
                return self._serialize(existing)
            self._require_capacity(normalized_owner_key)

            for active_task in self._tasks.values():
                if (
                    str(active_task.get("owner_key") or "") == normalized_owner_key
                    and active_task.get("status") in {"queued", "running"}
                ):
                    active_task["owner_concurrency"] = normalized_owner_concurrency
                    active_task["owner_concurrency_resolver"] = owner_concurrency_resolver

            task = {
                "id": normalized_task_id,
                "task_id": normalized_task_id,
                "request_id": normalized_task_id,
                "owner_key": normalized_owner_key,
                "kind": normalized_kind,
                "owner_concurrency": normalized_owner_concurrency,
                "owner_concurrency_resolver": owner_concurrency_resolver,
                "status": "queued",
                "created_at": _iso_now(),
                "updated_at": _iso_now(),
                "result": None,
                "error": None,
                "future": None,
                "version": 0,
            }
            self._tasks[normalized_task_id] = task
            task["runner"] = runner
            self._dispatch_locked()
            self._condition.notify_all()
            return self._serialize(task)

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

    def stats(self, owner_key: str | None = None, *, owner_concurrency: int | None = None) -> dict[str, Any]:
        normalized_owner_key = str(owner_key or "").strip()
        self._cleanup_locked()
        with self._lock:
            items = [
                task
                for task in self._tasks.values()
                if not normalized_owner_key or str(task.get("owner_key") or "") == normalized_owner_key
            ]
            queued = sum(1 for task in items if task.get("status") == "queued")
            running = sum(1 for task in items if task.get("status") == "running")
            success = sum(1 for task in items if task.get("status") == "success")
            error = sum(1 for task in items if task.get("status") == "error")
            return {
                "max_workers": self._max_workers,
                "max_pending_tasks": self._max_pending_tasks,
                "max_tasks_per_owner": self._max_tasks_per_owner,
                "max_pending_tasks_per_owner": self._max_pending_tasks_per_owner,
                "concurrency": max(1, int(owner_concurrency or self._max_tasks_per_owner or 1)),
                "queued": queued,
                "running": running,
                "active": queued + running,
                "success": success,
                "error": error,
                "total": len(items),
            }

    def _run(self, task_id: str, runner: TaskRunner) -> None:
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
                self._dispatch_locked()
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
                self._dispatch_locked()
                self._condition.notify_all()

    def _dispatch_locked(self) -> None:
        running_tasks = [task for task in self._tasks.values() if task.get("status") == "running"]
        running_by_owner: dict[str, int] = {}
        for task in running_tasks:
            owner_key = str(task.get("owner_key") or "")
            running_by_owner[owner_key] = running_by_owner.get(owner_key, 0) + 1

        available_workers = max(0, self._max_workers - len(running_tasks))
        while available_workers > 0:
            selected: dict[str, Any] | None = None
            for task in self._tasks.values():
                if task.get("status") != "queued":
                    continue
                owner_key = str(task.get("owner_key") or "")
                resolver = task.get("owner_concurrency_resolver")
                try:
                    resolved_limit = resolver() if callable(resolver) else task.get("owner_concurrency")
                except Exception:
                    resolved_limit = task.get("owner_concurrency")
                owner_limit = max(1, int(resolved_limit or self._max_tasks_per_owner or 1))
                if running_by_owner.get(owner_key, 0) < owner_limit:
                    selected = task
                    break
            if selected is None:
                break

            task_id = str(selected.get("id") or "")
            owner_key = str(selected.get("owner_key") or "")
            runner = selected.get("runner")
            selected["status"] = "running"
            selected["updated_at"] = _iso_now()
            selected["version"] = int(selected.get("version") or 0) + 1
            try:
                selected["future"] = self._executor.submit(self._run, task_id, runner)
            except Exception as exc:
                selected["status"] = "error"
                selected["error"] = str(exc).strip() or exc.__class__.__name__
                selected["updated_at"] = _iso_now()
                selected["version"] = int(selected.get("version") or 0) + 1
                continue
            running_by_owner[owner_key] = running_by_owner.get(owner_key, 0) + 1
            available_workers -= 1

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

    def _require_capacity(self, owner_key: str) -> None:
        active_tasks = [
            task
            for task in self._tasks.values()
            if task.get("status") in {"queued", "running"}
        ]
        if len(active_tasks) >= self._max_pending_tasks:
            raise ValueError("后台任务队列繁忙，请稍后再试")
        if self._max_pending_tasks_per_owner > 0:
            owner_active = sum(1 for task in active_tasks if str(task.get("owner_key") or "") == owner_key)
            if owner_active >= self._max_pending_tasks_per_owner:
                raise ValueError("当前账号已有任务在排队或处理中，请稍后再试")

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
            if key not in {"future", "owner_key", "runner", "owner_concurrency", "owner_concurrency_resolver"}
            and value is not None
        }
        future = task.get("future")
        if isinstance(future, Future) and future.cancelled():
            serialized["status"] = "error"
            serialized["error"] = "task was cancelled"
        return serialized


background_task_service = BackgroundTaskService(
    max_workers=config.background_task_max_workers,
    max_pending_tasks=config.background_task_queue_limit,
    max_tasks_per_owner=config.background_task_user_limit,
    max_pending_tasks_per_owner=config.background_task_user_queue_limit,
)
