"""Subprocess acceptance harness; only the external website response is controlled."""
import argparse
import asyncio
import os
from pathlib import Path

import uvicorn

from relay.app import create_app
from relay.web import WebResponse
from relay.windows_job import bind_process_tree

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--port", type=int, required=True)
args = parser.parse_args()
bind_process_tree()
args.root.mkdir(exist_ok=True)
(args.root / "worker.pid").write_text(str(os.getpid()))


async def external_response(url, **kwargs):
    (args.root / "web-entered").touch()
    await asyncio.sleep(60)
    return WebResponse(url, 200, {"content-type": "text/html"}, b"<p>Delayed</p>")


uvicorn.run(create_app("test-token", fetch=external_response, data_root=args.root / "profiles"), host="127.0.0.1", port=args.port, access_log=False, log_level="critical")
