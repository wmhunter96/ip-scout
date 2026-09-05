"""Shared pytest fixtures.

No fixture here talks to a real Docker daemon or the network -- see
test_docker_inspect.py and test_scanner.py for how each is mocked.
"""

from __future__ import annotations

from ipscout.config import Config


def make_config(**overrides) -> Config:
    """A small subnet by default, so range-based tests stay fast and readable."""
    defaults = dict(subnet_prefix="192.168.4", range_start=1, range_end=5, scan_interval=60)
    defaults.update(overrides)
    return Config(**defaults)
