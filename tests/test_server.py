"""ScanCache logic (unit) + the HTTP handler's routes (loopback only, no
external network or a real scan -- the cache is populated/left empty
directly rather than running the background scan thread).
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from ipscout.server import ScanCache, _make_handler


def test_scan_cache_starts_empty():
    cache = ScanCache()
    report, error = cache.get()
    assert report is None
    assert error is None


def test_scan_cache_set_report_clears_previous_error():
    cache = ScanCache()
    cache.set_error("boom")
    cache.set_report({"next_free_ip": "192.168.4.1"})

    report, error = cache.get()
    assert report == {"next_free_ip": "192.168.4.1"}
    assert error is None


def test_scan_cache_set_error_keeps_previous_report():
    cache = ScanCache()
    cache.set_report({"next_free_ip": "192.168.4.1"})
    cache.set_error("scan failed")

    report, error = cache.get()
    assert report == {"next_free_ip": "192.168.4.1"}
    assert error == "scan failed"


@pytest.fixture
def running_server():
    """A real ThreadingHTTPServer on loopback with a controllable ScanCache."""
    cache = ScanCache()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(cache))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, cache
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _get(httpd, path):
    conn = HTTPConnection(*httpd.server_address, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read(), resp.getheader("Content-Type")
    finally:
        conn.close()


def test_index_route_serves_html(running_server):
    httpd, _cache = running_server
    status, body, content_type = _get(httpd, "/")
    assert status == 200
    assert "text/html" in content_type
    assert b"<html" in body.lower()


def test_index_html_alias_serves_same_page(running_server):
    httpd, _cache = running_server
    status, body, _ = _get(httpd, "/index.html")
    assert status == 200
    assert b"<html" in body.lower()


def test_status_route_503_before_first_scan(running_server):
    httpd, _cache = running_server
    status, body, content_type = _get(httpd, "/api/status")
    assert status == 503
    assert "application/json" in content_type
    assert json.loads(body)["status"] == "starting"


def test_status_route_returns_cached_report(running_server):
    httpd, cache = running_server
    cache.set_report({"next_free_ip": "192.168.4.5", "used_ips": []})

    status, body, _ = _get(httpd, "/api/status")

    assert status == 200
    assert json.loads(body) == {"next_free_ip": "192.168.4.5", "used_ips": []}


def test_status_route_includes_error_alongside_stale_report(running_server):
    httpd, cache = running_server
    cache.set_report({"next_free_ip": "192.168.4.5"})
    cache.set_error("nmap not found")

    status, body, _ = _get(httpd, "/api/status")

    assert status == 200
    payload = json.loads(body)
    assert payload["next_free_ip"] == "192.168.4.5"
    assert payload["last_scan_error"] == "nmap not found"


def test_unknown_route_404s(running_server):
    httpd, _cache = running_server
    status, _body, _ = _get(httpd, "/nope")
    assert status == 404
