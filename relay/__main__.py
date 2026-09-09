import argparse
import hashlib
import logging
import tempfile
from pathlib import Path

import uvicorn

from relay.app import create_app
from relay.windows_job import bind_process_tree


def main():
    parser = argparse.ArgumentParser(description="Windows web relay")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--data-dir", type=Path, help="Owned browser temporary directory; one server per directory")
    args = parser.parse_args()
    try:
        bind_process_tree()
        server_key = hashlib.sha256(f"{args.host}:{args.port}".encode()).hexdigest()[:16]
        data_root = args.data_dir or Path(tempfile.gettempdir()) / "web-search-relay" / server_key
        app = create_app(args.token, data_root=data_root)
    except ValueError:
        parser.error("A nonempty printable ASCII token is required.")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
