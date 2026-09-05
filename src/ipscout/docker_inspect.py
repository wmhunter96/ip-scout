"""Docker container -> IP address inspection, via the Docker SDK.

Deliberately uses the `docker` Python SDK against the daemon socket rather
than shelling out to `docker inspect` -- no subprocess, no parsing CLI
output, and it's trivial to mock in tests (see tests/test_docker_inspect.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import docker
except ImportError:  # pragma: no cover - exercised only when the optional dep is missing
    docker = None


@dataclass
class ContainerInfo:
    name: str
    short_id: str
    networks: list[str] = field(default_factory=list)
    ips: list[str] = field(default_factory=list)


def get_docker_client():
    """Create a Docker SDK client from the environment (DOCKER_HOST, socket, etc.)."""
    if docker is None:
        raise RuntimeError(
            "The 'docker' package is not installed; run `pip install docker`."
        )
    return docker.from_env()


def _extract_ips(container) -> tuple[list[str], list[str]]:
    """Pull network names + IPv4 addresses out of a container's NetworkSettings.

    A container on host networking (or one still starting up) has no entry
    with an IPAddress; that network still shows up in `networks`, just with
    no matching IP -- callers should treat an empty `ips` list as "no IP
    Docker assigned it", not as "inspection failed".
    """
    networks = container.attrs.get("NetworkSettings", {}).get("Networks", {}) or {}
    names: list[str] = []
    ips: list[str] = []
    for net_name, net_data in networks.items():
        names.append(net_name)
        ip = (net_data or {}).get("IPAddress")
        if ip:
            ips.append(ip)
    return names, ips


def get_container_ips(client=None) -> list[ContainerInfo]:
    """List running containers and the IPs Docker has assigned them.

    Pass an existing SDK client (e.g. a mock in tests, or a shared client in
    serve mode) via `client`; otherwise one is created and closed here.
    """
    owns_client = client is None
    if client is None:
        client = get_docker_client()
    try:
        result = []
        for container in client.containers.list():
            networks, ips = _extract_ips(container)
            result.append(
                ContainerInfo(
                    name=container.name,
                    short_id=container.short_id,
                    networks=networks,
                    ips=ips,
                )
            )
        return result
    finally:
        if owns_client:
            try:
                client.close()
            except Exception:
                logger.debug("Error closing Docker client", exc_info=True)
