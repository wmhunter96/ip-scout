"""Serve mode: a tiny long-running HTTP server exposing GET /api/status plus
a small built-in dashboard at GET /.

Scans run on a background timer (every SCAN_INTERVAL seconds) instead of
per-request, so a slow nmap/ping sweep never blocks a caller polling the
endpoint (e.g. a Homarr Custom API widget) -- callers just get the most
recently cached report. Deliberately built on stdlib http.server rather
than a framework: these are two static/read-only responses (plus a POST
to kick off an out-of-cycle scan), and it keeps the image free of a web
framework + ASGI server dependency chain. The dashboard itself is a single
static HTML file (static/index.html) that just polls /api/status
client-side -- no templating, no separate frontend build step.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import Config
from .report import build_report

logger = logging.getLogger(__name__)

_STATUS_PATHS = ("/api/status", "/api/status/")
_INDEX_PATHS = ("/", "/index.html")
_RESCAN_PATHS = ("/api/scan-now", "/api/scan-now/")
_INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_bytes()

# How often the scan loop's wait wakes up to check whether a "scan now"
# request has come in -- keeps the button feeling responsive without
# needing a smarter (event-per-purpose) wait primitive.
_RESCAN_POLL_S = 0.5

_IDLE_PROGRESS = {"scanning": False, "fraction": 1.0, "detail": ""}


class ScanCache:
    """Thread-safe holder for the most recent report, last error (if any),
    and in-progress-scan status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._report: dict[str, Any] | None = None
        self._error: str | None = None
        self._progress: dict[str, Any] = {"scanning": False, "fraction": 0.0, "detail": ""}

    def set_report(self, report: dict[str, Any]) -> None:
        with self._lock:
            self._report = report
            self._error = None

    def set_error(self, error: str) -> None:
        with self._lock:
            self._error = error

    def start_scan(self) -> None:
        with self._lock:
            self._progress = {"scanning": True, "fraction": 0.0, "detail": "starting scan"}

    def update_progress(self, fraction: float, detail: str) -> None:
        """Matches scanner.ProgressCallback -- passed straight through as
        build_report's on_scan_progress."""
        with self._lock:
            self._progress = {"scanning": True, "fraction": fraction, "detail": detail}

    def finish_scan(self) -> None:
        with self._lock:
            self._progress = dict(_IDLE_PROGRESS)

    def get(self) -> tuple[dict[str, Any] | None, str | None]:
        with self._lock:
            return self._report, self._error

    def get_progress(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._progress)


def _wait_for_rescan_or_interval(
    stop_event: threading.Event, rescan_event: threading.Event, interval: float
) -> None:
    """Sleep until the scan interval elapses, the server is stopping, or a
    "scan now" request comes in -- whichever happens first."""
    deadline = time.monotonic() + interval
    while not stop_event.is_set() and not rescan_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        stop_event.wait(min(remaining, _RESCAN_POLL_S))


def _scan_loop(
    config: Config, cache: ScanCache, stop_event: threading.Event, rescan_event: threading.Event
) -> None:
    while not stop_event.is_set():
        cache.start_scan()
        try:
            cache.set_report(build_report(config, on_scan_progress=cache.update_progress))
        except Exception as exc:  # keep serving stale data rather than dying
            logger.exception("Scan failed")
            cache.set_error(str(exc))
        finally:
            cache.finish_scan()
        if rescan_event.is_set():
            # A "scan now" request came in while the scan above was already
            # running -- honor it by looping straight back around instead of
            # clearing it unconsumed and waiting out the rest of the interval
            # (which, for a slow first scan, could be the full SCAN_INTERVAL).
            rescan_event.clear()
            continue
        _wait_for_rescan_or_interval(stop_event, rescan_event, config.scan_interval)


def _make_handler(
    cache: ScanCache, rescan_event: threading.Event | None = None
) -> type[BaseHTTPRequestHandler]:
    # Falls back to a throwaway Event when no scan loop is wired up (as in
    # tests that exercise routes directly) so POST /api/scan-now still
    # responds sensibly instead of needing special-casing below.
    event = rescan_event if rescan_event is not None else threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quiet default access log
            logger.info("%s - %s", self.address_string(), fmt % args)

        def do_GET(self) -> None:
            if self.path in _INDEX_PATHS:
                self._serve_index()
            elif self.path in _STATUS_PATHS:
                self._serve_status()
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            if self.path in _RESCAN_PATHS:
                self._trigger_rescan()
            else:
                self.send_response(404)
                self.end_headers()

        def _serve_index(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_INDEX_HTML)))
            self.end_headers()
            self.wfile.write(_INDEX_HTML)

        def _serve_status(self) -> None:
            report, error = cache.get()
            progress = cache.get_progress()
            if report is None:
                status_code = 503
                body = json.dumps(
                    {"status": "starting", "error": error, "progress": progress}
                ).encode()
            else:
                status_code = 200
                payload = dict(report)
                if error:
                    payload["last_scan_error"] = error
                payload["progress"] = progress
                body = json.dumps(payload).encode()

            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _trigger_rescan(self) -> None:
            # Just a wake-up signal for the scan loop's wait -- if a scan is
            # already running this makes the *next* one start immediately
            # rather than interrupting the current one.
            event.set()
            body = json.dumps({"status": "rescan requested"}).encode()
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(config: Config) -> None:
    cache = ScanCache()
    stop_event = threading.Event()
    rescan_event = threading.Event()

    scan_thread = threading.Thread(
        target=_scan_loop, args=(config, cache, stop_event, rescan_event), daemon=True
    )
    scan_thread.start()

    httpd = ThreadingHTTPServer(("0.0.0.0", config.port), _make_handler(cache, rescan_event))
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
