import asyncio
import secrets

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from playwright.async_api import Error as BrowserError

from relay.errors import RelayError
from relay.pages import read_html
from relay.search import WebFetch
from relay.web import fetch_public, validate_url


def create_app(token: str, *, fetch: WebFetch = fetch_public) -> FastAPI:
    if not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("A nonempty printable ASCII token is required.")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/fetch")
    @app.post("/search")
    async def web_request(request: Request):
        try:
            if not secrets.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + token).encode()):
                raise RelayError("authentication_failed", "Invalid shared token.", 401)
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 16_384:
                    raise RelayError("invalid_request", "Request is too large.")
            import json
            field = "query" if request.url.path == "/search" else "url"
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict) or set(payload) != {field} or not isinstance(payload[field], str) or not payload[field].strip():
                    raise ValueError()
            except (ValueError, KeyError):
                raise RelayError("invalid_request", "Expected a nonempty query or URL request.") from None
            async with asyncio.timeout(30):
                if field == "query":
                    from relay.search import search_google
                    return await search_google(payload[field], fetch)
                validate_url(payload["url"])
                return read_html(await fetch(payload["url"]))
        except RelayError as failure:
            return JSONResponse(failure.envelope(), status_code=failure.status)
        except TimeoutError:
            error = RelayError("timeout", "Web request timed out.", 504)
            return JSONResponse(error.envelope(), status_code=error.status)
        except BrowserError:
            error = RelayError("browser_error", "The search browser could not start or complete the request.", 502)
            return JSONResponse(error.envelope(), status_code=error.status)
        except (aiohttp.ClientError, OSError):
            error = RelayError("connection_failed", "Could not reach the website.", 502)
            return JSONResponse(error.envelope(), status_code=error.status)

    return app
