"""Container -> IP extraction, with the Docker SDK fully mocked out.

None of these tests touch a real Docker daemon -- `client` is always a
hand-built fake standing in for `docker.DockerClient`.
"""

from __future__ import annotations

import pytest

from ipscout import docker_inspect
from ipscout.docker_inspect import ContainerInfo, get_container_ips, get_docker_client


class FakeContainer:
    def __init__(self, name: str, short_id: str, networks: dict):
        self.name = name
        self.short_id = short_id
        self.attrs = {"NetworkSettings": {"Networks": networks}}


class FakeContainerCollection:
    def __init__(self, containers: list[FakeContainer]):
        self._containers = containers

    def list(self):
        return self._containers


class FakeClient:
    def __init__(self, containers: list[FakeContainer]):
        self.containers = FakeContainerCollection(containers)
        self.closed = False

    def close(self):
        self.closed = True


def test_get_container_ips_single_network():
    client = FakeClient(
        [FakeContainer("web", "abc123", {"bridge": {"IPAddress": "172.17.0.2"}})]
    )

    result = get_container_ips(client=client)

    assert result == [
        ContainerInfo(name="web", short_id="abc123", networks=["bridge"], ips=["172.17.0.2"])
    ]


def test_get_container_ips_multiple_networks():
    client = FakeClient(
        [
            FakeContainer(
                "multi",
                "def456",
                {
                    "bridge": {"IPAddress": "172.17.0.3"},
                    "lan": {"IPAddress": "192.168.4.50"},
                },
            )
        ]
    )

    [info] = get_container_ips(client=client)

    assert info.name == "multi"
    assert set(info.networks) == {"bridge", "lan"}
    assert set(info.ips) == {"172.17.0.3", "192.168.4.50"}


def test_get_container_ips_host_networking_has_no_ip():
    # Host-networked containers show a "host" network entry with no IPAddress.
    client = FakeClient([FakeContainer("hostnet", "ghi789", {"host": {"IPAddress": ""}})])

    [info] = get_container_ips(client=client)

    assert info.networks == ["host"]
    assert info.ips == []


def test_get_container_ips_no_containers():
    client = FakeClient([])
    assert get_container_ips(client=client) == []


def test_get_container_ips_does_not_close_externally_owned_client():
    client = FakeClient([FakeContainer("web", "abc123", {"bridge": {"IPAddress": "172.17.0.2"}})])

    get_container_ips(client=client)

    assert client.closed is False


def test_get_docker_client_raises_when_sdk_missing(monkeypatch):
    monkeypatch.setattr(docker_inspect, "docker", None)
    with pytest.raises(RuntimeError, match="docker"):
        get_docker_client()
