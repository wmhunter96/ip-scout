"""Command-line entry point: run-once (table/JSON) or serve mode.

    ip-scout                    # scan once, print a table
    ip-scout --json             # scan once, print JSON
    ip-scout serve              # long-running HTTP server, GET /api/status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence

from .config import Config
from .report import build_report, format_table
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ip-scout",
        description="Show which IPs are in use on a subnet and report the next free one.",
    )
    parser.add_argument(
        "--subnet-prefix", help="e.g. 192.168.4 (overrides SUBNET_PREFIX)"
    )
    parser.add_argument(
        "--range-start", type=int, help="first host octet to scan (overrides RANGE_START)"
    )
    parser.add_argument(
        "--range-end", type=int, help="last host octet to scan (overrides RANGE_END)"
    )
    parser.add_argument(
        "--docker-network",
        help="only consider containers on this Docker network, e.g. br0 for an "
        "Unraid macvlan setup (overrides DOCKER_NETWORK)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON instead of a table"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="enable debug logging"
    )

    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser(
        "serve", help="run a long-lived HTTP server instead of a one-shot scan"
    )
    serve_parser.add_argument("--port", type=int, help="overrides PORT")
    serve_parser.add_argument(
        "--interval", type=int, help="seconds between scans (overrides SCAN_INTERVAL)"
    )

    return parser


def _apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    if args.subnet_prefix is not None:
        config.subnet_prefix = args.subnet_prefix
    if args.range_start is not None:
        config.range_start = args.range_start
    if args.range_end is not None:
        config.range_end = args.range_end
    if args.docker_network is not None:
        config.docker_network = args.docker_network
    if getattr(args, "port", None) is not None:
        config.port = args.port
    if getattr(args, "interval", None) is not None:
        config.scan_interval = args.interval
    return config


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = _apply_overrides(Config.from_env(), args)

    if args.command == "serve":
        serve(config)
        return 0

    try:
        report = build_report(config)
    except Exception as exc:
        # Most likely cause: no Docker socket reachable (wrong mount, wrong
        # DOCKER_HOST, or the daemon isn't up) -- surface a short message
        # instead of a raw traceback for what's usually a setup problem.
        print(f"ip-scout: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_table(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
