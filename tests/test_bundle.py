"""Opt-in acceptance checks against the Windows distributable."""
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

import psutil
import pytest
from test_relay import call_client

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.environ.get("WEB_RELAY_BUNDLE_TEST") != "1", reason="Build and explicitly verify the Windows bundle")


@contextlib.contextmanager
def running_bundle(project):
    executable = ROOT / "dist/web-relay/web-relay.exe"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(("PYTHON", "CLINE", "UV_", "PLAYWRIGHT"))}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(project / "wrong-browser-path")
    process = subprocess.Popen([str(executable), "--host", "127.0.0.1", "--port", str(port), "--token", "bundle-test-token", "--data-dir", str(project / "profiles")], cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    opener = build_opener(ProxyHandler({}))
    address = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(process.stderr.read().decode(errors="replace"))
            try:
                with opener.open(address + "/health", timeout=0.3) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("Bundle did not start")
        (project / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=bundle-test-token\n")
        yield process, address
    finally:
        if process.poll() is None:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
        stdout, stderr = process.communicate()
        assert b"bundle-test-token" not in stdout + stderr
        assert b"Python documentation" not in stdout + stderr


def test_packaged_server_requires_a_token():
    executable = ROOT / "dist/web-relay/web-relay.exe"
    result = subprocess.run([str(executable), "--host", "127.0.0.1", "--port", "8765"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
    assert result.returncode == 2
    assert "--token" in result.stderr


def test_build_rejects_a_stale_browser_cache(tmp_path):
    (tmp_path / "chromium-1").mkdir()
    result = subprocess.run([sys.executable, str(ROOT / "tools/build_windows.py"), "--browser-cache", str(tmp_path)], capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
    assert result.returncode != 0
    assert "matching the installed Playwright" in result.stderr


def test_bundle_uses_its_runtime_and_browser(tmp_path):
    bundle = (ROOT / "dist/web-relay").resolve()
    with running_bundle(tmp_path) as (process, _):
        server = psutil.Process(process.pid)
        loaded = [Path(item.path).resolve() for item in server.memory_maps() if Path(item.path).name.lower().startswith("python") and item.path.lower().endswith(".dll")]
        assert loaded
        assert all(path.is_relative_to(bundle) for path in loaded)
        _, denied = call_client(tmp_path, "fetch", "http://127.0.0.1/private")
        assert denied["error"]["code"] == "address_policy"
        _, body = call_client(tmp_path, "fetch", "https://www.google.com")
        assert body["ok"], body
        assert body["text"]
        browser_paths = set()
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(call_client, tmp_path, "search", "Python documentation")
            while not pending.done():
                for child in server.children(recursive=True):
                    try:
                        if child.name().lower() == "chrome.exe":
                            browser_paths.add(Path(child.exe()).resolve())
                    except psutil.NoSuchProcess:
                        pass
                time.sleep(0.02)
            _, search = pending.result()
        assert browser_paths
        assert all(path.is_relative_to(bundle / "browsers") for path in browser_paths)
        assert search["ok"] or search["error"]["code"] in ("captcha", "access_blocked", "upstream_error", "unsupported"), search
        assert not list((tmp_path / "profiles").glob("web-relay-request-*"))
        evidence = {"loaded_python_dlls": [str(path) for path in loaded], "browser_executables": [str(path) for path in browser_paths], "live_body_chars": len(body["text"]), "search": search, "clean_windows_machine": False}
        (ROOT / "build/bundle-validation.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence))


def open_request(address, operation="search", partial=False):
    from urllib.parse import urlsplit

    target = urlsplit(address)
    connection = socket.create_connection((target.hostname, target.port))
    body = b'{"query":"lifecycle verification"}'
    size = len(body) + 1 if partial else len(body)
    connection.sendall(f"POST /{operation} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer bundle-test-token\r\nContent-Length: {size}\r\nContent-Type: application/json\r\n\r\n".encode() + body)
    return connection


def test_bundle_busy_and_thirty_second_request_limit(tmp_path):
    with running_bundle(tmp_path) as (_, address):
        connection = open_request(address, partial=True)
        started = time.monotonic()
        try:
            time.sleep(0.2)
            _, busy = call_client(tmp_path, "fetch", "https://www.google.com")
            assert busy["error"]["code"] == "busy"
            connection.settimeout(34)
            response = b""
            while b'"code":"timeout"' not in response:
                chunk = connection.recv(65536)
                assert chunk
                response += chunk
            assert 29 <= time.monotonic() - started < 34
        finally:
            connection.close()
        _, recovered = call_client(tmp_path, "fetch", "http://127.0.0.1")
        assert recovered["error"]["code"] == "address_policy"


def test_bundle_force_exit_and_restart(tmp_path):
    with running_bundle(tmp_path) as (process, address):
        connection = open_request(address)
        parent = psutil.Process(process.pid)
        deadline = time.monotonic() + 10
        children = []
        try:
            while time.monotonic() < deadline:
                children = parent.children(recursive=True)
                if any(child.name().lower() == "chrome.exe" for child in children):
                    break
                time.sleep(0.005)
            assert any(child.name().lower() == "chrome.exe" for child in children)
            process.kill()
            process.wait(5)
            _, alive = psutil.wait_procs(children, timeout=5)
            assert not alive
            assert list((tmp_path / "profiles").glob("web-relay-request-*"))
        finally:
            connection.close()
    with running_bundle(tmp_path):
        assert not list((tmp_path / "profiles").glob("web-relay-request-*"))
        _, recovered = call_client(tmp_path, "fetch", "http://127.0.0.1")
        assert recovered["error"]["code"] == "address_policy"
