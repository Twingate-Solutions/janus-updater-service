from __future__ import annotations

import asyncio
import time
import structlog

from .discovery import Target, discover_targets
from .updater import check_and_update

log = structlog.get_logger()


class Scheduler:
    def __init__(self, *, high_client, low_client, settings):
        self.high = high_client
        self.low = low_client
        self.settings = settings
        self._tasks: dict[str, asyncio.Task] = {}
        self._targets: dict[str, Target] = {}  # last-known config per container
        self._sem = asyncio.Semaphore(settings.max_concurrent_updates)

    async def _run_target(self, target: Target) -> None:
        while True:
            try:
                async with self._sem:
                    await asyncio.to_thread(
                        check_and_update,
                        self.high,
                        self.low,
                        container_id=target.container_id,
                        container_name=target.name,
                        image_ref=target.image_ref,
                        is_compose=target.is_compose,
                        monitor_only=target.monitor_only,
                        stop_timeout=self.settings.stop_timeout,
                    )
            except Exception:
                # Errors are logged inside check_and_update; continue the loop
                pass
            await asyncio.sleep(target.interval)

    def cancel_all_tasks(self) -> None:
        """Cancel every active per-container task (used on graceful shutdown)."""
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        self._targets.clear()

    async def _reconcile_once(self) -> None:
        """
        Single reconcile pass:
        - Cancel tasks for containers that are gone or no longer enabled.
        - Start tasks for newly labeled containers.
        - Restart tasks whose label config has changed (e.g. interval update).
        """
        t0 = time.time()
        targets = discover_targets(
            self.high,
            label_prefix=self.settings.label_prefix,
            default_interval=self.settings.default_interval,
        )
        want = {t.container_id: t for t in targets}

        # Cancel tasks for removed containers
        for cid in list(self._tasks.keys()):
            if cid not in want:
                self._tasks.pop(cid).cancel()
                self._targets.pop(cid, None)

        # Add tasks for new containers; restart if config changed
        for cid, t in want.items():
            if cid in self._tasks:
                if t != self._targets[cid]:
                    # Labels changed (e.g. interval, monitor-only) — restart
                    self._tasks[cid].cancel()
                    self._tasks[cid] = asyncio.create_task(self._run_target(t))
                    self._targets[cid] = t
                    log.bind(service="janus", component="scheduler").info(
                        "target_updated",
                        event="target_updated",
                        container_id=cid,
                        container_name=t.name,
                    )
            else:
                self._tasks[cid] = asyncio.create_task(self._run_target(t))
                self._targets[cid] = t

        log.bind(service="janus", component="scheduler").info(
            "reconcile",
            event="reconcile",
            targets=len(want),
            active_tasks=len(self._tasks),
            duration_ms=int((time.time() - t0) * 1000),
        )

    async def reconcile_forever(self) -> None:
        """Reconcile every 30 s, logging errors without stopping the loop."""
        while True:
            try:
                await self._reconcile_once()
            except Exception as e:
                log.bind(service="janus", component="scheduler").error(
                    "reconcile_failed",
                    event="reconcile_failed",
                    error=str(e),
                )
            await asyncio.sleep(30)
