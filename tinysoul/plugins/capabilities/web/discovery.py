"""Crawlee-backed, TinySoul-fetched page discovery."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from fnmatch import fnmatchcase
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from uuid import uuid4

from crawlee import ConcurrencySettings, Request
from crawlee.crawlers import BasicCrawler, BasicCrawlingContext
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue
from lxml import html

from tinysoul.infra import JsonObject, to_json_object

from .errors import WebProcessingError
from .network import (
    FetchedPage,
    fetch_public_page,
    fetch_public_robots,
    validate_public_https_url,
)


_MAX_PATTERN_COUNT = 20
_MAX_PATTERN_CHARS = 200
_MAX_ANCHOR_CHARS = 300
_MAX_METADATA_CHARS = 500
_MAX_REL_CHARS = 200
_STOP_PRIORITY = (
    "crawl_time_limit",
    "page_limit",
    "candidate_limit",
    "per_page_link_limit",
    "completed",
)


PageFetcher = Callable[..., FetchedPage]
RobotsFetcher = Callable[..., str]


@dataclass(frozen=True)
class DiscoveryRequest:
    start_url: str
    max_visit_depth: int
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    max_pages: int
    max_candidates: int
    max_links_per_page: int
    max_concurrency: int
    max_tasks_per_minute: int
    max_request_retries: int
    max_crawl_seconds: int
    max_source_bytes: int
    request_timeout_seconds: int
    max_redirects: int
    user_agent: str
    allow_query_links: bool

    def __post_init__(self) -> None:
        if not self.start_url:
            raise WebProcessingError(
                "Discovery seed URL must be non-empty",
                reason="invalid_url",
            )
        if self.max_visit_depth < 0:
            raise WebProcessingError(
                "Discovery visit depth must be non-negative",
                reason="invalid_visit_depth",
            )
        for name in (
            "max_pages",
            "max_candidates",
            "max_links_per_page",
            "max_concurrency",
            "max_tasks_per_minute",
            "max_crawl_seconds",
            "max_source_bytes",
            "request_timeout_seconds",
            "max_redirects",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise WebProcessingError(
                    "Discovery numeric boundary is invalid",
                    reason="worker_protocol_invalid",
                )
        if self.max_request_retries < 0:
            raise WebProcessingError(
                "Discovery retry boundary is invalid",
                reason="worker_protocol_invalid",
            )
        if self.max_concurrency > self.max_pages:
            raise WebProcessingError(
                "Discovery concurrency exceeds its page budget",
                reason="worker_protocol_invalid",
            )
        _validate_globs(self.include_globs)
        _validate_globs(self.exclude_globs)


@dataclass(frozen=True)
class _Reference:
    source_url: str
    anchor_text: str
    link_title: str
    rel: str


@dataclass
class _PageState:
    url: str
    depth: int
    state: str = "candidate"
    references: set[_Reference] = field(default_factory=set)
    final_url: str = ""
    title: str = ""
    description: str = ""
    h1: str = ""
    canonical_url: str = ""
    failure_reason: str = ""


@dataclass
class _DiscoveryState:
    pages: dict[str, _PageState] = field(default_factory=dict)
    reserved_urls: set[str] = field(default_factory=set)
    scheduled_urls: set[str] = field(default_factory=set)
    stop_reasons: set[str] = field(default_factory=set)
    skipped_count: int = 0


async def discover_pages(
    request: DiscoveryRequest,
    *,
    page_fetcher: PageFetcher = fetch_public_page,
    robots_fetcher: RobotsFetcher = fetch_public_robots,
) -> JsonObject:
    """Return one bounded discovery graph without preserving page bodies."""

    start_url = validate_public_https_url(request.start_url)
    origin = _origin(start_url)
    robots_text = await asyncio.to_thread(
        robots_fetcher,
        start_url,
        max_bytes=min(request.max_source_bytes, 512 * 1024),
        timeout_seconds=request.request_timeout_seconds,
        max_redirects=request.max_redirects,
        user_agent=request.user_agent,
    )
    robots = RobotFileParser()
    robots.set_url(urlunsplit((*origin, "/robots.txt", "", "")))
    robots.parse(robots_text.splitlines())
    if not robots.can_fetch(request.user_agent, start_url):
        raise WebProcessingError(
            "Discovery seed is disallowed by robots.txt",
            reason="seed_disallowed_by_robots",
        )

    state = _DiscoveryState(
        pages={start_url: _PageState(url=start_url, depth=0)},
        scheduled_urls={start_url},
    )
    lock = asyncio.Lock()
    raw_crawl_delay = robots.crawl_delay(request.user_agent)
    if raw_crawl_delay is None:
        raw_crawl_delay = robots.crawl_delay("*")
    crawl_delay = (
        float(raw_crawl_delay)
        if isinstance(raw_crawl_delay, int | float)
        and not isinstance(raw_crawl_delay, bool)
        and raw_crawl_delay > 0
        else 0.0
    )
    tasks_per_minute = float(request.max_tasks_per_minute)
    if crawl_delay > 0:
        tasks_per_minute = min(tasks_per_minute, 60.0 / crawl_delay)
    effective_concurrency = 1 if crawl_delay > 0 else request.max_concurrency
    concurrency = ConcurrencySettings(
        min_concurrency=1,
        max_concurrency=effective_concurrency,
        desired_concurrency=effective_concurrency,
        max_tasks_per_minute=max(tasks_per_minute, 0.01),
    )
    storage_client = MemoryStorageClient()
    request_queue = await RequestQueue.open(
        alias=f"tinysoul-{uuid4().hex}",
        storage_client=storage_client,
    )
    crawler = BasicCrawler(
        storage_client=storage_client,
        request_manager=request_queue,
        use_session_pool=False,
        retry_on_blocked=False,
        configure_logging=False,
        max_request_retries=request.max_request_retries,
        max_requests_per_crawl=request.max_pages,
        concurrency_settings=concurrency,
        request_handler_timeout=timedelta(
            seconds=request.request_timeout_seconds + 5
        ),
    )

    @crawler.router.default_handler
    async def handle(context: BasicCrawlingContext) -> None:
        current_url = context.request.url
        depth = _request_depth(context.request)
        async with lock:
            page_state = state.pages.setdefault(
                current_url,
                _PageState(url=current_url, depth=depth),
            )
            page_state.depth = min(page_state.depth, depth)
            if current_url not in state.reserved_urls:
                if len(state.reserved_urls) >= request.max_pages:
                    state.stop_reasons.add("page_limit")
                    return
                state.reserved_urls.add(current_url)

        page = await asyncio.to_thread(
            page_fetcher,
            current_url,
            max_bytes=request.max_source_bytes,
            timeout_seconds=request.request_timeout_seconds,
            max_redirects=request.max_redirects,
            user_agent=request.user_agent,
        )
        if _origin(page.final_url) != origin:
            raise WebProcessingError(
                "Discovery redirect left the seed origin",
                reason="discovery_scope_violation",
            )
        metadata = _page_metadata(page)
        links, links_limited = _page_links(
            page,
            origin=origin,
            include_globs=request.include_globs,
            exclude_globs=request.exclude_globs,
            allow_query_links=request.allow_query_links,
            max_links=request.max_links_per_page,
        )
        enqueue: list[Request] = []
        async with lock:
            page_state.state = "visited"
            page_state.final_url = page.final_url
            page_state.title = metadata["title"]
            page_state.description = metadata["description"]
            page_state.h1 = metadata["h1"]
            page_state.canonical_url = metadata["canonical_url"]
            if links_limited:
                state.stop_reasons.add("per_page_link_limit")
            for candidate_url, reference, nofollow in links:
                if not robots.can_fetch(request.user_agent, candidate_url):
                    state.skipped_count += 1
                    continue
                candidate = state.pages.get(candidate_url)
                if candidate is None:
                    candidates = len(state.pages) - 1
                    if candidates >= request.max_candidates:
                        state.stop_reasons.add("candidate_limit")
                        continue
                    candidate = _PageState(url=candidate_url, depth=depth + 1)
                    state.pages[candidate_url] = candidate
                candidate.depth = min(candidate.depth, depth + 1)
                candidate.references.add(reference)
                if (
                    not nofollow
                    and depth + 1 <= request.max_visit_depth
                    and candidate.state == "candidate"
                    and candidate_url not in state.scheduled_urls
                ):
                    if len(state.scheduled_urls) >= request.max_pages:
                        state.stop_reasons.add("page_limit")
                        continue
                    state.scheduled_urls.add(candidate_url)
                    enqueue.append(
                        Request.from_url(
                            candidate_url,
                            user_data={"depth": depth + 1},
                        )
                    )
        if enqueue:
            await context.add_requests(enqueue)

    @crawler.failed_request_handler
    async def failed(context: BasicCrawlingContext, error: Exception) -> None:
        current_url = context.request.url
        async with lock:
            page_state = state.pages.setdefault(
                current_url,
                _PageState(url=current_url, depth=_request_depth(context.request)),
            )
            page_state.state = "failed"
            page_state.failure_reason = _failure_reason(error)

    run_task = asyncio.create_task(
        crawler.run(
            [Request.from_url(start_url, user_data={"depth": 0})],
        )
    )
    try:
        await asyncio.wait_for(
            asyncio.shield(run_task),
            timeout=float(request.max_crawl_seconds),
        )
    except TimeoutError:
        state.stop_reasons.add("crawl_time_limit")
        crawler.stop("configured crawl time limit")
        await run_task

    source = state.pages[start_url]
    if source.state != "visited":
        raise WebProcessingError(
            "Discovery seed could not be visited",
            reason=source.failure_reason or "seed_fetch_failed",
        )
    pages = [
        _page_payload(item)
        for url, item in sorted(
            state.pages.items(),
            key=lambda pair: (pair[1].depth, pair[0]),
        )
        if url != start_url
    ]
    visited_count = sum(item.state == "visited" for item in state.pages.values())
    failed_count = sum(item.state == "failed" for item in state.pages.values())
    candidate_count = sum(item.state == "candidate" for item in state.pages.values())
    return to_json_object(
        {
            "source": _source_payload(source),
            "pages": pages,
            "page_count": len(pages),
            "visited_count": visited_count,
            "candidate_count": candidate_count,
            "failed_count": failed_count,
            "skipped_count": state.skipped_count,
            "stop_reason": _stop_reason(state.stop_reasons),
            "truncated": False,
            "untrusted_external_content": True,
        }
    )


def _page_links(
    page: FetchedPage,
    *,
    origin: tuple[str, str],
    include_globs: tuple[str, ...],
    exclude_globs: tuple[str, ...],
    allow_query_links: bool,
    max_links: int,
) -> tuple[list[tuple[str, _Reference, bool]], bool]:
    try:
        document = html.fromstring(page.html)
    except Exception as exc:
        raise WebProcessingError(
            "Discovery page HTML could not be inspected",
            reason="invalid_html",
        ) from exc
    discovered: dict[str, tuple[_Reference, bool]] = {}
    for node in document.xpath("//a[@href]"):
        href = node.get("href", "")
        try:
            resolved_href = urljoin(page.final_url, href)
        except ValueError:
            continue
        candidate = _candidate_url(
            resolved_href,
            origin=origin,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            allow_query_links=allow_query_links,
        )
        if candidate is None or candidate == page.final_url:
            continue
        rel_values = sorted(set(str(node.get("rel", "")).lower().split()))
        reference = _Reference(
            source_url=page.final_url,
            anchor_text=_clean_text(" ".join(node.itertext()), _MAX_ANCHOR_CHARS),
            link_title=_clean_text(node.get("title", ""), _MAX_METADATA_CHARS),
            rel=_clean_text(" ".join(rel_values), _MAX_REL_CHARS),
        )
        previous = discovered.get(candidate)
        nofollow = "nofollow" in rel_values
        if previous is None:
            discovered[candidate] = (reference, nofollow)
            continue
        selected = min((previous[0], reference), key=_reference_key)
        discovered[candidate] = (selected, previous[1] and nofollow)
    ordered = [
        (url, reference, nofollow)
        for url, (reference, nofollow) in sorted(discovered.items())
    ]
    return ordered[:max_links], len(ordered) > max_links


def _candidate_url(
    value: str,
    *,
    origin: tuple[str, str],
    include_globs: tuple[str, ...],
    exclude_globs: tuple[str, ...],
    allow_query_links: bool,
) -> str | None:
    try:
        parsed = urlsplit(value)
        netloc = _canonical_netloc(parsed)
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if ("https", netloc) != origin:
        return None
    if parsed.query and not allow_query_links:
        return None
    path = parsed.path or "/"
    if include_globs and not any(fnmatchcase(path, pattern) for pattern in include_globs):
        return None
    if any(fnmatchcase(path, pattern) for pattern in exclude_globs):
        return None
    return urlunsplit(("https", netloc, path, parsed.query, ""))


def _page_metadata(page: FetchedPage) -> dict[str, str]:
    try:
        document = html.fromstring(page.html)
    except Exception:
        return {"title": "", "description": "", "h1": "", "canonical_url": ""}
    canonical = ""
    canonical_values = document.xpath(
        "//link[contains(concat(' ', translate(@rel, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        "'abcdefghijklmnopqrstuvwxyz'), ' '), ' canonical ')]/@href"
    )
    if canonical_values:
        value = urljoin(page.final_url, str(canonical_values[0]))
        try:
            parsed = urlsplit(value)
            if parsed.scheme == "https" and parsed.netloc:
                canonical = urlunsplit(
                    ("https", _canonical_netloc(parsed), parsed.path or "/", parsed.query, "")
                )
        except ValueError:
            canonical = ""
    return {
        "title": _first_text(document.xpath("//title/text()")),
        "description": _first_text(
            document.xpath(
                "//meta[translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz')='description']/@content"
            )
        ),
        "h1": _first_text(document.xpath("//h1[1]//text()")),
        "canonical_url": _clean_text(canonical, _MAX_METADATA_CHARS),
    }


def _source_payload(page: _PageState) -> JsonObject:
    return {
        "url": page.url,
        "final_url": page.final_url,
        "title": page.title,
        "description": page.description,
        "h1": page.h1,
        "canonical_url": page.canonical_url,
    }


def _page_payload(page: _PageState) -> JsonObject:
    reference = min(page.references, key=_reference_key) if page.references else None
    payload: JsonObject = {
        "url": page.url,
        "depth": page.depth,
        "state": page.state,
        "discovered_from": reference.source_url if reference else "",
        "anchor_text": reference.anchor_text if reference else "",
        "link_title": reference.link_title if reference else "",
        "rel": reference.rel if reference else "",
    }
    if page.state == "visited":
        payload.update(
            {
                "final_url": page.final_url,
                "title": page.title,
                "description": page.description,
                "h1": page.h1,
                "canonical_url": page.canonical_url,
            }
        )
    elif page.state == "failed":
        payload["failure_reason"] = page.failure_reason
    return payload


def _origin(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    return parsed.scheme.lower(), _canonical_netloc(parsed)


def _canonical_netloc(parsed) -> str:
    host = (parsed.hostname or "").rstrip(".").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    return f"{host}:{port}" if port is not None and port != 443 else host


def _request_depth(request: Request) -> int:
    value = getattr(request.user_data, "depth", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _first_text(values: list[object]) -> str:
    return _clean_text(" ".join(str(value) for value in values), _MAX_METADATA_CHARS)


def _clean_text(value: str, limit: int) -> str:
    normalized = " ".join(str(value).split())
    return normalized if len(normalized) <= limit else normalized[:limit].rstrip()


def _reference_key(reference: _Reference) -> tuple[str, str, str, str]:
    return (
        reference.source_url,
        reference.anchor_text,
        reference.link_title,
        reference.rel,
    )


def _failure_reason(error: Exception) -> str:
    if isinstance(error, WebProcessingError):
        return error.reason
    return "page_visit_failed"


def _stop_reason(reasons: set[str]) -> str:
    for reason in _STOP_PRIORITY:
        if reason == "completed" or reason in reasons:
            return reason
    return "completed"


def _validate_globs(values: tuple[str, ...]) -> None:
    if len(values) > _MAX_PATTERN_COUNT:
        raise WebProcessingError(
            "Discovery path glob count exceeds the configured protocol limit",
            reason="invalid_path_globs",
        )
    for value in values:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > _MAX_PATTERN_CHARS
            or any(ord(char) < 32 for char in value)
        ):
            raise WebProcessingError(
                "Discovery path glob is invalid",
                reason="invalid_path_globs",
            )
