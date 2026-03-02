# Janus

Janus is a label-driven Docker container image updater. It watches running containers, pulls updated images on a configurable schedule, and safely recreates containers in-place when a new image is available — preserving all configuration, labels, mounts, network settings, and resource limits.

## How it works

1. Scans all containers on the local Docker engine every 30 seconds for containers with `janus.autoupdate.enable=true`.
2. For each enabled container, periodically pulls its configured image reference (tag or digest).
3. Compares the image ID before and after the pull.
4. If the image has changed and `monitor-only` is not set:
   - Stops the old container.
   - Renames it to `<name>.janus-old.<timestamp>` (rollback anchor).
   - Creates and starts a new container with the updated image, preserving all original configuration.
   - Removes the old container on success; rolls back (restarts the old container) on failure.
5. After a successful update, dangling images from the previous version are pruned automatically.

## Container labels

| Label | Required | Default | Description |
| ----- | -------- | ------- | ----------- |
| `janus.autoupdate.enable` | Yes | — | Set to `true` to enable updates for this container |
| `janus.autoupdate.interval` | No | `JANUS_DEFAULT_INTERVAL` | Check interval in seconds (minimum: 5) |
| `janus.autoupdate.monitor-only` | No | `false` | Log available updates but do not recreate the container |

## Environment variables

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `JANUS_DEFAULT_INTERVAL` | `300` | Default check interval (seconds) for containers that don't set their own `interval` label |
| `JANUS_LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `JANUS_MAX_CONCURRENT_UPDATES` | `1` | Maximum number of container updates running simultaneously |
| `JANUS_STOP_TIMEOUT` | `10` | Seconds to wait for a container to stop gracefully before force-killing |
| `JANUS_LABEL_PREFIX` | `janus.autoupdate` | Namespace prefix for all labels (change this to avoid conflicts) |

## Run

```yaml
services:
  janus:
    image: ghcr.io/twingate-solutions/janus-updater-service:latest
    container_name: janus
    restart: unless-stopped
    environment:
      - JANUS_DEFAULT_INTERVAL=300
      - JANUS_LOG_LEVEL=INFO
      - JANUS_MAX_CONCURRENT_UPDATES=1
      - JANUS_STOP_TIMEOUT=10
      - JANUS_LABEL_PREFIX=janus.autoupdate
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      # Optional: for private registries
      - ${HOME}/.docker/config.json:/root/.docker/config.json:ro
```

Mount the Docker socket:

- `/var/run/docker.sock:/var/run/docker.sock`

Optional — for private registries:

- `~/.docker/config.json:/root/.docker/config.json:ro`

## Versioning and image tags

Each merge to `main` automatically increments the minor version and publishes three tags:

| Tag | Description |
| --- | ----------- |
| `latest` | Always points to the most recent build |
| `main` | Alias for `latest` |
| `1.XX` | Specific version tag (e.g. `1.00`, `1.01`, `1.02`) |

Only the three most recent versioned images are retained in the registry; older versions are deleted automatically.

## Limitations and cautions

### Docker socket access

Janus requires access to the Docker socket (`/var/run/docker.sock`). This grants it **full control over the Docker daemon**, equivalent to root access on the host. Only run Janus in trusted environments and never expose the socket externally.

### Compose-managed containers

Janus can update containers that were started by Docker Compose (it detects and preserves `com.docker.compose.*` labels). However, **Compose is not aware of the recreation** — the new container is managed directly via the Docker API, not through Compose. This means:

- Running `docker compose up` or `docker compose restart` afterwards will recreate the container again from the Compose file, replacing Janus's version.
- The container will not appear as "changed" in `docker compose ps` until Compose reconciles its state.
- For Compose stacks, `monitor-only` mode is safer: it logs available updates without touching the container, letting you apply updates via `docker compose pull && docker compose up -d` at a time of your choosing.

### Container recreation downtime

When an update is applied, the old container is stopped before the new one starts. There is a brief downtime window. For zero-downtime deployments, use `monitor-only` mode and handle updates externally (e.g. via a rolling update in an orchestrator).

### Rollback behaviour

If the new container fails to start, Janus attempts to rename and restart the old container automatically. However, if the rollback itself fails (e.g. Docker daemon error), the container may be left stopped. Check logs for `rollback_failed` events and intervene manually if needed.

### Self-update

Janus will not update itself — containers named `janus` are explicitly excluded from discovery. To update Janus, pull the new image and recreate its container manually or via Compose.

### Stateful containers

Janus recreates containers with the same volume mounts, but it does not manage data migrations. Updating a database container (e.g. Postgres, MySQL) with Janus is **not recommended** unless the image upgrade is known to be safe to apply by simple restart.

## Logging

All log output is structured JSON written to stdout, suitable for ingestion by log aggregators.

Key log events:

| Event | Description |
| ----- | ----------- |
| `startup` | Service started; logs effective configuration |
| `reconcile` | Periodic scan completed; shows active target count |
| `target_updated` | A container's label config changed; its update task was restarted |
| `check_start` | Starting an image pull-and-compare for a container |
| `no_update` | Pull completed, image unchanged |
| `update_available` | New image detected |
| `update_success` | Container recreated successfully |
| `update_failure` | Recreation failed (rollback attempted) |
| `image_prune` | Dangling images pruned after update, with bytes reclaimed |
| `rollback_attempted` | Old container restored after a failed recreation |
| `rollback_failed` | Rollback also failed — manual intervention required |
| `shutdown_requested` | SIGTERM or SIGINT received |
| `shutdown_complete` | All tasks cancelled, process exiting cleanly |
| `container_discovery_error` | Failed to inspect a container during a discovery scan |
