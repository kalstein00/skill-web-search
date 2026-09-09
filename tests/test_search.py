import os
import tempfile
from pathlib import Path

import pytest
from test_relay import call_client, running_server


def test_user_searches_with_browser(tmp_path):
    from relay.app import create_app
    from relay.web import WebResponse

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).resolve().parents[1] / ".browsers")

    async def external_response(url, **kwargs):
        html = b'<html><body><div><a href="https://docs.python.org/3/"><h3>Python documentation</h3></a><div class="VwiC3b">Official Python reference.</div></div></body></html>'
        return WebResponse(url, 200, {"content-type": "text/html"}, html)

    with running_server(create_app("test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        process, result = call_client(tmp_path, "search", "Python documentation")
    assert process.returncode == 0
    assert result == {"ok": True, "results": [{"title": "Python documentation", "url": "https://docs.python.org/3/", "snippet": "Official Python reference."}]}


@pytest.mark.parametrize("html,status,expected", [
    ("<p>Your search did not match any documents.</p>", 200, "empty"),
    ("<p>Our systems have detected unusual traffic</p>", 200, "captcha"),
    ("<p>Access denied</p>", 403, "access_blocked"),
    ("<p>An unknown Google layout</p>", 200, "upstream_error"),
    (''.join(f'<div><a href="https://example.org/{n}"><h3>Result {n}</h3></a><div class="VwiC3b">Summary {n}</div></div>' for n in range(7)), 200, "five"),
    ('<a href="https://example.org/one"><h3>Unusual traffic</h3></a><div><a href="https://example.org/two"><h3>Access denied</h3></a><div class="VwiC3b">Second summary</div></div>', 200, "adjacent"),
])
def test_search_outcomes_are_distinct(tmp_path, html, status, expected):
    from relay.app import create_app
    from relay.web import WebResponse

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).resolve().parents[1] / ".browsers")

    async def external_response(url, **kwargs):
        return WebResponse(url, status, {"content-type": "text/html"}, html.encode())

    with running_server(create_app("test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        process, result = call_client(tmp_path, "search", "test query")
    if expected == "empty":
        assert result == {"ok": True, "results": []}
    elif expected == "five":
        assert len(result["results"]) == 5
        assert result["results"][4] == {"title": "Result 4", "url": "https://example.org/4", "snippet": "Summary 4"}
    elif expected == "adjacent":
        assert result["results"][0]["snippet"] == ""
        assert result["results"][1]["snippet"] == "Second summary"
    else:
        assert process.returncode == 1
        assert result["error"]["code"] == expected


@pytest.mark.parametrize("scenario", ["redirect", "private_script", "private_redirect"])
def test_browser_redirects_and_subresources(tmp_path, scenario):
    from relay.app import create_app
    from relay.web import WebResponse

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).resolve().parents[1] / ".browsers")
    requested = []

    async def external_response(url, **kwargs):
        requested.append(url)
        if "google.com/search" in url:
            if scenario == "private_script":
                return WebResponse(url, 200, {"content-type": "text/html"}, b'<script src="http://127.0.0.1/private.js"></script>')
            location = "http://127.0.0.1/private" if scenario == "private_redirect" else "https://public.example/new/page"
            return WebResponse(url, 302, {"location": location}, b"")
        if url == "https://public.example/new/page":
            return WebResponse(url, 200, {"content-type": "text/html"}, b'<body><script src="results.js"></script></body>')
        if url == "https://public.example/new/results.js":
            return WebResponse(url, 200, {"content-type": "text/javascript"}, b'document.body.innerHTML = \'<a href="https://example.org"><h3>Redirected result</h3></a>\';')
        raise AssertionError("Unexpected external URL")

    with running_server(create_app("test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        _, result = call_client(tmp_path, "search", "test")
    if scenario == "redirect":
        assert result["results"][0]["title"] == "Redirected result"
        assert "https://public.example/new/results.js" in requested
    else:
        assert result["error"]["code"] == "address_policy"
        assert not any("127.0.0.1" in url for url in requested)


@pytest.mark.parametrize("blocked", [False, True])
def test_browser_profiles_removed_on_success_and_failure(tmp_path, monkeypatch, blocked):
    from relay.app import create_app
    from relay.web import WebResponse

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).resolve().parents[1] / ".browsers")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    observed = []

    async def external_response(url, **kwargs):
        observed.extend(tmp_path.rglob("web-relay-request-*"))
        html = b'<div class="g-recaptcha"></div>' if blocked else b'<a href="https://example.org"><h3>Example</h3></a>'
        return WebResponse(url, 200, {"content-type": "text/html"}, html)

    with running_server(create_app("test-token", fetch=external_response)) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        _, result = call_client(tmp_path, "search", "test")
    assert result["ok"] is not blocked
    assert observed
    assert not any(path.exists() for path in observed)


def test_missing_browser_returns_structured_error(tmp_path, monkeypatch):
    from relay.app import create_app

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "missing-browsers"))
    with running_server(create_app("test-token")) as address:
        (tmp_path / ".env").write_text(f"WEB_RELAY_URL={address}\nWEB_RELAY_TOKEN=test-token\n")
        _, result = call_client(tmp_path, "search", "test")
    assert result["error"]["code"] == "browser_error"
