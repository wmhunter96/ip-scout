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
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Matches nmap's "Nmap scan report for 192.168.4.12" and, when reverse DNS
# resolves, "Nmap scan report for somehost.lan (192.168.4.12)".
_NMAP_HOST_RE = re.compile(r"Nmap scan report for (?:\S+ \()?(\d{1,3}(?:\.\d{1,3}){3})\)?")

# nmap's own "About X% done" progress line, emitted periodically by
# `-v --stats-every` (only requested when a caller wants progress).
_NMAP_STATS_RE = re.compile(r"About ([\d.]+)% done")

_PING_TIMEOUT_S = 1.0
_PING_MAX_WORKERS = 32

# Reports (fraction 0.0-1.0, human-readable detail) as a scan progresses.
ProgressCallback = Callable[[float, str], None]


def nmap_available() -> bool:
    return shutil.which("nmap") is not None


def scan_with_nmap(
    subnet_prefix: str,
    start: int,
    end: int,
    timeout: int = 60,
    on_progress: ProgressCallback | None = None,
) -> set[str]:
    """Ping-scan (-sn, no port scan) the range with nmap; return responding IPs."""
    target = f"{subnet_prefix}.{start}-{end}"
    if on_progress is None:
        proc = subprocess.run(
            ["nmap", "-sn", "-n", target],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return set(_NMAP_HOST_RE.findall(proc.stdout))
    return _scan_with_nmap_tracking_progress(target, timeout, on_progress)


def _scan_with_nmap_tracking_progress(
    target: str, timeout: int, on_progress: ProgressCallback
) -> set[str]:
    """Same scan as scan_with_nmap, but run with `-v --stats-every` and its
    output streamed line-by-line so periodic "About X% done" lines can be
    parsed out and reported as they arrive, instead of the caller only
    finding out once the whole (possibly slow) scan has finished."""
    cmd = ["nmap", "-sn", "-n", "-v", "--stats-every", "2s", target]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            match = _NMAP_STATS_RE.search(line)
            if match:
                percent = min(float(match.group(1)), 100.0)
                on_progress(percent / 100.0, "scanning with nmap")
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(cmd, timeout)
        proc.wait(timeout=max(0.0, deadline - time.monotonic()))
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    on_progress(1.0, "nmap scan complete")
    return set(_NMAP_HOST_RE.findall("".join(lines)))


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
    on_progress: ProgressCallback | None = None,
) -> set[str]:
    """Fallback used when nmap isn't installed: a parallelized ping sweep of the range.

    This is the slower path (one subprocess per host, capped at
    _PING_MAX_WORKERS in flight), so it's also the one most worth reporting
    granular progress for: every host that finishes -- up or down -- moves
    the count forward.
    """
    ips = [f"{subnet_prefix}.{i}" for i in range(start, end + 1)]
    total = len(ips)
    live: set[str] = set()
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_ping_once, ip, timeout_s) for ip in ips]
        for future in as_completed(futures):
            result = future.result()
            if result:
                live.add(result)
            done += 1
            if on_progress is not None and total:
                on_progress(done / total, f"{done}/{total} hosts checked")
    return live


def scan_subnet(
    subnet_prefix: str, start: int, end: int, on_progress: ProgressCallback | None = None
) -> tuple[set[str], str]:
    """Scan the range, preferring nmap. Returns (live_ips, method_used)."""
    if nmap_available():
        try:
            return scan_with_nmap(subnet_prefix, start, end, on_progress=on_progress), "nmap"
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("nmap scan failed (%s); falling back to ping sweep", exc)
    return scan_with_ping_sweep(subnet_prefix, start, end, on_progress=on_progress), "ping"
