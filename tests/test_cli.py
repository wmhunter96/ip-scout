"""CLI arg parsing and dispatch -- build_report/serve are mocked, so no
scan or HTTP server actually runs.
"""

from __future__ import annotations

from ipscout import cli


def test_default_command_prints_table(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "build_report", lambda config: {"range": "192.168.4.1-254", "next_free_ip": None}
    )
    monkeypatch.setattr(cli, "format_table", lambda report: "TABLE OUTPUT")

    exit_code = cli.main([])

    assert exit_code == 0
    assert "TABLE OUTPUT" in capsys.readouterr().out


def test_json_flag_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_report", lambda config: {"next_free_ip": "192.168.4.1"})

    exit_code = cli.main(["--json"])

    assert exit_code == 0
    assert '"next_free_ip": "192.168.4.1"' in capsys.readouterr().out


def test_cli_overrides_take_precedence_over_env(monkeypatch):
    monkeypatch.setenv("SUBNET_PREFIX", "10.0.0")
    monkeypatch.setenv("RANGE_START", "1")
    monkeypatch.setenv("RANGE_END", "254")

    captured = {}

    def fake_build_report(config):
        captured["config"] = config
        return {"next_free_ip": None}

    monkeypatch.setattr(cli, "build_report", fake_build_report)

    cli.main(
        ["--subnet-prefix", "192.168.9", "--range-start", "50", "--range-end", "60", "--json"]
    )

    assert captured["config"].subnet_prefix == "192.168.9"
    assert captured["config"].range_start == 50
    assert captured["config"].range_end == 60


def test_build_report_failure_prints_message_and_exits_nonzero(monkeypatch, capsys):
    def fake_build_report(config):
        raise RuntimeError("cannot connect to Docker daemon")

    monkeypatch.setattr(cli, "build_report", fake_build_report)

    exit_code = cli.main([])

    assert exit_code == 1
    assert "cannot connect to Docker daemon" in capsys.readouterr().err


def test_serve_subcommand_calls_serve_with_overrides(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "serve", lambda config: captured.setdefault("config", config))

    exit_code = cli.main(["serve", "--port", "9090", "--interval", "45"])

    assert exit_code == 0
    assert captured["config"].port == 9090
    assert captured["config"].scan_interval == 45
