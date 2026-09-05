"""Live-host discovery for a subnet range: nmap when available, ping sweep otherwise.

Both paths need raw-socket access (CAP_NET_RAW) to send ICMP -- see the
"Network access" section of the README for what that means for how the
container is run.
"""

from __future__ import annotations

import logging
import platform
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Matches nmap's "Nmap scan report for 192.168.4.12" and, when reverse DNS
# resolves, "Nmap scan report for somehost.lan (192.168.4.12)".
_NMAP_HOST_RE = re.compile(r"Nmap scan report for (?:\S+ \()?(\d{1,3}(?:\.\d{1,3}){3})\)?")

_PING_TIMEOUT_S = 1.0
_PING_MAX_WORKERS = 32


def nmap_available() -> bool:
    return shutil.which("nmap") is not None


def scan_with_nmap(subnet_prefix: str, start: int, end: int, timeout: int = 60) -> set[str]:
    """Ping-scan (-sn, no port scan) the range with nmap; return responding IPs."""
    target = f"{subnet_prefix}.{start}-{end}"
    proc = subprocess.run(
        ["nmap", "-sn", "-n", target],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return set(_NMAP_HOST_RE.findall(proc.stdout))


def _ping_once(ip: str, timeout_s: float = _PING_TIMEOUT_S) -> str | None:
    """Send a single ICMP echo; return the IP if it responds, else None."""
    if platform.system().lower() == "windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(int(timeout_s)), ip]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s + 2, check=False
        )
    except subprocess.TimeoutExpired:
        return None
    return ip if proc.returncode == 0 else None


def scan_with_ping_sweep(
    subnet_prefix: str,
    start: int,
    end: int,
    max_workers: int = _PING_MAX_WORKERS,
    timeout_s: float = _PING_TIMEOUT_S,
) -> set[str]:
    """Fallback used when nmap isn't installed: a parallelized ping sweep of the range."""
    ips = [f"{subnet_prefix}.{i}" for i in range(start, end + 1)]
    live: set[str] = set()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_ping_once, ip, timeout_s) for ip in ips]
        for future in as_completed(futures):
            result = future.result()
            if result:
                live.add(result)
    return live


def scan_subnet(subnet_prefix: str, start: int, end: int) -> tuple[set[str], str]:
    """Scan the range, preferring nmap. Returns (live_ips, method_used)."""
    if nmap_available():
        try:
            return scan_with_nmap(subnet_prefix, start, end), "nmap"
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("nmap scan failed (%s); falling back to ping sweep", exc)
    return scan_with_ping_sweep(subnet_prefix, start, end), "ping"
