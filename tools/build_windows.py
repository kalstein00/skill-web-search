"""Build an onedir Windows x64 bundle with the pinned dedicated Chromium."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-cache", type=Path, default=ROOT / ".browsers")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("Build on Windows x64 with the locked development environment.")
    output = ROOT / "dist"
    work = ROOT / "build"
    # PyInstaller can replace its previous output. Both roots are fixed and checked.
    for directory in (output, work):
        if directory.resolve().parent != ROOT.resolve() or directory.is_symlink() or directory.is_junction():
            raise SystemExit("Build paths must stay inside the repository.")
        directory.mkdir(exist_ok=True)
    browser_cache = args.browser_cache.resolve()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
    with sync_playwright() as playwright:
        expected = Path(playwright.chromium.executable_path)
    if not expected.is_file() or not expected.resolve().is_relative_to(browser_cache):
        raise SystemExit("Install Chromium matching the installed Playwright into the selected browser cache.")
    chromium = browser_cache / expected.relative_to(browser_cache).parts[0]
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "web-relay", "--distpath", str(output), "--workpath", str(work / "pyinstaller"), "--specpath", str(work), "--paths", str(ROOT), "--collect-all", "playwright", "--collect-submodules", "uvicorn", str(ROOT / "tools/server_entry.py")]
    print("Building the Windows server; details in build/pyinstaller.log", flush=True)
    with (work / "pyinstaller.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise SystemExit("PyInstaller failed; inspect build/pyinstaller.log.")
    bundle = output / "web-relay"
    shutil.copytree(chromium, bundle / "browsers" / chromium.name, dirs_exist_ok=True)
    shutil.copy2(ROOT / "docs/windows-distribution.md", bundle / "START-HERE.md")
    shutil.copytree(ROOT / ".cline/skills/web-search", output / "client-skill/web-search", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = {"platform": platform.platform(), "python": platform.python_version(),
                "packages": {name: importlib.metadata.version(name) for name in ("fastapi", "aiohttp", "playwright", "pyinstaller")},
                "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
                "browsers": [chromium.name]}
    (bundle / "build-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Ready: {bundle / 'web-relay.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
