"""Public Internet transport. DNS validation occurs in the connection resolver."""
import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver

from relay.errors import RelayError

MAX_RESPONSE_BYTES = 4_000_000


def require_public(address: str) -> None:
    ip = ipaddress.ip_address(address)
    # Transition addresses can tunnel to an otherwise forbidden IPv4 endpoint.
    if not ip.is_global or ip.is_multicast or (isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo)):
        raise RelayError("address_policy", "Only public Internet addresses are allowed.")


def validate_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or "\\" in url or "%" in parsed.hostname:
            raise ValueError("invalid target")
        _ = parsed.port
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            # aiohttp may recognize inet_aton forms and skip its DNS resolver.
            if re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)(?:\.(?:0[xX][0-9a-fA-F]+|[0-9]+))*\.?", parsed.hostname):
                raise RelayError("address_policy", "Noncanonical numeric addresses are not supported.")
        else:
            require_public(parsed.hostname)
    except ValueError:
        raise RelayError("address_policy", "A public HTTP or HTTPS URL is required.") from None


class PublicResolver(AbstractResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        records = await asyncio.get_running_loop().getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
        for _, _, _, _, address in records:
            require_public(address[0])
        # These exact numeric addresses are handed to the connector; no second DNS lookup.
        return [{"hostname": host, "host": address[0], "port": port, "family": af,
                 "proto": proto, "flags": socket.AI_NUMERICHOST}
                for af, _, proto, _, address in records]

    async def close(self):
        pass


@dataclass
class WebResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes


async def fetch_public(url: str) -> WebResponse:
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False, force_close=True)
    async with aiohttp.ClientSession(connector=connector, trust_env=False, cookie_jar=aiohttp.DummyCookieJar(), timeout=aiohttp.ClientTimeout(total=30)) as session:
        for _ in range(11):
            validate_url(url)
            async with session.get(url, allow_redirects=False, headers={"User-Agent": "Mozilla/5.0 WebRelay/0.1"}) as response:
                if response.status in (301, 302, 303, 307, 308):
                    target = response.headers.get("Location")
                    if not target:
                        raise RelayError("upstream_error", "Invalid redirect.", 502)
                    url = urljoin(url, target)
                    continue
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise RelayError("unsupported", "Page exceeds the supported transfer size.")
                return WebResponse(str(response.url), response.status, {k.lower(): v for k, v in response.headers.items()}, bytes(body))
    raise RelayError("upstream_error", "Too many redirects.", 502)
