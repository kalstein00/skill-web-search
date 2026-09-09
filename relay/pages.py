from email.message import Message

from bs4 import BeautifulSoup

from relay.errors import RelayError
from relay.web import WebResponse


def read_html(response: WebResponse) -> dict:
    if response.status in (401, 407):
        raise RelayError("unsupported", "This page requires authentication.")
    if response.status in (403, 429):
        raise RelayError("access_blocked", "The website blocked access.", 502)
    if response.status >= 400:
        raise RelayError("upstream_error", "The website returned an error.", 502)
    if response.headers.get("content-type", "").split(";")[0].lower() not in ("text/html", "application/xhtml+xml"):
        raise RelayError("unsupported", "Only public HTML pages are supported.")
    content_type = Message()
    content_type["content-type"] = response.headers.get("content-type", "")
    soup = BeautifulSoup(response.body, "html.parser", from_encoding=content_type.get_content_charset())
    if soup.select_one('input[type="password"]'):
        raise RelayError("unsupported", "This page requires login.")
    scripts = bool(soup.find("script"))
    for element in soup(["script", "style", "noscript", "template", "nav", "footer", "header"]):
        element.decompose()
    content = soup.find("main") or soup.find("article") or soup.body or soup
    text = content.get_text("\n", strip=True)
    if scripts and (not text or "enable javascript" in text.lower() or "javascript is required" in text.lower()):
        raise RelayError("unsupported", "This page requires JavaScript to read its body.")
    return {"ok": True, "url": response.url, "text": text[:20_000], "truncated": len(text) > 20_000}
