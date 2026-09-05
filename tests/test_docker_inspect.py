"""Container -> IP extraction, with `docker` (the CLI) fully mocked out --
no real Docker daemon, socket, or subprocess is touched.
"""

from __future__ import annotations

import json
import subprocess

from ipscout import docker_inspect
from ipscout.docker_inspect import ContainerInfo, get_container_ips


def _fake_completed_process(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _container_json(name: str, container_id: str, networks: dict) -> str:
    return json.dumps(
        {
            "Id": container_id,
            "Name": f"/{name}",  # docker inspect's own Name is always "/"-prefixed
            "NetworkSettings": {"Networks": networks},
        }
    )


def _fake_docker(ps_output: str, inspect_output: str):
    """Returns a fake `subprocess.run` that answers `docker ps -q` with
    ps_output and `docker inspect ...` with inspect_output."""

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return _fake_completed_process(stdout=ps_output)
        if cmd[:2] == ["docker", "inspect"]:
            return _fake_completed_process(stdout=inspect_output)
        raise AssertionError(f"unexpected docker command: {cmd}")

    return fake_run


def test_get_container_ips_single_network(monkeypatch):
    inspect_out = _container_json("web", "abc123def456", {"bridge": {"IPAddress": "172.17.0.2"}})
    monkeypatch.setattr(
        docker_inspect.subprocess, "run", _fake_docker("abc123def456\n", inspect_out + "\n")
    )

    result = get_container_ips()

    assert result == [
        ContainerInfo(name="web", short_id="abc123def456", networks=["bridge"], ips=["172.17.0.2"])
    ]


def test_get_container_ips_multiple_networks(monkeypatch):
    inspect_out = _container_json(
        "multi",
        "def456abc789",
        {
            "bridge": {"IPAddress": "172.17.0.3"},
            "lan": {"IPAddress": "192.168.4.50"},
        },
    )
    monkeypatch.setattr(
        docker_inspect.subprocess, "run", _fake_docker("def456abc789\n", inspect_out + "\n")
    )

    [info] = get_container_ips()

    assert info.name == "multi"
    assert set(info.networks) == {"bridge", "lan"}
    assert set(info.ips) == {"172.17.0.3", "192.168.4.50"}


def test_get_container_ips_host_networking_has_no_ip(monkeypatch):
    # Host-networked containers show a "host" network entry with no IPAddress.
    inspect_out = _container_json("hostnet", "ghi789jkl012", {"host": {"IPAddress": ""}})
    monkeypatch.setattr(
        docker_inspect.subprocess, "run", _fake_docker("ghi789jkl012\n", inspect_out + "\n")
    )

    [info] = get_container_ips()

    assert info.networks == ["host"]
    assert info.ips == []


def test_get_container_ips_no_containers(monkeypatch):
    monkeypatch.setattr(docker_inspect.subprocess, "run", _fake_docker("", ""))
    assert get_container_ips() == []


def test_get_container_ips_short_id_is_truncated_to_twelve_chars(monkeypatch):
    full_id = "abc123def456789extra"
    inspect_out = _container_json("web", full_id, {"bridge": {"IPAddress": "172.17.0.2"}})
    monkeypatch.setattr(
        docker_inspect.subprocess, "run", _fake_docker(full_id + "\n", inspect_out + "\n")
    )

    [info] = get_container_ips()

    assert info.short_id == full_id[:12]


def test_get_container_ips_network_filter_drops_other_networks(monkeypatch):
    # A container on both the default bridge and a macvlan network -- with
    # a filter, only the matching network's name/IP should survive.
    inspect_out = _container_json(
        "multi",
        "def456abc789",
        {
            "bridge": {"IPAddress": "172.17.0.3"},
            "br0": {"IPAddress": "192.168.4.50"},
        },
    )
    monkeypatch.setattr(
        docker_inspect.subprocess, "run", _fake_docker("def456abc789\n", inspect_out + "\n")
    )

    [info] = get_container_ips(network_filter="br0")

    assert info.networks == ["br0"]
    assert info.ips == ["192.168.4.50"]


def test_get_container_ips_network_filter_drops_containers_not_on_it_at_all(monkeypatch):
    # A container with no presence on the filtered network shouldn't show
    # up in the result at all, not just with empty networks/ips.
    inspect_out = _container_json("web", "abc123def456", {"bridge": {"IPAddress": "172.17.0.2"}})
    monkeypatch.setattr(
        docker_inspect.subprocess, "run", _fake_docker("abc123def456\n", inspect_out + "\n")
    )

    assert get_container_ips(network_filter="br0") == []


def test_get_container_ips_no_filter_keeps_every_network(monkeypatch):
    inspect_out = _container_json(
        "multi",
        "def456abc789",
        {"bridge": {"IPAddress": "172.17.0.3"}, "br0": {"IPAddress": "192.168.4.50"}},
    )
    monkeypatch.setattr(
        docker_inspect.subprocess, "run", _fake_docker("def456abc789\n", inspect_out + "\n")
    )

    [info] = get_container_ips(network_filter=None)

    assert set(info.networks) == {"bridge", "br0"}


def test_get_container_ips_inspects_all_running_ids_in_one_call(monkeypatch):
    ids = ["id1", "id2"]
    inspect_out = "\n".join(
        _container_json(f"c{i}", cid, {"bridge": {"IPAddress": f"172.17.0.{i + 2}"}})
        for i, cid in enumerate(ids)
    )
    seen_inspect_cmds = []

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return _fake_completed_process(stdout="\n".join(ids) + "\n")
        if cmd[:2] == ["docker", "inspect"]:
            seen_inspect_cmds.append(cmd)
            return _fake_completed_process(stdout=inspect_out + "\n")
        raise AssertionError(f"unexpected docker command: {cmd}")

    monkeypatch.setattr(docker_inspect.subprocess, "run", fake_run)

    result = get_container_ips()

    # One `docker inspect` call covering both IDs, not one call per container.
    assert len(seen_inspect_cmds) == 1
    assert seen_inspect_cmds[0][-2:] == ids
    assert [c.name for c in result] == ["c0", "c1"]
