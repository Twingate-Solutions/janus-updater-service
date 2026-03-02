from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()


@dataclass(frozen=True)
class Target:
    container_id: str
    name: str
    image_ref: str
    interval: int
    monitor_only: bool
    is_compose: bool


def _parse_bool(v: Optional[str]) -> bool:
    if v is None:
        return False
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def discover_targets(high_client, label_prefix: str, default_interval: int) -> list[Target]:
    enable_key = f"{label_prefix}.enable"
    interval_key = f"{label_prefix}.interval"
    monitor_key = f"{label_prefix}.monitor-only"

    targets: list[Target] = []

    for c in high_client.containers.list(all=True):
        try:
            attrs = c.attrs  # may trigger API call
            name = (attrs.get("Name") or "").lstrip("/") or c.name
            if name == "janus":
                continue

            labels = (attrs.get("Config", {}) or {}).get("Labels", {}) or {}
            if not _parse_bool(labels.get(enable_key)):
                continue

            interval = default_interval
            raw_int = labels.get(interval_key)
            if raw_int:
                try:
                    interval = max(5, int(raw_int))
                except ValueError:
                    interval = default_interval

            monitor_only = _parse_bool(labels.get(monitor_key))

            image_ref = (attrs.get("Config", {}) or {}).get("Image") or ""
            if not image_ref:
                continue

            is_compose = (
                "com.docker.compose.project" in labels
                and "com.docker.compose.service" in labels
            )

            targets.append(
                Target(
                    container_id=c.id,
                    name=name,
                    image_ref=image_ref,
                    interval=interval,
                    monitor_only=monitor_only,
                    is_compose=is_compose,
                )
            )
        except Exception as exc:
            log.bind(service="janus", component="discovery").warning(
                "container_discovery_error",
                container_id=getattr(c, "id", "unknown"),
                container_name=getattr(c, "name", "unknown"),
                error=str(exc),
            )
            continue

    return targets