"""Opt-in live evidence; never substitute fixtures for these checks."""
import os
from pathlib import Path

import pytest
from test_relay import call_client, running_server

pytestmark = pytest.mark.skipif(os.environ.get("WEB_RELAY_LIVE") != "1", reason="Explicit live verification only")


def test_live_google_search_and_body(tmp_path):
    from relay.app import create_app

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).resolve().parents[1] / ".browsers")
    with running_server(create_app("live-verification-token")) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=live-verification-token\n")
        _, search = call_client(tmp_path, "search", "Python documentation")
        assert search["ok"], search
        assert search["results"]
        print("Live results:", search["results"])
        _, body = call_client(tmp_path, "fetch", search["results"][0]["url"])
        assert body["ok"], body
        assert body["text"]
        print("Live body:", {"url": body["url"], "characters": len(body["text"]), "truncated": body["truncated"]})
