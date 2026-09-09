import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from test_relay import ROOT, running_server


def test_skill_client_runs_without_project_sync_or_downloads(tmp_path):
    from relay.app import create_app
    from relay.web import WebResponse

    async def external_response(url, **kwargs):
        return WebResponse(url, 200, {"content-type": "text/html"}, b"<p>Offline client works</p>")

    uv = shutil.which("uv") or str(Path(os.environ["APPDATA"]) / "Python/Python312/Scripts/uv.exe")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="must-not-sync"\nversion="0.0.1"\ndependencies=["package-that-must-never-be-downloaded"]\n')
    with running_server(create_app("test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        env = dict(os.environ, UV_CACHE_DIR=str(tmp_path / "empty-cache"), UV_PYTHON_INSTALL_DIR=str(tmp_path / "no-python"), UV_DEFAULT_INDEX="http://127.0.0.1:1/forbidden")
        completed = subprocess.run([uv, "run", "--offline", "--no-project", "--no-sync", "--no-python-downloads", "--no-managed-python", "--python", sys.executable, str(ROOT / ".cline/skills/web-search/scripts/web_relay_client.py"), "--project-root", str(tmp_path), "fetch", "https://example.org"], cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["text"] == "Offline client works"
    assert not (tmp_path / ".venv").exists()
    assert not (tmp_path / "no-python").exists()


def test_explicit_project_root_ignores_parent_and_environment(tmp_path, monkeypatch):
    from test_relay import call_client

    (tmp_path / ".env").write_text("WEB_RELAY_URL=http://127.0.0.1:12345\nWEB_RELAY_TOKEN=parent-token\n")
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.setenv("WEB_RELAY_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("WEB_RELAY_TOKEN", "environment-token")
    _, result = call_client(child, "fetch", "https://example.org")
    assert result["error"]["code"] == "configuration_error"


def test_failure_is_not_retried_and_only_target_is_sent(tmp_path):
    from test_relay import call_client

    from relay.app import create_app
    from relay.web import WebResponse

    async def external_response(url, **kwargs):
        return WebResponse(url, 403, {"content-type": "text/html"}, b"blocked")

    app = create_app("test-token", fetch=external_response)
    received = []

    @app.middleware("http")
    async def observe_wire(request, call_next):
        if request.method == "POST":
            received.append(await request.json())
        return await call_next(request)

    (tmp_path / "private-conversation.txt").write_text("must never be sent")
    with running_server(app) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        process, result = call_client(tmp_path, "fetch", "https://example.org")
    assert result["error"]["code"] == "access_blocked"
    assert received == [{"url": "https://example.org"}]
    assert process.returncode == 1
    assert process.stderr.strip() == "access_blocked"
