"""Config.from_env() reads the documented env vars, with sane defaults."""

from __future__ import annotations

from ipscout.config import Config


def test_from_env_defaults_when_unset(monkeypatch):
    for var in ("SUBNET_PREFIX", "RANGE_START", "RANGE_END", "SCAN_INTERVAL", "PORT"):
        monkeypatch.delenv(var, raising=False)

    config = Config.from_env()

    assert config.subnet_prefix == "192.168.1"
    assert config.range_start == 1
    assert config.range_end == 254
    assert config.scan_interval == 300
    assert config.port == 8000


def test_from_env_reads_all_vars(monkeypatch):
    monkeypatch.setenv("SUBNET_PREFIX", "10.0.0")
    monkeypatch.setenv("RANGE_START", "10")
    monkeypatch.setenv("RANGE_END", "20")
    monkeypatch.setenv("SCAN_INTERVAL", "120")
    monkeypatch.setenv("PORT", "9000")

    config = Config.from_env()

    assert config.subnet_prefix == "10.0.0"
    assert config.range_start == 10
    assert config.range_end == 20
    assert config.scan_interval == 120
    assert config.port == 9000


def test_range_label():
    config = Config(subnet_prefix="192.168.4", range_start=1, range_end=254)
    assert config.range_label == "192.168.4.1-254"
