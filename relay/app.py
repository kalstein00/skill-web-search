import asyncio
import json
import logging
import secrets
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from playwright.async_api import Error as BrowserError
from playwright.async_api import TimeoutError as BrowserTimeoutError
from starlette.requests import ClientDisconnect

from relay.errors import RelayError
from relay.pages import read_html
from relay.runtime import RuntimeDirectory
from relay.search import WebFetch, search_google
from relay.web import fetch_public, validate_url

logger = logging.getLogger("web_relay")


async def read_payload(request: Request) -> tuple[str, str]:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16_384:
            raise RelayError("invalid_request", "Request is too large.")
    field = "query" if request.url.path == "/search" else "url"
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {field} or not isinstance(payload[field], str) or not payload[field].strip():
            raise ValueError()
    except (ValueError, KeyError):
        raise RelayError("invalid_request", "Expected a nonempty query or URL request.") from None
    return field, payload[field]


async def disconnected(request: Request):
    # Body is fully consumed before this task starts; no competing ASGI receiver.
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            return


def create_app(token: str, *, fetch: WebFetch = fetch_public, data_root: Path | None = None, request_timeout: float = 30) -> FastAPI:
    if not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("A nonempty printable ASCII token is required.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if data_root is None:
            with tempfile.TemporaryDirectory(prefix="web-relay-server-") as folder, RuntimeDirectory(Path(folder)) as runtime:
                app.state.data_root = runtime.path
                yield
        else:
            with RuntimeDirectory(data_root) as runtime:
                app.state.data_root = runtime.path
                yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    busy = False

    @app.get("/health")
    async def health():
        return {"ok": True}

    async def perform(field: str, value: str) -> dict:
        if field == "query":
            return await search_google(value, fetch, app.state.data_root)
        validate_url(value)
        return read_html(await fetch(value))

    async def execute(request: Request) -> dict:
        nonlocal busy
        if not secrets.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + token).encode()):
            raise RelayError("authentication_failed", "Invalid shared token.", 401)
        if busy:
            raise RelayError("busy", "The relay is processing another request.", 409)
        busy = True
        tasks: list[asyncio.Task] = []
        try:
            async with asyncio.timeout(request_timeout):
                field, value = await read_payload(request)
                operation = asyncio.create_task(perform(field, value))
                disconnect = asyncio.create_task(disconnected(request))
                tasks = [operation, disconnect]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if operation in done:
                    return await operation
                raise RelayError("client_disconnected", "Client disconnected.", 499)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            busy = False

    @app.post("/fetch")
    @app.post("/search")
    async def web_request(request: Request):
        started = time.monotonic()
        try:
            result = await execute(request)
        except RelayError as failure:
            error = failure
        except (TimeoutError, BrowserTimeoutError):
            error = RelayError("timeout", "Web request timed out.", 504)
        except ClientDisconnect:
            error = RelayError("client_disconnected", "Client disconnected.", 499)
        except BrowserError:
            error = RelayError("browser_error", "The search browser could not start or complete the request.", 502)
        except (aiohttp.ClientError, OSError):
            error = RelayError("connection_failed", "Could not reach the website.", 502)
        else:
            logger.info("request outcome=success duration_ms=%d", int((time.monotonic() - started) * 1000))
            return result
        logger.info("request outcome=%s duration_ms=%d", error.code, int((time.monotonic() - started) * 1000))
        return JSONResponse(error.envelope(), status_code=error.status)

    return app
