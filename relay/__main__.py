import argparse

import uvicorn

from relay.app import create_app


def main():
    parser = argparse.ArgumentParser(description="Windows web relay")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    try:
        app = create_app(args.token)
    except ValueError:
        parser.error("A nonempty printable ASCII token is required.")
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
