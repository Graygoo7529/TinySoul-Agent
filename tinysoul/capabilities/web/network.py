"""Bounded public-HTTPS retrieval owned by the Web capability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from lxml import html

from .errors import WebProcessingError


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ALLOWED_CONTENT_TYPES = frozenset(
    {"text/html", "application/xhtml+xml", "text/plain"}
)


@dataclass(frozen=True)
class FetchedPage:
    """One bounded external page after redirects and link normalization."""

    final_url: str
    html: str
    content_type: str


AddressResolver = Callable[..., object]


def fetch_public_page(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: int,
    max_redirects: int,
    user_agent: str,
) -> FetchedPage:
    """Fetch one public HTTPS page with bounded body and explicit redirects."""

    current = validate_public_https_url(url)
    headers = {
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
        "User-Agent": user_agent,
    }
    try:
        with httpx.Client(
            timeout=float(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        ) as client:
            for redirect_count in range(max_redirects + 1):
                validate_public_https_url(current)
                with client.stream("GET", current) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location", "")
                        if not location:
                            raise WebProcessingError(
                                "Web redirect did not provide a destination",
                                reason="invalid_redirect",
                            )
                        if redirect_count >= max_redirects:
                            raise WebProcessingError(
                                "Web redirect limit was exceeded",
                                reason="redirect_limit_exceeded",
                            )
                        current = validate_public_https_url(
                            urljoin(str(response.url), location)
                        )
                        continue
                    if response.status_code < 200 or response.status_code >= 300:
                        raise WebProcessingError(
                            "Web page returned an unsuccessful HTTP status",
                            reason="http_status_error",
                            payload={"status_code": response.status_code},
                        )
                    content_type = _content_type(response.headers.get("content-type", ""))
                    if content_type not in _ALLOWED_CONTENT_TYPES:
                        raise WebProcessingError(
                            "Web page content type is not supported",
                            reason="unsupported_content_type",
                            payload={"content_type": content_type or "unknown"},
                        )
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            declared_size = int(content_length)
                        except ValueError:
                            declared_size = 0
                        if declared_size > max_bytes:
                            raise WebProcessingError(
                                "Web page exceeds the configured byte limit",
                                reason="source_bytes_limit_exceeded",
                            )
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise WebProcessingError(
                                "Web page exceeds the configured byte limit",
                                reason="source_bytes_limit_exceeded",
                            )
                    final_url = validate_public_https_url(str(response.url))
                    encoding = response.encoding or "utf-8"
                    text = bytes(body).decode(encoding, errors="replace")
                    normalized = normalize_html_links(text, base_url=final_url)
                    return FetchedPage(
                        final_url=final_url,
                        html=normalized,
                        content_type=content_type,
                    )
    except WebProcessingError:
        raise
    except (httpx.HTTPError, OSError, UnicodeError) as exc:
        raise WebProcessingError(
            "Web page could not be retrieved",
            reason="network_request_failed",
            payload={"error_type": type(exc).__name__},
        ) from exc
    raise WebProcessingError(
        "Web page retrieval ended without a result",
        reason="network_request_failed",
    )


def validate_public_https_url(
    value: str,
    *,
    resolver: AddressResolver = socket.getaddrinfo,
) -> str:
    """Return a canonical URL only when every resolved address is public."""

    if not isinstance(value, str) or not value:
        raise WebProcessingError(
            "Web URL must be a non-empty string",
            reason="invalid_url",
        )
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise WebProcessingError("Web URL is invalid", reason="invalid_url") from exc
    if parsed.scheme.lower() != "https":
        raise WebProcessingError(
            "Web fetch only accepts HTTPS URLs",
            reason="unsupported_url_scheme",
        )
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise WebProcessingError("Web URL authority is invalid", reason="invalid_url")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise WebProcessingError(
            "Web URL must resolve to a public host",
            reason="private_network_target",
        )
    effective_port = port or 443
    try:
        resolved = resolver(host, effective_port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebProcessingError(
            "Web host could not be resolved",
            reason="dns_resolution_failed",
        ) from exc
    if not isinstance(resolved, list) or not resolved:
        raise WebProcessingError(
            "Web host did not resolve to an address",
            reason="dns_resolution_failed",
        )
    for item in resolved:
        if not isinstance(item, tuple) or len(item) < 5:
            raise WebProcessingError(
                "Web host resolution returned an invalid address",
                reason="dns_resolution_failed",
            )
        sockaddr = item[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            raise WebProcessingError(
                "Web host resolution returned an invalid address",
                reason="dns_resolution_failed",
            )
        address = str(sockaddr[0]).split("%", 1)[0]
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise WebProcessingError(
                "Web host resolution returned an invalid address",
                reason="dns_resolution_failed",
            ) from exc
        if not parsed_address.is_global:
            raise WebProcessingError(
                "Web URL must resolve only to public addresses",
                reason="private_network_target",
            )
    netloc = host
    if ":" in host:
        netloc = f"[{host}]"
    if port is not None and port != 443:
        netloc = f"{netloc}:{port}"
    return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))


def normalize_html_links(value: str, *, base_url: str) -> str:
    """Make page links absolute before a local extractor sees the HTML."""

    try:
        document = html.fromstring(value, base_url=base_url)
        document.make_links_absolute(base_url, resolve_base_href=True)
        return html.tostring(document, encoding="unicode", method="html")
    # lxml does not expose a stable cross-version parser exception hierarchy.
    except Exception as exc:
        raise WebProcessingError(
            "Web page HTML could not be normalized",
            reason="invalid_html",
        ) from exc


def _content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()
