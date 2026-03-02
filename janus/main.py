from __future__ import annotations

import asyncio
import signal
import structlog

from .config import Settings
from .logging_setup import configure_logging
from .docker_client import get_clients
from .scheduler import Scheduler

log = structlog.get_logger()


async def _run(sched: Scheduler) -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _on_signal() -> None:
        log.bind(service="janus", component="main").info(
            "shutdown_requested"
        )
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal)

    reconcile_task = asyncio.create_task(sched.reconcile_forever())

    await stop.wait()

    reconcile_task.cancel()
    try:
        await reconcile_task
    except asyncio.CancelledError:
        pass

    sched.cancel_all_tasks()

    log.bind(service="janus", component="main").info(
        "shutdown_complete"
    )


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    high, low = get_clients()

    log.bind(service="janus", component="main").info(
        "startup",
        default_interval=settings.default_interval,
        stop_timeout=settings.stop_timeout,
        max_concurrent_updates=settings.max_concurrent_updates,
        label_prefix=settings.label_prefix,
    )

    sched = Scheduler(high_client=high, low_client=low, settings=settings)
    asyncio.run(_run(sched))
