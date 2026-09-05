"""Configuration for ip-scout, sourced from environment variables.

CLI flags (see cli.py) override whatever these env vars resolve to; the env
vars are what a container / systemd unit sets, so a bare `docker run -e ...`
or Unraid template is enough with no CLI flags at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SUBNET_PREFIX = "192.168.1"
DEFAULT_RANGE_START = 1
DEFAULT_RANGE_END = 254
DEFAULT_SCAN_INTERVAL = 300
DEFAULT_PORT = 8000
DEFAULT_DOCKER_NETWORK = None


@dataclass
class Config:
    subnet_prefix: str = DEFAULT_SUBNET_PREFIX
    range_start: int = DEFAULT_RANGE_START
    range_end: int = DEFAULT_RANGE_END
    scan_interval: int = DEFAULT_SCAN_INTERVAL
    port: int = DEFAULT_PORT
    # Only containers on this Docker network are considered at all (e.g.
    # "br0" for an Unraid macvlan setup) -- None means every network.
    # Containers on an unrelated network (typically the default bridge,
    # 172.17.0.x) have nothing to do with the LAN subnet being tracked here.
    docker_network: str | None = DEFAULT_DOCKER_NETWORK

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            subnet_prefix=os.environ.get("SUBNET_PREFIX", DEFAULT_SUBNET_PREFIX),
            range_start=int(os.environ.get("RANGE_START", DEFAULT_RANGE_START)),
            range_end=int(os.environ.get("RANGE_END", DEFAULT_RANGE_END)),
            scan_interval=int(os.environ.get("SCAN_INTERVAL", DEFAULT_SCAN_INTERVAL)),
            port=int(os.environ.get("PORT", DEFAULT_PORT)),
            docker_network=os.environ.get("DOCKER_NETWORK") or DEFAULT_DOCKER_NETWORK,
        )

    @property
    def range_label(self) -> str:
        """Human-readable range, e.g. '192.168.4.1-254'."""
        return f"{self.subnet_prefix}.{self.range_start}-{self.range_end}"
