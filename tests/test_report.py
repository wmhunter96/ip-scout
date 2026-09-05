"""Cross-referencing containers + a live scan into one report -- container
listing and the subnet scan are both mocked, so this only exercises
report.py's own logic (dedupe, free-IP computation, formatting).
"""

from __future__ import annotations

from conftest import make_config

from ipscout import report as report_module
from ipscout.docker_inspect import ContainerInfo


def test_build_report_cross_references_containers_and_scan(monkeypatch):
    config = make_config(subnet_prefix="192.168.4", range_start=1, range_end=5)

    monkeypatch.setattr(
        report_module,
        "get_container_ips",
        lambda client=None: [
            ContainerInfo(name="web", short_id="abc123", networks=["bridge"], ips=["192.168.4.2"]),
            ContainerInfo(name="hostnet", short_id="def456", networks=["host"], ips=[]),
        ],
    )
    monkeypatch.setattr(
        report_module, "scan_subnet", lambda prefix, start, end: ({"192.168.4.4"}, "ping")
    )

    result = report_module.build_report(config)

    assert result["range"] == "192.168.4.1-5"
    assert result["scan_method"] == "ping"
    assert result["used_ips"] == ["192.168.4.2", "192.168.4.4"]
    assert result["used_ip_count"] == 2
    assert result["free_ips"] == ["192.168.4.1", "192.168.4.3", "192.168.4.5"]
    assert result["free_ip_count"] == 3
    assert result["next_free_ip"] == "192.168.4.1"
    assert [c["name"] for c in result["containers"]] == ["web", "hostnet"]


def test_build_report_dedupes_container_ip_also_seen_by_scan(monkeypatch):
    # A container's IP will almost always also answer the live scan --
    # it shouldn't be double counted.
    config = make_config(subnet_prefix="192.168.4", range_start=1, range_end=3)

    monkeypatch.setattr(
        report_module,
        "get_container_ips",
        lambda client=None: [
            ContainerInfo(name="web", short_id="abc123", networks=["bridge"], ips=["192.168.4.2"])
        ],
    )
    monkeypatch.setattr(
        report_module,
        "scan_subnet",
        lambda prefix, start, end: ({"192.168.4.2", "192.168.4.3"}, "nmap"),
    )

    result = report_module.build_report(config)

    assert result["used_ips"] == ["192.168.4.2", "192.168.4.3"]
    assert result["free_ips"] == ["192.168.4.1"]
    assert result["next_free_ip"] == "192.168.4.1"


def test_build_report_no_free_ips(monkeypatch):
    config = make_config(subnet_prefix="192.168.4", range_start=1, range_end=2)

    monkeypatch.setattr(report_module, "get_container_ips", lambda client=None: [])
    monkeypatch.setattr(
        report_module,
        "scan_subnet",
        lambda prefix, start, end: ({"192.168.4.1", "192.168.4.2"}, "ping"),
    )

    result = report_module.build_report(config)

    assert result["free_ips"] == []
    assert result["next_free_ip"] is None


def test_format_table_includes_key_fields():
    report = {
        "range": "192.168.4.1-5",
        "scan_method": "ping",
        "scanned_at": "2026-09-04T00:00:00+00:00",
        "containers": [
            {"name": "web", "short_id": "abc123", "networks": ["bridge"], "ips": ["192.168.4.2"]},
            {"name": "hostnet", "short_id": "def456", "networks": ["host"], "ips": []},
        ],
        "used_ips": ["192.168.4.2", "192.168.4.4"],
        "used_ip_count": 2,
        "free_ips": ["192.168.4.1", "192.168.4.3", "192.168.4.5"],
        "free_ip_count": 3,
        "next_free_ip": "192.168.4.1",
    }

    table = report_module.format_table(report)

    assert "192.168.4.1-5" in table
    assert "web" in table and "192.168.4.2" in table
    assert "(none / host network)" in table
    assert "Next free IP: 192.168.4.1" in table


def test_format_table_handles_no_containers_and_no_free_ips():
    report = {
        "range": "192.168.4.1-2",
        "scan_method": "ping",
        "scanned_at": "2026-09-04T00:00:00+00:00",
        "containers": [],
        "used_ips": ["192.168.4.1", "192.168.4.2"],
        "used_ip_count": 2,
        "free_ips": [],
        "free_ip_count": 0,
        "next_free_ip": None,
    }

    table = report_module.format_table(report)

    assert "(no running containers)" in table
    assert "(none free)" in table
    assert "Next free IP: (none available)" in table
