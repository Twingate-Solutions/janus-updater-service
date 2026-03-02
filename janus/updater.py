from __future__ import annotations

import time
import structlog

from .recreate import recreate_container_identical

log = structlog.get_logger()


def pull_and_compare(high_client, container_id: str, image_ref: str) -> tuple[str | None, str | None, bool]:
    """
    Returns (old_image_id, new_image_id, changed).
    """
    c = high_client.containers.get(container_id)

    old_id = None
    try:
        old_id = c.image.id
    except Exception:
        old_id = None

    # Always pull; this doubles as "check"
    high_client.images.pull(image_ref)

    # Resolve what image ID the tag/digest points at now
    new_id = None
    try:
        new_id = high_client.images.get(image_ref).id
    except Exception:
        # fallback: re-read container image id if tag lookups fail
        try:
            new_id = high_client.containers.get(container_id).image.id
        except Exception:
            new_id = None

    changed = (old_id is not None and new_id is not None and old_id != new_id)
    return old_id, new_id, changed


def check_and_update(
    high_client,
    low_client,
    *,
    container_id: str,
    container_name: str,
    image_ref: str,
    is_compose: bool,
    monitor_only: bool,
    stop_timeout: int,
) -> None:
    t0 = time.time()

    log.bind(service="janus", component="updater").info(
        "check_start",
        event="check_start",
        container_id=container_id,
        container_name=container_name,
        image_ref=image_ref,
        compose=is_compose,
        monitor_only=monitor_only,
    )

    old_id, new_id, changed = pull_and_compare(high_client, container_id, image_ref)

    if not changed:
        log.bind(service="janus", component="updater").info(
            "no_update",
            event="no_update",
            container_id=container_id,
            container_name=container_name,
            image_ref=image_ref,
            current_image_id=old_id,
            new_image_id=new_id,
            duration_ms=int((time.time() - t0) * 1000),
        )
        return

    log.bind(service="janus", component="updater").info(
        "update_available",
        event="update_available",
        container_id=container_id,
        container_name=container_name,
        image_ref=image_ref,
        old_image_id=old_id,
        new_image_id=new_id,
        duration_ms=int((time.time() - t0) * 1000),
    )

    if monitor_only:
        return

    t1 = time.time()
    try:
        recreate_container_identical(
            high_client=high_client,
            low_client=low_client,
            container_id=container_id,
            stop_timeout=stop_timeout,
        )
        log.bind(service="janus", component="updater").info(
            "update_success",
            event="update_success",
            container_id=container_id,
            container_name=container_name,
            image_ref=image_ref,
            old_image_id=old_id,
            new_image_id=new_id,
            duration_ms=int((time.time() - t1) * 1000),
        )
        # Prune dangling images left behind by the update (best-effort)
        try:
            result = high_client.images.prune(filters={"dangling": True})
            reclaimed = (result.get("SpaceReclaimed") or 0)
            if reclaimed:
                log.bind(service="janus", component="updater").info(
                    "image_prune",
                    event="image_prune",
                    space_reclaimed_bytes=reclaimed,
                )
        except Exception:
            pass
    except Exception as e:
        log.bind(service="janus", component="updater").error(
            "update_failure",
            event="update_failure",
            container_id=container_id,
            container_name=container_name,
            image_ref=image_ref,
            old_image_id=old_id,
            new_image_id=new_id,
            error=str(e),
            duration_ms=int((time.time() - t1) * 1000),
        )
        raise