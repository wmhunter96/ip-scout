"""Pure IP-range math: no network calls, no Docker SDK, no subprocess.

Kept isolated from scanner.py / docker_inspect.py so the arithmetic that
decides "what's free" can be unit tested without mocking a single external
call.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable


def _validate_octet(value: int, label: str) -> None:
    if not 0 <= value <= 255:
        raise ValueError(f"{label} must be between 0 and 255, got {value}")


def generate_range(subnet_prefix: str, start: int, end: int) -> list[str]:
    """Return every dotted-quad IP in [start, end] under subnet_prefix ("a.b.c")."""
    _validate_octet(start, "range_start")
    _validate_octet(end, "range_end")
    if start > end:
        raise ValueError(f"range_start ({start}) must be <= range_end ({end})")
    return [f"{subnet_prefix}.{i}" for i in range(start, end + 1)]


def compute_free_ips(all_ips: Iterable[str], used_ips: Iterable[str]) -> list[str]:
    """Return the subset of all_ips not present in used_ips, order preserved."""
    used = set(used_ips)
    return [ip for ip in all_ips if ip not in used]


def next_free_ip(free_ips: list[str]) -> str | None:
    """The first free IP in the list, or None if nothing is free."""
    return free_ips[0] if free_ips else None


def sort_ips(ips: Iterable[str]) -> list[str]:
    """Numeric (not lexicographic) sort of dotted-quad IPv4 strings, deduplicated."""
    return sorted(set(ips), key=lambda ip: ipaddress.IPv4Address(ip))
