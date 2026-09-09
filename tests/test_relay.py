"""Acceptance seam: CLI process -> HTTP server -> controlled external web."""
import contextlib
import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import uvicorn

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def running_server(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()


def call_client(project, *args):
    process = subprocess.run(
        [sys.executable, str(ROOT / "client.py"), "--project-root", str(project), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=40, check=False,
    )
    return process, json.loads(process.stdout)


def test_user_reads_public_html(tmp_path):
    from relay.app import create_app
    from relay.web import WebResponse

    async def external_response(url):
        return WebResponse(url, 200, {"content-type": "text/html"}, b"<html><article><h1>Reference</h1><p>Verified content.</p></article></html>")

    with running_server(create_app("test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        process, result = call_client(tmp_path, "fetch", "https://example.org/reference")
    assert process.returncode == 0
    assert result == {"ok": True, "url": "https://example.org/reference", "text": "Reference\nVerified content.", "truncated": False}


@pytest.mark.parametrize("html,content_type,status,expected", [
    (b"<p>" + b"a" * 20000 + b"</p>", "text/html", 200, False),
    (b"<p>" + b"a" * 20001 + b"</p>", "text/html", 200, True),
    (b"%PDF-1.7", "application/pdf", 200, "unsupported"),
    (b'<input type="password">', "text/html", 200, "unsupported"),
    (b'<script>load()</script><p>Enable JavaScript</p>', "text/html", 200, "unsupported"),
    (b"blocked", "text/html", 403, "access_blocked"),
])
def test_body_boundaries_and_failures(tmp_path, html, content_type, status, expected):
    from relay.app import create_app
    from relay.web import WebResponse

    async def external_response(url):
        return WebResponse(url, status, {"content-type": content_type}, html)

    with running_server(create_app("test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        process, result = call_client(tmp_path, "fetch", "https://example.org/reference")
    if isinstance(expected, bool):
        assert process.returncode == 0
        assert len(result["text"]) == 20000
        assert result["truncated"] is expected
    else:
        assert process.returncode == 1
        assert result["error"]["code"] == expected
        assert expected in process.stderr


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "http://10.0.0.1/", "http://169.254.169.254/", "http://localhost/", "http://2130706433/", "http://0x7f000001/", "file:///etc/passwd"])
def test_private_targets_are_denied(tmp_path, url):
    from relay.app import create_app

    with running_server(create_app("test-token")) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        _, result = call_client(tmp_path, "fetch", url)
    assert result["error"]["code"] == "address_policy"


def test_configuration_and_authentication_are_distinct(tmp_path):
    from relay.app import create_app

    _, missing = call_client(tmp_path, "fetch", "https://example.org")
    assert missing["error"]["code"] == "configuration_error"
    with running_server(create_app("test-token")) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=wrong\n")
        _, invalid = call_client(tmp_path, "fetch", "https://example.org")
    assert invalid["error"]["code"] == "authentication_failed"


def test_invalid_port_is_configuration_error(tmp_path):
    (tmp_path / ".env").write_text("WEB_RELAY_URL=http://127.0.0.1:abc\nWEB_RELAY_TOKEN=test-token\n")
    _, result = call_client(tmp_path, "fetch", "https://example.org")
    assert result["error"]["code"] == "configuration_error"


def test_http_charset_is_preserved(tmp_path):
    from relay.app import create_app
    from relay.web import WebResponse

    async def external_response(url):
        return WebResponse(url, 200, {"content-type": "text/html; charset=euc-kr"}, "<p>공개 정보</p>".encode("euc-kr"))

    with running_server(create_app("test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        _, result = call_client(tmp_path, "fetch", "https://example.org")
    assert result["text"] == "공개 정보"


@pytest.mark.parametrize("scenario", ["redirect", "private_dns", "mixed_dns", "rebind"])
def test_real_transport_enforces_address_policy(tmp_path, monkeypatch, scenario):
    """Only DNS and socket network boundaries are substituted; transport stays real."""
    import asyncio

    from relay.app import create_app

    class Origin(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302 if scenario == "redirect" else 200)
            self.send_header("Content-Type", "text/html")
            if scenario == "redirect":
                self.send_header("Location", "http://127.0.0.1/private")
            self.end_headers()
            self.wfile.write(b"<p>Public origin</p>")

        def log_message(self, *args):
            pass

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    worker = threading.Thread(target=origin.serve_forever, daemon=True)
    worker.start()
    real_dns = socket.getaddrinfo
    loop_class = asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.SelectorEventLoop
    real_connect = loop_class.sock_connect
    lookups, connections = [], []

    def dns(host, port, *args, **kwargs):
        if host != "public.example":
            return real_dns(host, port, *args, **kwargs)
        lookups.append(host)
        addresses = ["93.184.216.34"]
        if scenario == "private_dns" or (scenario == "rebind" and len(lookups) > 1):
            addresses = ["127.0.0.1"]
        elif scenario == "mixed_dns":
            addresses.append("127.0.0.1")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port)) for ip in addresses]

    async def connect(loop, sock, address):
        if address[0] == "93.184.216.34":
            connections.append(address[0])
            return await real_connect(loop, sock, origin.server_address)
        return await real_connect(loop, sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(loop_class, "sock_connect", connect)
    try:
        with running_server(create_app("test-token")) as address:
            (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
            _, result = call_client(tmp_path, "fetch", "http://public.example/reference")
        if scenario == "rebind":
            assert result["text"] == "Public origin"
            assert connections == ["93.184.216.34"]
            assert len(lookups) == 1
        else:
            assert result["error"]["code"] == "address_policy"
            assert connections == (["93.184.216.34"] if scenario == "redirect" else [])
    finally:
        origin.shutdown()
        origin.server_close()
        worker.join(5)
