"""Pure IP-range math: no network calls, no Docker, no subprocess.

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


def _octets_in_range(ips: Iterable[str], subnet_prefix: str, start: int, end: int) -> set[int]:
    prefix_dot = f"{subnet_prefix}."
    return {
        int(ip[len(prefix_dot) :])
        for ip in ips
        if ip.startswith(prefix_dot) and start <= int(ip[len(prefix_dot) :]) <= end
    }


def nearest_free_neighbors(
    container_ips: Iterable[str], used_ips: Iterable[str], subnet_prefix: str, start: int, end: int
) -> tuple[str | None, str | None]:
    """The free IP directly below the lowest *container* address, and
    directly above the highest, walking outward past any other used
    address (e.g. some unrelated live-scanned LAN device) until a
    genuinely free one turns up or [start, end] runs out.

    Anchored to `container_ips` specifically, not every address in
    `used_ips` -- e.g. used addresses clustered at .234-.251 in a 1-254
    range gives (.233, .252): the two addresses that would extend that
    block by one on either side. A real LAN can easily have other used
    addresses scattered well outside that block (a router at .1, IoT
    devices, whatever else answered the live scan); those aren't where a
    new container would actually go, so they shouldn't shift this
    computation the way they would for `next_free_ip()` (the single
    lowest free address anywhere in the whole range).

    Either side is None when there's no free room left before `start`/`end`,
    or both are None when there are no container addresses in [start, end]
    at all -- nothing to bracket.
    """
    container_octets = _octets_in_range(container_ips, subnet_prefix, start, end)
    if not container_octets:
        return None, None
    used_octets = _octets_in_range(used_ips, subnet_prefix, start, end)

    below = None
    octet = min(container_octets) - 1
    while octet >= start:
        if octet not in used_octets:
            below = f"{subnet_prefix}.{octet}"
            break
        octet -= 1

    above = None
    octet = max(container_octets) + 1
    while octet <= end:
        if octet not in used_octets:
            above = f"{subnet_prefix}.{octet}"
            break
        octet += 1

    return below, above
