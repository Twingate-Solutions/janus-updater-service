from __future__ import annotations

import docker
from docker import DockerClient
from docker import APIClient


def get_clients() -> tuple[DockerClient, APIClient]:
    """
    High-level client for convenience + low-level API client for exact recreation calls.
    Both created via from_env() to avoid internal transport URL format issues.
    """
    high = docker.from_env()
    low = high.api
    return high, low