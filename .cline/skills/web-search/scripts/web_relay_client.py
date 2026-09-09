"""Standard-library-only LAN client; intentionally independent of server packages."""
import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class ClientError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError("connection_failed", "Relay redirects are not allowed.")


def read_settings(root: Path) -> tuple[str, str]:
    try:
        settings = {}
        for line in (root / ".env").read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if separator:
                settings[key.strip()] = value.strip().strip("\"'")
        address = settings.get("WEB_RELAY_URL", "").rstrip("/")
        token = settings.get("WEB_RELAY_TOKEN", "")
        parsed = urlsplit(address)
        _ = parsed.port
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
            raise ValueError("invalid relay address")
        if not token or any(ord(c) < 32 or ord(c) > 126 for c in token):
            raise ValueError("invalid token")
        return address, token
    except (OSError, ValueError):
        raise ClientError("configuration_error", "Set WEB_RELAY_URL (HTTP origin) and WEB_RELAY_TOKEN in the explicit project root's .env.") from None


def request(root: Path, operation: str, value: str) -> dict:
    address, token = read_settings(root)
    payload = {"url" if operation == "fetch" else "query": value}
    req = Request(address + "/" + operation, data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        try:
            response = opener.open(req, timeout=35)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("oversize")
            result = json.loads(raw)
            if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
                raise ClientError("invalid_response", "Relay returned an invalid JSON response.")
            return result
    except TimeoutError:
        raise ClientError("timeout", "Relay request timed out.") from None
    except (URLError, OSError):
        raise ClientError("connection_failed", "Could not connect to the relay.") from None
    except (ValueError, UnicodeError):
        raise ClientError("invalid_response", "Relay returned an invalid JSON response.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("operation", choices=["fetch", "search"])
    parser.add_argument("value")
    args = parser.parse_args()
    try:
        result = request(args.project_root, args.operation, args.value)
    except ClientError as error:
        result = {"ok": False, "error": {"code": error.code, "message": error.message}}
    print(json.dumps(result, ensure_ascii=True))
    if not result["ok"]:
        print(result.get("error", {}).get("code", "request_failed"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
