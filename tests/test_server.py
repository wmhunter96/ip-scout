"""ScanCache logic (unit) + the HTTP handler's routes (loopback only, no
external network or a real scan -- the cache is populated/left empty
directly rather than running the background scan thread).
"""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest
from conftest import make_config

from ipscout import server as server_module
from ipscout.server import ScanCache, _make_handler, _scan_loop


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
    payload = json.loads(body)
    assert payload["next_free_ip"] == "192.168.4.5"
    assert payload["used_ips"] == []
    assert payload["progress"] == {"scanning": False, "fraction": 0.0, "detail": ""}


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


def test_scan_cache_progress_starts_idle():
    cache = ScanCache()
    assert cache.get_progress() == {"scanning": False, "fraction": 0.0, "detail": ""}


def test_scan_cache_tracks_progress_through_a_scan():
    cache = ScanCache()

    cache.start_scan()
    assert cache.get_progress() == {"scanning": True, "fraction": 0.0, "detail": "starting scan"}

    cache.update_progress(0.5, "128/254 hosts checked")
    assert cache.get_progress() == {
        "scanning": True,
        "fraction": 0.5,
        "detail": "128/254 hosts checked",
    }

    cache.finish_scan()
    assert cache.get_progress() == {"scanning": False, "fraction": 1.0, "detail": ""}


def _post(httpd, path):
    conn = HTTPConnection(*httpd.server_address, timeout=5)
    try:
        conn.request("POST", path)
        resp = conn.getresponse()
        return resp.status, resp.read(), resp.getheader("Content-Type")
    finally:
        conn.close()


def test_status_route_503_includes_progress_before_first_scan(running_server):
    httpd, cache = running_server
    cache.start_scan()
    cache.update_progress(0.3, "76/254 hosts checked")

    status, body, _ = _get(httpd, "/api/status")

    assert status == 503
    payload = json.loads(body)
    assert payload["progress"] == {
        "scanning": True,
        "fraction": 0.3,
        "detail": "76/254 hosts checked",
    }


def test_scan_now_route_sets_rescan_event():
    cache = ScanCache()
    rescan_event = threading.Event()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(cache, rescan_event))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, body, content_type = _post(httpd, "/api/scan-now")
        assert status == 202
        assert "application/json" in content_type
        assert json.loads(body)["status"] == "rescan requested"
        assert rescan_event.is_set()
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def test_unknown_post_route_404s(running_server):
    httpd, _cache = running_server
    status, _body, _ = _post(httpd, "/nope")
    assert status == 404


def test_scan_loop_honors_rescan_requested_during_a_scan(monkeypatch):
    """Regression test: clicking "Scan now" while a scan is already running
    (e.g. a slow first scan) used to be silently dropped -- the loop cleared
    the request unconsumed and waited out the rest of SCAN_INTERVAL instead
    of running the requested scan right away."""
    call_count = 0
    stop_event = threading.Event()
    rescan_event = threading.Event()

    def fake_build_report(config, docker_client=None, on_scan_progress=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate a "Scan now" click landing while this scan is running.
            rescan_event.set()
        else:
            stop_event.set()
        return {"scanned_at": "now"}

    monkeypatch.setattr(server_module, "build_report", fake_build_report)

    config = make_config(scan_interval=300)  # would hang the test if the bug regressed
    cache = ScanCache()

    start = time.monotonic()
    _scan_loop(config, cache, stop_event, rescan_event)
    elapsed = time.monotonic() - start

    assert call_count == 2
    assert elapsed < 5
