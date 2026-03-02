import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from janus.config import Settings
from janus.discovery import Target
from janus.scheduler import Scheduler


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_target(cid="abc", name="myapp", interval=60, monitor_only=False, is_compose=False):
    return Target(
        container_id=cid,
        name=name,
        image_ref="nginx:latest",
        interval=interval,
        monitor_only=monitor_only,
        is_compose=is_compose,
    )


def make_settings(**kwargs):
    return Settings(
        label_prefix=kwargs.get("label_prefix", "janus.autoupdate"),
        default_interval=kwargs.get("default_interval", 300),
        stop_timeout=kwargs.get("stop_timeout", 10),
        max_concurrent_updates=kwargs.get("max_concurrent_updates", 1),
        log_level=kwargs.get("log_level", "INFO"),
    )


@pytest.fixture
def scheduler():
    return Scheduler(
        high_client=MagicMock(),
        low_client=MagicMock(),
        settings=make_settings(),
    )


# ── cancel_all_tasks ──────────────────────────────────────────────────────────

def test_cancel_all_tasks_cancels_every_task(scheduler):
    tasks = [MagicMock(), MagicMock(), MagicMock()]
    for i, t in enumerate(tasks):
        scheduler._tasks[f"cid{i}"] = t
        scheduler._targets[f"cid{i}"] = make_target(cid=f"cid{i}")

    scheduler.cancel_all_tasks()

    for t in tasks:
        t.cancel.assert_called_once()
    assert len(scheduler._tasks) == 0
    assert len(scheduler._targets) == 0


def test_cancel_all_tasks_on_empty_scheduler_is_safe(scheduler):
    scheduler.cancel_all_tasks()  # should not raise


# ── _reconcile_once ───────────────────────────────────────────────────────────

class TestReconcileOnce:
    async def _reconcile(self, scheduler, targets):
        with patch("janus.scheduler.discover_targets", return_value=targets):
            with patch.object(scheduler, "_run_target", new_callable=AsyncMock):
                await scheduler._reconcile_once()

    async def test_adds_task_for_new_target(self, scheduler):
        target = make_target()
        await self._reconcile(scheduler, [target])

        assert target.container_id in scheduler._tasks
        assert scheduler._targets[target.container_id] == target

    async def test_does_not_duplicate_task_for_unchanged_target(self, scheduler):
        target = make_target()
        await self._reconcile(scheduler, [target])
        first_task = scheduler._tasks[target.container_id]

        await self._reconcile(scheduler, [target])

        assert scheduler._tasks[target.container_id] is first_task

    async def test_cancels_task_for_removed_target(self, scheduler):
        target = make_target()
        mock_task = MagicMock()
        scheduler._tasks[target.container_id] = mock_task
        scheduler._targets[target.container_id] = target

        await self._reconcile(scheduler, [])  # container gone

        mock_task.cancel.assert_called_once()
        assert target.container_id not in scheduler._tasks
        assert target.container_id not in scheduler._targets

    async def test_restarts_task_when_interval_changes(self, scheduler):
        old = make_target(interval=60)
        new = make_target(interval=120)  # same container_id, different interval

        mock_task = MagicMock()
        scheduler._tasks[old.container_id] = mock_task
        scheduler._targets[old.container_id] = old

        await self._reconcile(scheduler, [new])

        mock_task.cancel.assert_called_once()
        assert scheduler._targets[new.container_id] == new
        # A new asyncio.Task was created (not the old mock)
        assert scheduler._tasks[new.container_id] is not mock_task

    async def test_restarts_task_when_monitor_only_changes(self, scheduler):
        old = make_target(monitor_only=False)
        new = make_target(monitor_only=True)

        mock_task = MagicMock()
        scheduler._tasks[old.container_id] = mock_task
        scheduler._targets[old.container_id] = old

        await self._reconcile(scheduler, [new])

        mock_task.cancel.assert_called_once()

    async def test_does_not_restart_unchanged_task(self, scheduler):
        target = make_target()
        mock_task = MagicMock()
        scheduler._tasks[target.container_id] = mock_task
        scheduler._targets[target.container_id] = target

        await self._reconcile(scheduler, [target])  # same config

        mock_task.cancel.assert_not_called()

    async def test_handles_multiple_containers(self, scheduler):
        t1 = make_target(cid="c1", name="app1")
        t2 = make_target(cid="c2", name="app2")
        t3 = make_target(cid="c3", name="app3")

        await self._reconcile(scheduler, [t1, t2, t3])
        assert len(scheduler._tasks) == 3

        # Remove t2
        await self._reconcile(scheduler, [t1, t3])
        assert len(scheduler._tasks) == 2
        assert "c2" not in scheduler._tasks

    async def test_reconcile_error_does_not_raise(self, scheduler):
        with patch(
            "janus.scheduler.discover_targets", side_effect=Exception("Docker down")
        ):
            # reconcile_once itself propagates; reconcile_forever catches it
            with pytest.raises(Exception, match="Docker down"):
                await scheduler._reconcile_once()
