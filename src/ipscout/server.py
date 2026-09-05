"""Serve mode: a tiny long-running HTTP server exposing GET /api/status.

Scans run on a background timer (every SCAN_INTERVAL seconds) instead of
per-request, so a slow nmap/ping sweep never blocks a caller polling the
endpoint (e.g. a Homarr Custom API widget) -- callers just get the most
recently cached report. Deliberately built on stdlib http.server rather
than a framework: this is a single read-only endpoint, and it keeps the
image free of a web framework + ASGI server dependency chain.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import Config
from .report import build_report

logger = logging.getLogger(__name__)

_STATUS_PATHS = ("/api/status", "/api/status/")


class ScanCache:
    """Thread-safe holder for the most recent report (and last error, if any)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._report: dict[str, Any] | None = None
        self._error: str | None = None

    def set_report(self, report: dict[str, Any]) -> None:
        with self._lock:
            self._report = report
            self._error = None

    def set_error(self, error: str) -> None:
        with self._lock:
            self._error = error

    def get(self) -> tuple[dict[str, Any] | None, str | None]:
        with self._lock:
            return self._report, self._error


def _scan_loop(config: Config, cache: ScanCache, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            cache.set_report(build_report(config))
        except Exception as exc:  # keep serving stale data rather than dying
            logger.exception("Scan failed")
            cache.set_error(str(exc))
        stop_event.wait(config.scan_interval)


def _make_handler(cache: ScanCache) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quiet default access log
            logger.info("%s - %s", self.address_string(), fmt % args)

        def do_GET(self) -> None:
            if self.path not in _STATUS_PATHS:
                self.send_response(404)
                self.end_headers()
                return

            report, error = cache.get()
            if report is None:
                status_code = 503
                body = json.dumps({"status": "starting", "error": error}).encode()
            else:
                status_code = 200
                payload = dict(report)
                if error:
                    payload["last_scan_error"] = error
                body = json.dumps(payload).encode()

            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(config: Config) -> None:
    cache = ScanCache()
    stop_event = threading.Event()

    scan_thread = threading.Thread(
        target=_scan_loop, args=(config, cache, stop_event), daemon=True
    )
    scan_thread.start()

    httpd = ThreadingHTTPServer(("0.0.0.0", config.port), _make_handler(cache))
    logger.info(
        "ip-scout serving on :%s (scanning %s every %ss)",
        config.port,
        config.range_label,
        config.scan_interval,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        httpd.shutdown()
