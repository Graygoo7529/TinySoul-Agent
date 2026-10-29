"""Bounded public-HTTPS retrieval owned by the Web capability."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from lxml import etree, html

from tinysoul.infra.http import httpx_sync_mounts
from tinysoul.infra.network import ResolvedNetwork
from tinysoul.prompts.plugins.capabilities import web as prompt_text

from ..errors import WebProcessingError

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})


@dataclass(frozen=True)
class FetchedPage:
    """One bounded external page after redirects and link normalization."""

    final_url: str
    html: str
    content_type: str


@dataclass(frozen=True)
class _FetchedText:
    final_url: str
    text: str
    content_type: str
    status_code: int


AddressResolver = Callable[..., object]


def fetch_public_page(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: int,
    max_redirects: int,
    user_agent: str,
    network: ResolvedNetwork = ResolvedNetwork(),
    resolver: AddressResolver = socket.getaddrinfo,
) -> FetchedPage:
    """Fetch one public HTTPS page with bounded body and explicit redirects."""

    fetched = _fetch_public_text(
        url,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
        max_redirects=max_redirects,
        user_agent=user_agent,
        network=network,
        resolver=resolver,
        allowed_content_types=_ALLOWED_CONTENT_TYPES,
    )
    normalized = normalize_html_links(fetched.text, base_url=fetched.final_url)
    return FetchedPage(
        final_url=fetched.final_url,
        html=normalized,
        content_type=fetched.content_type,
    )


def fetch_public_robots(
    page_url: str,
    *,
    max_bytes: int,
    timeout_seconds: int,
    max_redirects: int,
    user_agent: str,
    network: ResolvedNetwork = ResolvedNetwork(),
    resolver: AddressResolver = socket.getaddrinfo,
) -> str:
    """Return one origin's robots.txt through the public HTTPS boundary."""

    page = urlsplit(normalize_https_url(page_url))
    robots_url = urlunsplit(("https", page.netloc, "/robots.txt", "", ""))
    fetched = _fetch_public_text(
        robots_url,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
        max_redirects=max_redirects,
        user_agent=user_agent,
        network=network,
        resolver=resolver,
        allowed_content_types=_ALLOWED_CONTENT_TYPES,
        empty_statuses=frozenset({404, 410}),
    )
    return fetched.text


def _fetch_public_text(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: int,
    max_redirects: int,
    user_agent: str,
    network: ResolvedNetwork = ResolvedNetwork(),
    resolver: AddressResolver = socket.getaddrinfo,
    allowed_content_types: frozenset[str],
    empty_statuses: frozenset[int] = frozenset(),
) -> _FetchedText:
    current = url
    headers = {
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
        "User-Agent": user_agent,
    }
    try:
        with httpx.Client(
            timeout=float(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            mounts=httpx_sync_mounts(network),
            headers=headers,
        ) as client:
            for redirect_count in range(max_redirects + 1):
                current = validate_public_https_url(
                    current, network=network, resolver=resolver
                )
                with client.stream("GET", current) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location", "")
                        if not location:
                            raise WebProcessingError(
                                prompt_text.WEB_REDIRECT_DID_NOT_PROVIDE_A_DESTINATION,
                                reason="invalid_redirect",
                            )
                        if redirect_count >= max_redirects:
                            raise WebProcessingError(
                                prompt_text.redirect_limit(limit=max_redirects),
                                reason="redirect_limit_exceeded",
                            )
                        current = urljoin(str(response.url), location)
                        continue
                    if response.status_code in empty_statuses:
                        return _FetchedText(
                            final_url=normalize_https_url(str(response.url)),
                            text="",
                            content_type=_content_type(
                                response.headers.get("content-type", "")
                            ),
                            status_code=response.status_code,
                        )
                    if response.status_code < 200 or response.status_code >= 300:
                        raise WebProcessingError(
                            prompt_text.http_status_error(
                                status_code=response.status_code
                            ),
                            reason="http_status_error",
                            payload={"status_code": response.status_code},
                        )
                    content_type = _content_type(
                        response.headers.get("content-type", "")
                    )
                    if content_type not in allowed_content_types:
                        raise WebProcessingError(
                            prompt_text.WEB_PAGE_CONTENT_TYPE_IS_NOT_SUPPORTED,
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
                                prompt_text.page_too_large(limit=max_bytes),
                                reason="source_bytes_limit_exceeded",
                            )
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise WebProcessingError(
                                prompt_text.page_too_large(limit=max_bytes),
                                reason="source_bytes_limit_exceeded",
                            )
                    final_url = normalize_https_url(str(response.url))
                    encoding = response.encoding or "utf-8"
                    text = bytes(body).decode(encoding, errors="replace")
                    return _FetchedText(
                        final_url=final_url,
                        text=text,
                        content_type=content_type,
                        status_code=response.status_code,
                    )
    except WebProcessingError:
        raise
    except (httpx.HTTPError, OSError, UnicodeError) as exc:
        raise WebProcessingError(
            prompt_text.WEB_PAGE_COULD_NOT_BE_RETRIEVED,
            reason="network_request_failed",
            payload={"error_type": type(exc).__name__},
        ) from exc
    raise WebProcessingError(
        prompt_text.WEB_PAGE_RETRIEVAL_ENDED_WITHOUT_A_RESULT,
        reason="network_request_failed",
    )


def normalize_https_url(value: str) -> str:
    """Validate URL syntax and canonicalize it without resolving the target."""

    if not isinstance(value, str) or not value:
        raise WebProcessingError(
            prompt_text.WEB_URL_MUST_BE_A_NON_EMPTY_STRING,
            reason="invalid_url",
        )
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise WebProcessingError(
            prompt_text.WEB_URL_IS_INVALID, reason="invalid_url"
        ) from exc
    if parsed.scheme.lower() != "https":
        raise WebProcessingError(
            prompt_text.WEB_FETCH_ONLY_ACCEPTS_HTTPS_URLS,
            reason="unsupported_url_scheme",
        )
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise WebProcessingError(
            prompt_text.WEB_URL_AUTHORITY_IS_INVALID, reason="invalid_url"
        )
    host = parsed.hostname.rstrip(".").lower()
    if not host:
        raise WebProcessingError(
            prompt_text.WEB_URL_AUTHORITY_IS_INVALID, reason="invalid_url"
        )
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != 443:
        netloc = f"{netloc}:{port}"
    try:
        return str(httpx.URL(
            urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
        ))
    except httpx.InvalidURL as exc:
        raise WebProcessingError(
            prompt_text.WEB_URL_IS_INVALID, reason="invalid_url"
        ) from exc


def validate_public_https_url(
    value: str,
    *,
    network: ResolvedNetwork = ResolvedNetwork(),
    resolver: AddressResolver = socket.getaddrinfo,
) -> str:
    """Validate a target using local DNS only for a direct domain connection."""
    canonical = normalize_https_url(value)
    parsed = urlsplit(canonical)
    host = parsed.hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        raise WebProcessingError(
            prompt_text.WEB_URL_MUST_RESOLVE_TO_A_PUBLIC_HOST,
            reason="private_network_target",
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            raise WebProcessingError(
                prompt_text.WEB_URL_MUST_RESOLVE_TO_A_PUBLIC_HOST,
                reason="private_network_target",
            )
        return canonical
    if network.proxy_for_url(canonical) is not None:
        return canonical
    effective_port = 443 if parsed.port is None else parsed.port
    try:
        resolved = resolver(host, effective_port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebProcessingError(
            prompt_text.WEB_HOST_COULD_NOT_BE_RESOLVED,
            reason="dns_resolution_failed",
        ) from exc
    if not isinstance(resolved, list) or not resolved:
        raise WebProcessingError(
            prompt_text.WEB_HOST_DID_NOT_RESOLVE_TO_AN_ADDRESS,
            reason="dns_resolution_failed",
        )
    for item in resolved:
        if not isinstance(item, tuple) or len(item) < 5:
            raise WebProcessingError(
                prompt_text.WEB_HOST_RESOLUTION_RETURNED_AN_INVALID_ADDRESS,
                reason="dns_resolution_failed",
            )
        sockaddr = item[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            raise WebProcessingError(
                prompt_text.WEB_HOST_RESOLUTION_RETURNED_AN_INVALID_ADDRESS,
                reason="dns_resolution_failed",
            )
        resolved_address = str(sockaddr[0]).split("%", 1)[0]
        try:
            parsed_address = ipaddress.ip_address(resolved_address)
        except ValueError as exc:
            raise WebProcessingError(
                prompt_text.WEB_HOST_RESOLUTION_RETURNED_AN_INVALID_ADDRESS,
                reason="dns_resolution_failed",
            ) from exc
        if not parsed_address.is_global:
            raise WebProcessingError(
                prompt_text.WEB_URL_MUST_RESOLVE_ONLY_TO_PUBLIC_ADDRESSES,
                reason="private_network_target",
            )
    return canonical


def normalize_html_links(value: str, *, base_url: str) -> str:
    """Make page links absolute before a local extractor sees the HTML."""

    try:
        document = html.fromstring(value, base_url=base_url)
        document.make_links_absolute(base_url, resolve_base_href=True)
        return html.tostring(document, encoding="unicode", method="html")
    except (etree.ParserError, etree.XMLSyntaxError, ValueError) as exc:
        raise WebProcessingError(
            prompt_text.WEB_PAGE_HTML_COULD_NOT_BE_NORMALIZED,
            reason="invalid_html",
            payload={"error_type": type(exc).__name__},
        ) from exc


def _content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()
