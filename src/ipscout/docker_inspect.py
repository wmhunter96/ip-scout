"""Docker container -> IP address inspection, via the `docker` CLI.

Deliberately shells out to `docker ps` + `docker inspect` against the
mounted socket -- the exact two commands this project exists to automate,
run by hand like this:

    docker ps --format '{{.Names}}' | while read name; do
      ip=$(docker inspect --format \
        '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$name")
      printf "%-25s %s\n" "$name" "$ip"
    done

Same two commands, but one `docker inspect` call for every running
container instead of one per name (`docker inspect` happily takes many IDs
at once), and JSON output instead of a Go template string so a container on
more than one network doesn't get its IPs concatenated with no separator.

This previously went through the `docker` Python SDK instead -- switched
to the CLI because the SDK's own Engine API version negotiation was a
source of exactly the kind of environment-specific breakage (works in dev,
silently returns nothing on a real Unraid box) this project is supposed to
replace with something that just works, the same way the hand-run commands
above always have.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DOCKER_TIMEOUT_S = 15


@dataclass
class ContainerInfo:
    name: str
    short_id: str
    networks: list[str] = field(default_factory=list)
    ips: list[str] = field(default_factory=list)


def _docker(*args: str) -> str:
    proc = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=_DOCKER_TIMEOUT_S,
        check=True,
    )
    return proc.stdout


def _running_container_ids() -> list[str]:
    """Equivalent to `docker ps -q` -- by ID rather than name, so a rename
    racing with this call can't cause an inspect miss."""
    return [line for line in _docker("ps", "-q").splitlines() if line]


def _extract_ips(networks: dict) -> tuple[list[str], list[str]]:
    """Pull network names + IPv4 addresses out of a container's Networks dict.

    A container on host networking (or one still starting up) has no entry
    with an IPAddress; that network still shows up in `names`, just with no
    matching IP -- callers should treat an empty `ips` list as "no IP
    Docker assigned it", not as "inspection failed".
    """
    names: list[str] = []
    ips: list[str] = []
    for net_name, net_data in networks.items():
        names.append(net_name)
        ip = (net_data or {}).get("IPAddress")
        if ip:
            ips.append(ip)
    return names, ips


def get_container_ips() -> list[ContainerInfo]:
    """List running containers and the IPs Docker has assigned them."""
    ids = _running_container_ids()
    if not ids:
        return []

    # One `docker inspect` call covering every running container, not one
    # per container -- `{{json .}}` prints one JSON object per line.
    out = _docker("inspect", "--format", "{{json .}}", *ids)

    result = []
    for line in out.splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        networks, ips = _extract_ips(data.get("NetworkSettings", {}).get("Networks") or {})
        result.append(
            ContainerInfo(
                name=data["Name"].lstrip("/"),
                short_id=data["Id"][:12],
                networks=networks,
                ips=ips,
            )
        )
    return result
