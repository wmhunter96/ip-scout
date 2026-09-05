"""Cross-references Docker container IPs with a live subnet scan.

This is the one function both the CLI and serve mode call -- everything
above it (docker_inspect, scanner, ipmath) is a pure building block; this
module is where they get combined into the report a caller actually wants.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from . import ipmath
from .config import Config
from .docker_inspect import get_container_ips
from .scanner import ProgressCallback, scan_subnet


def build_report(
    config: Config, on_scan_progress: ProgressCallback | None = None
) -> dict[str, Any]:
    containers = get_container_ips()
    container_ips = {ip for c in containers for ip in c.ips}

    live_ips, scan_method = scan_subnet(
        config.subnet_prefix, config.range_start, config.range_end, on_progress=on_scan_progress
    )

    all_ips_in_range = ipmath.generate_range(
        config.subnet_prefix, config.range_start, config.range_end
    )
    used_ips = ipmath.sort_ips(container_ips | live_ips)
    free_ips = ipmath.compute_free_ips(all_ips_in_range, used_ips)
    next_free_below, next_free_above = ipmath.nearest_free_neighbors(
        used_ips, config.subnet_prefix, config.range_start, config.range_end
    )

    return {
        "scanned_at": datetime.now(UTC).isoformat(),
        "subnet_prefix": config.subnet_prefix,
        "range": config.range_label,
        "scan_method": scan_method,
        "containers": [asdict(c) for c in containers],
        "used_ips": used_ips,
        "used_ip_count": len(used_ips),
        "free_ips": free_ips,
        "free_ip_count": len(free_ips),
        "next_free_ip": ipmath.next_free_ip(free_ips),
        "next_free_below": next_free_below,
        "next_free_above": next_free_above,
    }


def format_table(report: dict[str, Any]) -> str:
    """Render a report dict (as returned by build_report) as a plain-text table."""
    lines = [
        f"ip-scout - {report['range']}  "
        f"(scan: {report['scan_method']}, at {report['scanned_at']})",
        "",
        "Containers:",
    ]

    containers = report["containers"]
    if containers:
        name_width = max(len("NAME"), *(len(c["name"]) for c in containers))
        lines.append(f"  {'NAME'.ljust(name_width)}  IPS")
        for c in containers:
            ip_str = ", ".join(c["ips"]) if c["ips"] else "(none / host network)"
            lines.append(f"  {c['name'].ljust(name_width)}  {ip_str}")
    else:
        lines.append("  (no running containers)")

    lines += [
        "",
        f"In-use IPs ({report['used_ip_count']}): "
        + (", ".join(report["used_ips"]) or "(none found)"),
        f"Free IPs ({report['free_ip_count']}): "
        + (", ".join(report["free_ips"]) or "(none free)"),
        "",
        f"Next free IP: {report['next_free_ip'] or '(none available)'}",
        f"Next free below used block: {report.get('next_free_below') or '(none available)'}",
        f"Next free above used block: {report.get('next_free_above') or '(none available)'}",
    ]
    return "\n".join(lines)
