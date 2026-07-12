from __future__ import annotations

from threading import Event
import unittest

from services.background_task_service import BackgroundTaskService


class BackgroundTaskServiceTest(unittest.TestCase):
    def test_capacity_limits_and_stats(self) -> None:
        release_first = Event()
        service = BackgroundTaskService(
            max_workers=1,
            max_pending_tasks=2,
            max_tasks_per_owner=1,
            max_pending_tasks_per_owner=1,
            retention_seconds=60,
        )
        try:
            first = service.submit(
                task_id="task-a",
                owner_key="user:a",
                kind="test",
                runner=lambda: (release_first.wait(5) and {"ok": True}) or {"ok": False},
            )
            self.assertEqual(first["status"], "running")

            with self.assertRaises(ValueError):
                service.submit(
                    task_id="task-a-2",
                    owner_key="user:a",
                    kind="test",
                    runner=lambda: {"ok": True},
                )

            second = service.submit(
                task_id="task-b",
                owner_key="user:b",
                kind="test",
                runner=lambda: {"ok": True},
            )
            self.assertEqual(second["status"], "queued")

            with self.assertRaises(ValueError):
                service.submit(
                    task_id="task-c",
                    owner_key="user:c",
                    kind="test",
                    runner=lambda: {"ok": True},
                )

            stats = service.stats()
            self.assertEqual(stats["max_workers"], 1)
            self.assertEqual(stats["max_pending_tasks"], 2)
            self.assertEqual(stats["max_tasks_per_owner"], 1)
            self.assertEqual(stats["active"], 2)

            owner_stats = service.stats("user:a")
            self.assertEqual(owner_stats["active"], 1)
        finally:
            release_first.set()
            service.shutdown(wait=True)

    def test_configure_updates_limits_for_new_submissions(self) -> None:
        release_first = Event()
        release_second = Event()
        service = BackgroundTaskService(
            max_workers=1,
            max_pending_tasks=1,
            max_tasks_per_owner=1,
            max_pending_tasks_per_owner=1,
            retention_seconds=60,
        )
        try:
            service.submit(
                task_id="task-a",
                owner_key="user:a",
                kind="test",
                runner=lambda: (release_first.wait(5) and {"ok": True}) or {"ok": False},
            )
            with self.assertRaises(ValueError):
                service.submit(
                    task_id="task-b",
                    owner_key="user:b",
                    kind="test",
                    runner=lambda: {"ok": True},
                )

            service.configure(max_workers=2, max_pending_tasks=2, max_tasks_per_owner=2)
            service.submit(
                task_id="task-b",
                owner_key="user:b",
                kind="test",
                runner=lambda: (release_second.wait(5) and {"ok": True}) or {"ok": False},
            )

            self.assertEqual(service.stats()["active"], 2)
        finally:
            release_first.set()
            release_second.set()
            service.shutdown(wait=True)

    def test_owner_concurrency_queues_without_blocking_other_owners(self) -> None:
        release = Event()
        service = BackgroundTaskService(
            max_workers=3,
            max_pending_tasks=10,
            max_tasks_per_owner=1,
            max_pending_tasks_per_owner=10,
            retention_seconds=60,
        )
        try:
            first = service.submit(
                task_id="task-a-1",
                owner_key="user:a",
                kind="test",
                owner_concurrency=1,
                runner=lambda: (release.wait(5) and {"ok": True}) or {"ok": False},
            )
            second = service.submit(
                task_id="task-a-2",
                owner_key="user:a",
                kind="test",
                owner_concurrency=1,
                runner=lambda: {"ok": True},
            )
            other = service.submit(
                task_id="task-b-1",
                owner_key="user:b",
                kind="test",
                owner_concurrency=1,
                runner=lambda: (release.wait(5) and {"ok": True}) or {"ok": False},
            )

            self.assertEqual(first["status"], "running")
            self.assertEqual(second["status"], "queued")
            self.assertEqual(other["status"], "running")
            self.assertEqual(service.stats("user:a", owner_concurrency=1)["running"], 1)
            self.assertEqual(service.stats("user:a", owner_concurrency=1)["queued"], 1)
        finally:
            release.set()
            service.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
