from __future__ import annotations

import time
import structlog
from typing import Any

try:
    from docker.types import Mount as DockerMount
    _MOUNT_AVAILABLE = True
except ImportError:
    _MOUNT_AVAILABLE = False

log = structlog.get_logger()


def _ts_suffix() -> str:
    return time.strftime("%Y%m%d%H%M%S", time.gmtime())


def _compose_labels_present(labels: dict[str, str]) -> bool:
    return ("com.docker.compose.project" in labels) and ("com.docker.compose.service" in labels)


def _convert_mounts(raw_mounts: list) -> list:
    """Convert Docker API mount dicts to docker-py Mount objects."""
    if not _MOUNT_AVAILABLE:
        return []
    result = []
    for m in raw_mounts:
        if not isinstance(m, dict):
            continue
        try:
            mount_type = (m.get("Type") or "volume").lower()
            target = m.get("Target") or ""
            if not target:
                continue
            source = m.get("Source") or ""
            kwargs: dict[str, Any] = {
                "target": target,
                "source": source,
                "type": mount_type,
                "read_only": m.get("ReadOnly", False),
            }
            if m.get("Consistency"):
                kwargs["consistency"] = m["Consistency"]
            if mount_type == "bind" and m.get("BindOptions"):
                bo = m["BindOptions"]
                if bo.get("Propagation"):
                    kwargs["propagation"] = bo["Propagation"]
            elif mount_type == "volume" and m.get("VolumeOptions"):
                vo = m["VolumeOptions"]
                if vo.get("NoCopy"):
                    kwargs["no_copy"] = True
                if vo.get("Labels"):
                    kwargs["labels"] = vo["Labels"]
                if vo.get("DriverConfig"):
                    kwargs["driver_config"] = vo["DriverConfig"]
            elif mount_type == "tmpfs" and m.get("TmpfsOptions"):
                to = m["TmpfsOptions"]
                if to.get("SizeBytes"):
                    kwargs["tmpfs_size"] = to["SizeBytes"]
                if to.get("Mode"):
                    kwargs["tmpfs_mode"] = to["Mode"]
            result.append(DockerMount(**kwargs))
        except Exception:
            continue
    return result


def recreate_container_identical(*, high_client, low_client, container_id: str, stop_timeout: int) -> None:
    """
    Recreate a container via the Docker Engine API, preserving all configuration:
    labels, environment, mounts, network settings (including static IPs and aliases),
    resource limits, security options, and all HostConfig fields.

    Uses a rename-based rollback strategy:
    1) rename old container to free original name
    2) create new container with original name
    3) start new; on success remove old; on failure rollback.
    """
    c = high_client.containers.get(container_id)
    attrs: dict[str, Any] = c.attrs

    name = (attrs.get("Name") or "").lstrip("/") or c.name
    cfg = attrs.get("Config") or {}
    host_cfg = attrs.get("HostConfig") or {}
    net_settings = attrs.get("NetworkSettings") or {}
    networks = (net_settings.get("Networks") or {}) if isinstance(net_settings.get("Networks"), dict) else {}

    labels: dict[str, str] = (cfg.get("Labels") or {}) if isinstance(cfg.get("Labels"), dict) else {}
    is_compose = _compose_labels_present(labels)

    image_ref: str = cfg.get("Image") or ""
    if not image_ref:
        raise RuntimeError("Container has no image reference to recreate from")

    old_name = name
    backup_name = f"{old_name}.janus-old.{_ts_suffix()}"

    log.bind(service="janus", component="recreate").info(
        "recreate_start",
        container_id=container_id,
        container_name=old_name,
        image_ref=image_ref,
        compose=is_compose,
    )

    # ── HostConfig ──────────────────────────────────────────────────────────
    port_bindings = host_cfg.get("PortBindings") or None
    binds = host_cfg.get("Binds") or None
    restart_policy = host_cfg.get("RestartPolicy") or None
    log_config = host_cfg.get("LogConfig") or None

    # Use Binds (legacy -v style) when present; fall back to Mounts (--mount style)
    raw_mounts = host_cfg.get("Mounts") or []
    mounts = _convert_mounts(raw_mounts) if raw_mounts and not binds else None

    host_config_kwargs: dict[str, Any] = dict(
        # Mounts / binds
        binds=binds,
        mounts=mounts,
        port_bindings=port_bindings,
        publish_all_ports=host_cfg.get("PublishAllPorts"),
        restart_policy=restart_policy,
        log_config=log_config,
        # Networking
        network_mode=host_cfg.get("NetworkMode"),
        extra_hosts=host_cfg.get("ExtraHosts"),
        dns=host_cfg.get("Dns"),
        dns_search=host_cfg.get("DnsSearch"),
        dns_opt=host_cfg.get("DnsOptions"),
        # Capabilities / security
        privileged=host_cfg.get("Privileged"),
        cap_add=host_cfg.get("CapAdd"),
        cap_drop=host_cfg.get("CapDrop"),
        security_opt=host_cfg.get("SecurityOpt"),
        # Process / namespace isolation
        ipc_mode=host_cfg.get("IpcMode"),
        pid_mode=host_cfg.get("PidMode"),
        userns_mode=host_cfg.get("UsernsMode"),
        uts_mode=host_cfg.get("UTSMode"),
        isolation=host_cfg.get("Isolation"),
        # Runtime / init
        runtime=host_cfg.get("Runtime"),
        init=host_cfg.get("Init"),
        auto_remove=host_cfg.get("AutoRemove"),
        # Devices
        devices=host_cfg.get("Devices"),
        device_cgroup_rules=host_cfg.get("DeviceCgroupRules"),
        # CPU resource limits
        cpu_shares=host_cfg.get("CpuShares"),
        cpu_period=host_cfg.get("CpuPeriod"),
        cpu_quota=host_cfg.get("CpuQuota"),
        cpuset_cpus=host_cfg.get("CpusetCpus"),
        cpuset_mems=host_cfg.get("CpusetMems"),
        nano_cpus=host_cfg.get("NanoCpus"),
        # Memory resource limits
        mem_limit=host_cfg.get("Memory"),
        memswap_limit=host_cfg.get("MemorySwap"),
        mem_reservation=host_cfg.get("MemoryReservation"),
        mem_swappiness=host_cfg.get("MemorySwappiness"),
        kernel_memory=host_cfg.get("KernelMemory"),
        oom_kill_disable=host_cfg.get("OomKillDisable"),
        oom_score_adj=host_cfg.get("OomScoreAdj"),
        pids_limit=host_cfg.get("PidsLimit"),
        # Block IO resource limits
        blkio_weight=host_cfg.get("BlkioWeight"),
        blkio_weight_device=host_cfg.get("BlkioWeightDevice"),
        device_read_bps=host_cfg.get("BlkioDeviceReadBps"),
        device_write_bps=host_cfg.get("BlkioDeviceWriteBps"),
        device_read_iops=host_cfg.get("BlkioDeviceReadIOps"),
        device_write_iops=host_cfg.get("BlkioDeviceWriteIOps"),
        # Groups / volumes / storage
        group_add=host_cfg.get("GroupAdd"),
        volumes_from=host_cfg.get("VolumesFrom"),
        links=host_cfg.get("Links"),
        volume_driver=host_cfg.get("VolumeDriver"),
        storage_opt=host_cfg.get("StorageOpt"),
        cgroup_parent=host_cfg.get("CgroupParent"),
        # Misc
        sysctls=host_cfg.get("Sysctls"),
        ulimits=host_cfg.get("Ulimits"),
        shm_size=host_cfg.get("ShmSize"),
        tmpfs=host_cfg.get("Tmpfs"),
        read_only=host_cfg.get("ReadonlyRootfs"),
    )
    # Remove None values — docker-py create_host_config rejects None for many params
    host_config_kwargs = {k: v for k, v in host_config_kwargs.items() if v is not None}

    host_config_obj = low_client.create_host_config(**host_config_kwargs)

    # Patch in fields not exposed by the create_host_config helper
    for api_key in ("ReadonlyPaths", "MaskedPaths", "CgroupnsMode"):
        val = host_cfg.get(api_key)
        if val is not None:
            host_config_obj[api_key] = val

    # ── Container Config ─────────────────────────────────────────────────────
    exposed_ports = cfg.get("ExposedPorts") or {}
    ports = list(exposed_ports.keys()) if isinstance(exposed_ports, dict) else None

    create_kwargs: dict[str, Any] = dict(
        image=image_ref,
        name=old_name,
        environment=cfg.get("Env"),
        entrypoint=cfg.get("Entrypoint"),
        command=cfg.get("Cmd"),
        working_dir=cfg.get("WorkingDir"),
        user=cfg.get("User"),
        hostname=cfg.get("Hostname"),
        domainname=cfg.get("Domainname"),
        labels=labels,
        ports=ports,
        volumes=cfg.get("Volumes") or None,
        host_config=host_config_obj,
    )

    # Only include optional bool/int fields if explicitly set to avoid overriding defaults
    for cfg_key, create_key in (
        ("Tty", "tty"),
        ("OpenStdin", "stdin_open"),
        ("StdinOnce", "stdin_once"),
    ):
        val = cfg.get(cfg_key)
        if val is not None:
            create_kwargs[create_key] = val

    if cfg.get("Healthcheck"):
        create_kwargs["healthcheck"] = cfg["Healthcheck"]
    if cfg.get("StopSignal"):
        create_kwargs["stop_signal"] = cfg["StopSignal"]
    if cfg.get("StopTimeout") is not None:
        create_kwargs["stop_timeout"] = cfg["StopTimeout"]

    # ── Network attachments: preserve aliases and IPAM-assigned static IPs ──
    # IPAMConfig.IPv4Address / IPv6Address are only set when static IPs were
    # requested (--ip / Compose ipv4_address). Dynamic IPs are not preserved
    # as they will be legitimately re-assigned by Docker.
    net_attach = []
    for net_name, net_info in networks.items():
        if not isinstance(net_info, dict):
            continue
        aliases = net_info.get("Aliases") or []
        ipam = net_info.get("IPAMConfig") or {}
        ipv4 = ipam.get("IPv4Address") or None
        ipv6 = ipam.get("IPv6Address") or None
        net_attach.append((net_name, aliases, ipv4, ipv6))

    # ── Stop and rename old container to free the name ───────────────────────
    try:
        c.stop(timeout=stop_timeout)
    except Exception:
        pass

    try:
        c.rename(backup_name)
    except Exception as e:
        raise RuntimeError(f"Failed to rename existing container for safe recreate: {e}")

    new_container_id = None
    try:
        created = low_client.create_container(**create_kwargs)
        new_container_id = created.get("Id")
        if not new_container_id:
            raise RuntimeError("Docker API did not return new container Id")

        # Connect to all networks, preserving aliases and static IPs where set
        for net_name, aliases, ipv4, ipv6 in net_attach:
            try:
                net = high_client.networks.get(net_name)
                connect_kwargs: dict[str, Any] = {}
                if aliases:
                    connect_kwargs["aliases"] = aliases
                if ipv4:
                    connect_kwargs["ipv4_address"] = ipv4
                if ipv6:
                    connect_kwargs["ipv6_address"] = ipv6
                net.connect(new_container_id, **connect_kwargs)
            except Exception:
                # Special network modes (host, none) and already-connected networks
                # will raise here; ignore best-effort.
                pass

        low_client.start(new_container_id)

        # Success: remove old container
        try:
            old = high_client.containers.get(c.id)
            old.remove(v=False, force=True)
        except Exception:
            pass

        log.bind(service="janus", component="recreate").info(
            "recreate_success",
            old_container_id=container_id,
            old_container_name=backup_name,
            new_container_id=new_container_id,
            new_container_name=old_name,
            compose=is_compose,
        )
        return

    except Exception as e:
        log.bind(service="janus", component="recreate").error(
            "recreate_failed",
            container_id=container_id,
            container_name=old_name,
            new_container_id=new_container_id,
            error=str(e),
        )
        # Rollback: remove new (if exists), restore old name, restart old
        try:
            if new_container_id:
                try:
                    low_client.remove_container(new_container_id, force=True)
                except Exception:
                    pass

            old = high_client.containers.get(c.id)
            try:
                old.rename(old_name)
            except Exception:
                pass
            try:
                old.start()
            except Exception:
                pass

            log.bind(service="janus", component="recreate").info(
                "rollback_attempted",
                old_container_id=container_id,
                restored_name=old_name,
            )
        except Exception as rb_e:
            log.bind(service="janus", component="recreate").error(
                "rollback_failed",
                container_id=container_id,
                error=str(rb_e),
            )
        raise
