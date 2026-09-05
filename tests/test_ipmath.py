"""Range math and free-IP logic -- no network access, no Docker SDK."""

from __future__ import annotations

import pytest

from ipscout import ipmath


def test_generate_range_basic():
    assert ipmath.generate_range("192.168.4", 1, 5) == [
        "192.168.4.1",
        "192.168.4.2",
        "192.168.4.3",
        "192.168.4.4",
        "192.168.4.5",
    ]


def test_generate_range_single_host():
    assert ipmath.generate_range("10.0.0", 42, 42) == ["10.0.0.42"]


def test_generate_range_start_after_end_raises():
    with pytest.raises(ValueError, match="range_start"):
        ipmath.generate_range("192.168.4", 10, 5)


@pytest.mark.parametrize("start,end", [(-1, 10), (10, 300), (0, 256)])
def test_generate_range_invalid_octet_raises(start, end):
    with pytest.raises(ValueError):
        ipmath.generate_range("192.168.4", start, end)


def test_compute_free_ips_removes_used():
    all_ips = ipmath.generate_range("192.168.4", 1, 5)
    used = {"192.168.4.1", "192.168.4.3"}
    assert ipmath.compute_free_ips(all_ips, used) == [
        "192.168.4.2",
        "192.168.4.4",
        "192.168.4.5",
    ]


def test_compute_free_ips_nothing_used():
    all_ips = ipmath.generate_range("192.168.4", 1, 3)
    assert ipmath.compute_free_ips(all_ips, []) == all_ips


def test_compute_free_ips_everything_used():
    all_ips = ipmath.generate_range("192.168.4", 1, 3)
    assert ipmath.compute_free_ips(all_ips, all_ips) == []


def test_next_free_ip_returns_first():
    assert ipmath.next_free_ip(["192.168.4.2", "192.168.4.4"]) == "192.168.4.2"


def test_next_free_ip_none_when_empty():
    assert ipmath.next_free_ip([]) is None


def test_sort_ips_numeric_not_lexicographic():
    # Lexicographic sort would put ".2" after ".10" and ".100"; numeric sort
    # of real IPv4 addresses should not.
    unsorted = ["192.168.4.100", "192.168.4.2", "192.168.4.10", "192.168.4.1"]
    assert ipmath.sort_ips(unsorted) == [
        "192.168.4.1",
        "192.168.4.2",
        "192.168.4.10",
        "192.168.4.100",
    ]


def test_sort_ips_dedupes():
    assert ipmath.sort_ips(["192.168.4.2", "192.168.4.2", "192.168.4.1"]) == [
        "192.168.4.1",
        "192.168.4.2",
    ]
