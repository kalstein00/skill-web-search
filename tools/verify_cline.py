"""Exercise installed Cline with controlled web responses; never selects a model."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_relay import running_server

from relay.app import create_app
from relay.web import WebResponse


def main():
    project = ROOT / ".scratch/cline-verification/project"
    project.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / ".cline/skills/web-search", project / ".cline/skills/web-search", dirs_exist_ok=True)
    requests = []
    wire_calls = []

    async def external_response(url, **kwargs):
        requests.append("search" if "google.com/search" in url else "fetch")
        html = '<html><body><div><a href="https://docs.python.org/3/"><h3>Python documentation</h3></a><div class="VwiC3b">Official Python reference.</div></div></body></html>' if "google.com/search" in url else '<article><h1>Python documentation</h1><p>This controlled acceptance fixture confirms that the LAN relay returned a selected source body.</p></article>'
        return WebResponse(url, 200, {"content-type": "text/html"}, html.encode())

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / ".browsers")
    uv = shutil.which("uv") or str(Path(os.environ["APPDATA"]) / "Python/Python312/Scripts/uv.exe")
    # Cline's Windows terminal can have a different view of user Scripts paths.
    # Stage the already installed executable with the acceptance workspace.
    runtime = project.parent / "runtime"
    runtime.mkdir(exist_ok=True)
    staged_uv = runtime / Path(uv).name
    shutil.copy2(uv, staged_uv)
    uv = str(staged_uv)
    env = dict(os.environ, PATH=str(Path(uv).parent) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    cline = shutil.which("cline.cmd") or shutil.which("cline")
    if not cline:
        raise SystemExit("Installed Cline CLI was not found.")
    skill_directory = (project / ".cline/skills/web-search").as_posix()
    prompt = f'Use the web-search skill to search for Python documentation, choose one returned source, fetch its body, and answer briefly in Korean with the source URL. This is a controlled acceptance test, so identify fixture content as test data. The project root is {project.as_posix()}. The skill directory is {skill_directory}; its client is {skill_directory}/scripts/web_relay_client.py. The installed Python is {Path(sys.executable).as_posix()} and installed uv is {Path(uv).as_posix()}. Use these exact forward-slash absolute paths; your shell may not inherit PATH changes. You may verify executable and skill file existence. Keep your existing model/provider settings. Do not read or print the .env file or its token; the client reads it. Do not edit files or use another web tool.'
    app = create_app("cline-acceptance-token", fetch=external_response)

    @app.middleware("http")
    async def observe_wire(request, call_next):
        if request.method == "POST":
            wire_calls.append({"path": request.url.path, "payload": await request.json()})
        return await call_next(request)

    with running_server(app) as address:
        (project / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=cline-acceptance-token\n")
        completed = subprocess.run([cline, "--json", "--timeout", "120", "--cwd", str(project), prompt], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150, check=False)
    # Test-only token is still redacted before preserving tool output.
    report = (completed.stdout + "\n" + completed.stderr).replace("cline-acceptance-token", "[redacted]")
    (project.parent / "cline-output.txt").write_text(report, encoding="utf-8")
    result = {}
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "run_result":
            result = {key: event.get(key) for key in ("finishReason", "text", "model", "durationMs")}
    result.update({"cline_exit": completed.returncode, "observed_web_operations": requests, "wire_calls": wire_calls, "model_overrides": False, "controlled_responses": True})
    (project.parent / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    paths = [call["path"] for call in wire_calls]
    return 0 if completed.returncode == 0 and paths == ["/search", "/fetch"] and wire_calls[1]["payload"] == {"url": "https://docs.python.org/3/"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
