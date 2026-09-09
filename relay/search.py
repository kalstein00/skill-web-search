import asyncio
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import Error as BrowserError
from playwright.async_api import Route, async_playwright

from relay.errors import RelayError
from relay.web import WebResponse, validate_url


class WebFetch(Protocol):
    async def __call__(self, url: str, *, headers: dict[str, str] | None = None, follow_redirects: bool = True) -> WebResponse: ...


@asynccontextmanager
async def browser_context(profile: str):
    # Cancellation during Playwright startup otherwise leaks its pipe transport.
    # Finish acquiring the handle, then close it before acknowledging cancellation.
    starting = asyncio.create_task(async_playwright().start())
    launching = None
    try:
        playwright = await asyncio.shield(starting)
        launching = asyncio.create_task(playwright.chromium.launch_persistent_context(
            profile, channel="chromium", headless=True, service_workers="block", accept_downloads=False,
            proxy={"server": "http://127.0.0.1:9"}, timeout=5000,
            args=["--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
        ))
        context = await asyncio.shield(launching)
        yield context
    finally:
        try:
            if launching is not None:
                contexts = await asyncio.gather(launching, return_exceptions=True)
                if not isinstance(contexts[0], BaseException):
                    await contexts[0].close()
        finally:
            drivers = await asyncio.gather(starting, return_exceptions=True)
            if not isinstance(drivers[0], BaseException):
                await drivers[0].stop()


def search_results(html: str, status: int = 200, url: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    has_results = any(heading.find_parent("a", href=True) for heading in soup.find_all("h3"))
    if "/sorry/" in url or soup.select_one('iframe[src*="recaptcha"], .g-recaptcha, #captcha-form') or (not has_results and "unusual traffic" in text):
        raise RelayError("captcha", "Google requires CAPTCHA verification.", 502)
    if status in (403, 429) or (not has_results and "access denied" in text):
        raise RelayError("access_blocked", "Google blocked the search.", 502)
    if status >= 400:
        raise RelayError("upstream_error", "Google returned an error.", 502)
    results = []
    seen = set()
    for heading in soup.find_all("h3"):
        link = heading.find_parent("a", href=True)
        if link is None:
            continue
        target = str(link["href"])
        if target.startswith("/url?"):
            params = parse_qs(urlsplit(target).query)
            target = params.get("q", params.get("url", [""]))[0]
        try:
            validate_url(target)
        except RelayError:
            continue
        if target in seen:
            continue
        seen.add(target)
        snippet = ""
        for ancestor in heading.parents:
            if ancestor.name in ("body", "html", "[document]") or len(ancestor.find_all("h3")) > 1:
                break
            found = ancestor.select_one(".VwiC3b, .aCOpRe, .IsZvec, .yXK7lf")
            if found:
                snippet = found.get_text(" ", strip=True)
                break
        results.append({"title": heading.get_text(" ", strip=True), "url": target, "snippet": snippet})
        if len(results) == 5:
            break
    if not results and not any(marker in text for marker in ("did not match any documents", "no results found", "검색결과가 없습니다")):
        raise RelayError("upstream_error", "Google returned an unrecognized search page.", 502)
    return {"ok": True, "results": results}


async def search_google(query: str, fetch: WebFetch, data_root: Path | None = None) -> dict:
    # An explicit profile permits deterministic removal after success and failure.
    with tempfile.TemporaryDirectory(prefix="web-relay-request-", dir=data_root) as profile:
        async with browser_context(profile) as context:
            page = context.pages[0]
            document: list[WebResponse] = []
            failures: list[RelayError] = []
            navigations: list[str] = []
            redirect_count = 0
            resource_tasks: set[asyncio.Task] = set()

            async def handle_route(route: Route):
                try:
                    request = route.request
                    if request.method != "GET" or request.resource_type in ("image", "media", "font"):
                        await route.abort()
                        return
                    validate_url(request.url)
                    outgoing = {k: v for k, v in (await request.all_headers()).items() if k in ("user-agent", "accept", "accept-language", "cookie")}
                    response = await fetch(request.url, headers=outgoing, follow_redirects=False)
                    if response.status in (301, 302, 303, 307, 308):
                        target = urljoin(request.url, response.headers.get("location", ""))
                        validate_url(target)
                        if request.is_navigation_request() and request.frame == page.main_frame:
                            # Playwright only routes the first request of a native redirect.
                            # Start a fresh navigation so every target is routed and its
                            # document origin/base URL remains the actual destination.
                            navigations.append(target)
                            await route.fulfill(status=200, content_type="text/html", body="")
                            return
                        raise RelayError("unsupported", "Redirected search subresources are not supported.")
                    if request.is_navigation_request() and request.frame == page.main_frame:
                        document.append(response)
                    headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding", "connection")}
                    await route.fulfill(status=response.status, headers=headers, body=response.body)
                except RelayError as error:
                    failures.append(error)
                    await route.abort()
                except (aiohttp.ClientError, OSError, BrowserError, TimeoutError):
                    failures.append(RelayError("connection_failed", "A search resource could not be loaded.", 502))
                    await route.abort()

            async def route_request(route: Route):
                task = asyncio.current_task()
                if task is not None:
                    resource_tasks.add(task)
                try:
                    await handle_route(route)
                finally:
                    if task is not None:
                        resource_tasks.discard(task)

            try:
                await context.route("**/*", route_request)
                await context.route_web_socket("**/*", lambda ws: ws.close())
                await page.goto("https://www.google.com/search?" + urlencode({"q": query, "hl": "en", "num": 5}), wait_until="domcontentloaded", timeout=0)
                for _ in range(100):
                    if failures:
                        raise failures[0]
                    if navigations:
                        redirect_count += 1
                        if redirect_count > 10:
                            raise RelayError("upstream_error", "Too many search redirects.", 502)
                        await page.goto(navigations.pop(0), wait_until="domcontentloaded", timeout=0)
                        continue
                    response = document[-1] if document else None
                    try:
                        return search_results(await page.content(), response.status if response else 200, response.url if response else page.url)
                    except RelayError as error:
                        if error.code != "upstream_error" or "unrecognized" not in error.message:
                            raise
                    except BrowserError:
                        pass  # JavaScript can replace the document during inspection.
                    await asyncio.sleep(0.1)
                if failures:
                    raise failures[0]
                response = document[-1] if document else None
                return search_results(await page.content(), response.status if response else 200, response.url if response else page.url)
            except BrowserError:
                if failures:
                    raise failures[0]
                raise RelayError("browser_error", "The search browser could not complete the request.", 502) from None
            finally:
                pending = list(resource_tasks)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
