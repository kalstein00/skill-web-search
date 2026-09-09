import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

import psutil
import pytest
from test_relay import call_client, running_server


def test_busy_is_immediate_and_next_request_recovers(tmp_path):
    from relay.app import create_app
    from relay.web import WebResponse

    entered = threading.Event()

    async def external_response(url, **kwargs):
        if url.endswith("slow"):
            entered.set()
            await asyncio.sleep(2)
        return WebResponse(url, 200, {"content-type": "text/html"}, b"<p>Available</p>")

    with running_server(create_app("test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        with ThreadPoolExecutor() as pool:
            first = pool.submit(call_client, tmp_path, "fetch", "https://example.org/slow")
            assert entered.wait(5)
            _, busy = call_client(tmp_path, "search", "test")
            assert busy["error"]["code"] == "busy"
            assert first.result()[1]["ok"]
        _, next_result = call_client(tmp_path, "fetch", "https://example.org/fast")
        assert next_result["text"] == "Available"


@pytest.mark.parametrize("operation", ["fetch", "search"])
@pytest.mark.parametrize("ending", ["timeout", "disconnect"])
def test_cancelled_web_work_cleans_up_and_recovers(tmp_path, operation, ending):
    from relay.app import create_app
    from relay.web import WebResponse

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).resolve().parents[1] / ".browsers")
    entered, cancelled = threading.Event(), threading.Event()
    profiles = tmp_path / "profiles"

    async def external_response(url, **kwargs):
        if not url.endswith("fast"):
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()
        return WebResponse(url, 200, {"content-type": "text/html"}, b"<p>Recovered</p>")

    with running_server(create_app("test-token", fetch=external_response, data_root=profiles, request_timeout=4 if ending == "timeout" else 15)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        if ending == "timeout":
            started = time.monotonic()
            _, result = call_client(tmp_path, operation, "test" if operation == "search" else "https://example.org/slow")
            assert result["error"]["code"] == "timeout"
            assert time.monotonic() - started < 8
        else:
            target = urlsplit(address)
            body = json.dumps({"query": "test"} if operation == "search" else {"url": "https://example.org/slow"}).encode()
            connection = socket.create_connection((target.hostname, target.port))
            connection.sendall(f"POST /{operation} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer test-token\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
            assert entered.wait(5)
            connection.close()
        assert cancelled.wait(5)
        deadline = time.monotonic() + 5
        while list(profiles.glob("web-relay-request-*")) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not list(profiles.glob("web-relay-request-*"))
        _, recovered = call_client(tmp_path, "fetch", "https://example.org/fast")
        assert recovered["text"] == "Recovered"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process-job acceptance")
def test_forced_exit_kills_browser_tree_and_restart_cleans_profiles(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root), PLAYWRIGHT_BROWSERS_PATH=str(root / ".browsers"))
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = [sys.executable, str(root / "tests/lifecycle_worker.py"), "--root", str(tmp_path), "--port", str(port)]
    opener = build_opener(ProxyHandler({}))

    def start():
        process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(process.stderr.read().decode())
            try:
                with opener.open(f"http://127.0.0.1:{port}/health", timeout=0.3) as response:
                    if response.status == 200:
                        return process, psutil.Process(int((tmp_path / "worker.pid").read_text()))
            except OSError:
                time.sleep(0.05)
        process.kill()
        raise AssertionError("Worker did not start")

    process, worker = start()
    connection = socket.create_connection(("127.0.0.1", port))
    try:
        body = b'{"query":"process cleanup test"}'
        connection.sendall(f"POST /search HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer test-token\r\nContent-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n".encode() + body)
        deadline = time.monotonic() + 10
        while not (tmp_path / "web-entered").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "web-entered").exists()
        children = worker.children(recursive=True)
        assert any(child.name().lower() == "chrome.exe" for child in children)
        worker.kill()
        worker.wait(5)
        process.wait(5)
        _, alive = psutil.wait_procs(children, timeout=5)
        assert not alive
        assert list((tmp_path / "profiles").glob("web-relay-request-*"))
    finally:
        connection.close()
        if worker.is_running():
            worker.kill()
        process.wait(5)
        process.stderr.close()
    restarted, new_worker = start()
    try:
        assert not list((tmp_path / "profiles").glob("web-relay-request-*"))
    finally:
        new_worker.kill()
        restarted.wait(5)
        restarted.stderr.close()


@pytest.mark.parametrize("operation", ["fetch", "search"])
def test_default_thirty_second_deadline_and_content_free_logs(tmp_path, caplog, operation):
    from relay.app import create_app
    from relay.web import WebResponse

    async def external_response(url, **kwargs):
        await asyncio.sleep(60)
        return WebResponse(url, 200, {"content-type": "text/html"}, b"never returned")

    caplog.set_level("INFO", logger="web_relay")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).resolve().parents[1] / ".browsers")
    with running_server(create_app("private-test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=private-test-token\n")
        started = time.monotonic()
        _, result = call_client(tmp_path, operation, "private-request-marker" if operation == "search" else "https://example.org/private-request-marker")
        elapsed = time.monotonic() - started
    assert result["error"]["code"] == "timeout"
    assert 29 <= elapsed < 34
    assert "outcome=timeout" in caplog.text
    assert "private-request-marker" not in caplog.text
    assert "private-test-token" not in caplog.text


def test_timeout_during_browser_startup_leaves_no_children(tmp_path):
    from relay.app import create_app

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).resolve().parents[1] / ".browsers")
    process = psutil.Process()
    before = {child.pid for child in process.children(recursive=True)}
    profiles = tmp_path / "profiles"
    with running_server(create_app("test-token", data_root=profiles, request_timeout=0.05)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        _, result = call_client(tmp_path, "search", "startup cancellation")
        assert result["error"]["code"] == "timeout"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            remaining = [child for child in process.children(recursive=True) if child.pid not in before]
            if not remaining:
                break
            time.sleep(0.05)
        assert not remaining
        assert not list(profiles.glob("web-relay-request-*"))
