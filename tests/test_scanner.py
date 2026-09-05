"""Live-host scanning, with subprocess/shutil fully mocked -- no real
network access, and no dependency on nmap or ping actually being installed,
is required to run this suite.
"""

from __future__ import annotations

import subprocess

from ipscout import scanner

SAMPLE_NMAP_OUTPUT = """
Starting Nmap 7.94 ( https://nmap.org ) at 2026-09-04 12:00 UTC
Nmap scan report for 192.168.4.1
Host is up (0.00089s latency).
Nmap scan report for router.lan (192.168.4.1)
Nmap scan report for 192.168.4.10
Host is up (0.0012s latency).
Nmap done: 254 IP addresses (2 hosts up) scanned in 3.10 seconds
"""


def _fake_completed_process(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_nmap_available_true(monkeypatch):
    monkeypatch.setattr(scanner.shutil, "which", lambda name: "/usr/bin/nmap")
    assert scanner.nmap_available() is True


def test_nmap_available_false(monkeypatch):
    monkeypatch.setattr(scanner.shutil, "which", lambda name: None)
    assert scanner.nmap_available() is False


def test_scan_with_nmap_parses_ips(monkeypatch):
    monkeypatch.setattr(
        scanner.subprocess,
        "run",
        lambda *a, **k: _fake_completed_process(stdout=SAMPLE_NMAP_OUTPUT),
    )
    result = scanner.scan_with_nmap("192.168.4", 1, 254)
    assert result == {"192.168.4.1", "192.168.4.10"}


def test_scan_with_nmap_no_hosts_up(monkeypatch):
    monkeypatch.setattr(
        scanner.subprocess,
        "run",
        lambda *a, **k: _fake_completed_process(stdout="Nmap done: 0 hosts up\n"),
    )
    assert scanner.scan_with_nmap("192.168.4", 1, 254) == set()


def test_ping_sweep_only_responding_ips_are_live(monkeypatch):
    # Simulate .2 and .4 answering, everything else timing out.
    def fake_run(cmd, **kwargs):
        ip = cmd[-1]
        returncode = 0 if ip in ("192.168.4.2", "192.168.4.4") else 1
        return _fake_completed_process(returncode=returncode)

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)

    result = scanner.scan_with_ping_sweep("192.168.4", 1, 5, max_workers=4)

    assert result == {"192.168.4.2", "192.168.4.4"}


def test_ping_sweep_handles_timeout_as_dead(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)

    result = scanner.scan_with_ping_sweep("192.168.4", 1, 3, max_workers=4)

    assert result == set()


def test_scan_subnet_uses_nmap_when_available(monkeypatch):
    monkeypatch.setattr(scanner, "nmap_available", lambda: True)
    monkeypatch.setattr(scanner, "scan_with_nmap", lambda *a, **k: {"192.168.4.1"})
    monkeypatch.setattr(
        scanner, "scan_with_ping_sweep", lambda *a, **k: (_ for _ in ()).throw(AssertionError())
    )

    ips, method = scanner.scan_subnet("192.168.4", 1, 254)

    assert ips == {"192.168.4.1"}
    assert method == "nmap"


def test_scan_subnet_falls_back_to_ping_when_nmap_missing(monkeypatch):
    monkeypatch.setattr(scanner, "nmap_available", lambda: False)
    monkeypatch.setattr(scanner, "scan_with_ping_sweep", lambda *a, **k: {"192.168.4.2"})

    ips, method = scanner.scan_subnet("192.168.4", 1, 254)

    assert ips == {"192.168.4.2"}
    assert method == "ping"


def test_ping_sweep_reports_progress_as_hosts_finish(monkeypatch):
    def fake_run(cmd, **kwargs):
        ip = cmd[-1]
        returncode = 0 if ip == "192.168.4.2" else 1
        return _fake_completed_process(returncode=returncode)

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)

    updates = []
    scanner.scan_with_ping_sweep(
        "192.168.4", 1, 5, max_workers=1, on_progress=lambda f, d: updates.append((f, d))
    )

    # Sequential (max_workers=1) so the order and final state are deterministic.
    assert updates == [
        (0.2, "1/5 hosts checked"),
        (0.4, "2/5 hosts checked"),
        (0.6, "3/5 hosts checked"),
        (0.8, "4/5 hosts checked"),
        (1.0, "5/5 hosts checked"),
    ]


def test_scan_with_nmap_streams_progress_and_still_parses_ips(monkeypatch):
    fake_output_lines = [
        "Starting Nmap 7.94 ( https://nmap.org ) at 2026-09-04 12:00 UTC\n",
        "Stats: 0:00:02 elapsed; 0 hosts completed (0 up), 254 undergoing Ping Scan\n",
        "Ping Scan Timing: About 40.00% done; ETC: 12:00 (0:00:03 remaining)\n",
        "Nmap scan report for 192.168.4.1\n",
        "Host is up (0.00089s latency).\n",
        "Nmap scan report for 192.168.4.10\n",
        "Host is up (0.0012s latency).\n",
        "Nmap done: 254 IP addresses (2 hosts up) scanned in 3.10 seconds\n",
    ]

    class FakeProcess:
        def __init__(self):
            self.stdout = iter(fake_output_lines)
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

        def kill(self):
            pass

    monkeypatch.setattr(scanner.subprocess, "Popen", lambda *a, **k: FakeProcess())

    updates = []
    result = scanner.scan_with_nmap(
        "192.168.4", 1, 254, on_progress=lambda f, d: updates.append((f, d))
    )

    assert result == {"192.168.4.1", "192.168.4.10"}
    assert (0.4, "scanning with nmap") in updates
    assert updates[-1] == (1.0, "nmap scan complete")


def test_scan_subnet_falls_back_to_ping_when_nmap_errors(monkeypatch):
    monkeypatch.setattr(scanner, "nmap_available", lambda: True)

    def raise_error(*a, **k):
        raise subprocess.SubprocessError("boom")

    monkeypatch.setattr(scanner, "scan_with_nmap", raise_error)
    monkeypatch.setattr(scanner, "scan_with_ping_sweep", lambda *a, **k: {"192.168.4.3"})

    ips, method = scanner.scan_subnet("192.168.4", 1, 254)

    assert ips == {"192.168.4.3"}
    assert method == "ping"
