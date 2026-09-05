"""Range math and free-IP logic -- no network access, no Docker."""

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


def test_nearest_free_neighbors_brackets_a_used_cluster():
    containers = [f"192.168.4.{i}" for i in range(234, 252)]  # .234-.251
    below, above = ipmath.nearest_free_neighbors(containers, containers, "192.168.4", 1, 254)
    assert below == "192.168.4.233"
    assert above == "192.168.4.252"


def test_nearest_free_neighbors_single_used_ip():
    containers = ["192.168.4.100"]
    below, above = ipmath.nearest_free_neighbors(containers, containers, "192.168.4", 1, 254)
    assert below == "192.168.4.99"
    assert above == "192.168.4.101"


def test_nearest_free_neighbors_no_room_below_at_range_start():
    containers = ["192.168.4.1", "192.168.4.50"]
    below, above = ipmath.nearest_free_neighbors(containers, containers, "192.168.4", 1, 254)
    assert below is None  # the lowest container IP already sits at range_start
    assert above == "192.168.4.51"


def test_nearest_free_neighbors_no_room_above_at_range_end():
    containers = ["192.168.4.200", "192.168.4.254"]
    below, above = ipmath.nearest_free_neighbors(containers, containers, "192.168.4", 1, 254)
    assert below == "192.168.4.199"
    assert above is None  # the highest container IP already sits at range_end


def test_nearest_free_neighbors_no_containers_in_range():
    # Nothing to bracket even if other addresses happen to be used.
    below, above = ipmath.nearest_free_neighbors([], ["192.168.4.50"], "192.168.4", 1, 254)
    assert (below, above) == (None, None)


def test_nearest_free_neighbors_ignores_containers_outside_the_subnet_or_range():
    # A container on a different Docker network (172.17.x) and an address
    # outside [start, end] shouldn't affect the bracket at all.
    containers = ["172.17.0.2", "192.168.4.0", "192.168.4.234", "192.168.4.251"]
    below, above = ipmath.nearest_free_neighbors(containers, containers, "192.168.4", 1, 254)
    assert below == "192.168.4.233"
    assert above == "192.168.4.252"


def test_nearest_free_neighbors_ignores_unrelated_used_addresses_far_from_the_block():
    # Regression test: scattered LAN devices detected by the live scan (a
    # router, IoT gear, etc.) at addresses well below the container block
    # must not shift the "below" answer down to bracket *them* instead --
    # only the container block itself anchors the bracket.
    containers = [f"192.168.4.{i}" for i in range(234, 252)]  # .234-.251
    used = containers + ["192.168.4.1", "192.168.4.20", "192.168.4.66"]
    below, above = ipmath.nearest_free_neighbors(containers, used, "192.168.4", 1, 254)
    assert below == "192.168.4.233"
    assert above == "192.168.4.252"


def test_nearest_free_neighbors_walks_past_other_used_addresses_adjacent_to_the_block():
    # If the address immediately outside the block is *also* used by
    # something else, the answer should skip past it to the next genuinely
    # free one, not just blindly report block_edge +/- 1 as "free".
    containers = [f"192.168.4.{i}" for i in range(234, 252)]  # .234-.251
    used = containers + ["192.168.4.233", "192.168.4.252"]
    below, above = ipmath.nearest_free_neighbors(containers, used, "192.168.4", 1, 254)
    assert below == "192.168.4.232"
    assert above == "192.168.4.253"
