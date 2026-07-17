from __future__ import annotations

import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import cast

from tinysoul.action import (
    ActionCall,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutionControl,
    ActionFramework,
    ActionResultStatus,
    builtin_action_catalog_root,
)
from tinysoul.action.backends import (
    ControlledProcessRunner,
    ProcessOutcome,
    ProcessRequest,
    ProcessStatus,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.capabilities import parse_capabilities_settings
from tinysoul.capabilities.web.actions import (
    WEB_DISCOVER_PAGES_ACTION,
    WebDiscoveryExecutor,
)
from tinysoul.capabilities.web.config import WebDiscoverySettings, WebSettings
from tinysoul.capabilities.web.dependencies import web_dependency_requirements
from tinysoul.capabilities.web.discovery import DiscoveryRequest, discover_pages
from tinysoul.capabilities.web.network import FetchedPage
from tinysoul.capabilities.web.service import WebCapabilityService
from tinysoul.infra import JsonValue, StagingDirectoryManager, dumps_json
from tinysoul.runtime import RunScope, SignalBus
from tinysoul.workspace import WorkspaceEngineBuilder, WorkspaceSettings


def test_discovery_config_and_dependency_are_independent() -> None:
    settings = parse_capabilities_settings(
        {
            "web": {
                "discover_pages": {
                    "enabled": True,
                    "max_visit_depth": 2,
                    "max_pages": 8,
                    "max_concurrency": 2,
                },
                "fetch_with_trafilatura": {"enabled": False},
            }
        }
    ).web

    assert settings.discover_pages.enabled is True
    assert settings.discover_pages.max_visit_depth == 2
    assert settings.discover_pages.max_pages == 8
    assert [
        requirement.id for requirement in web_dependency_requirements(settings)
    ] == ["web.discovery", "web.http"]


def test_crawlee_discovery_returns_direct_candidates_and_recursive_metadata() -> None:
    pages = {
        "https://example.com/docs/": FetchedPage(
            final_url="https://example.com/docs/",
            html=(
                "<html><head><title>Documentation</title>"
                '<meta name="description" content="Product docs">'
                '<link rel="canonical" href="./"></head>'
                "<body><h1>Documentation</h1>"
                '<a href="install" title="Install">'
                "Installation</a>"
                '<a href="https://example.com/docs/private">Private</a>'
                '<a href="https://example.com/docs/search?q=one">Search</a>'
                '<a href="https://other.example/docs/">Other</a>'
                '<a href="https://example.com:bad/docs/broken">Broken</a>'
                "</body></html>"
            ),
            content_type="text/html",
        ),
        "https://example.com/docs/install": FetchedPage(
            final_url="https://example.com/docs/install",
            html=(
                "<html><head><title>Install</title></head>"
                "<body><h1>Install TinySoul</h1>"
                '<a href="advanced">Advanced</a>'
                "</body></html>"
            ),
            content_type="text/html",
        ),
    }

    def fetch_page(url: str, **kwargs: object) -> FetchedPage:
        del kwargs
        return pages[url]

    def fetch_robots(url: str, **kwargs: object) -> str:
        del url, kwargs
        return "User-agent: *\nDisallow: /docs/private\n"

    async def exercise() -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
        direct = await discover_pages(
            _discovery_request(depth=0),
            page_fetcher=fetch_page,
            robots_fetcher=fetch_robots,
        )
        recursive = await discover_pages(
            _discovery_request(depth=1),
            page_fetcher=fetch_page,
            robots_fetcher=fetch_robots,
        )
        return direct, recursive

    direct, recursive = asyncio.run(exercise())

    direct_source = cast(dict[str, JsonValue], direct["source"])
    assert direct_source["title"] == "Documentation"
    assert direct_source["description"] == "Product docs"
    assert direct_source["h1"] == "Documentation"
    assert direct_source["canonical_url"] == "https://example.com/docs/"
    direct_pages = cast(list[dict[str, JsonValue]], direct["pages"])
    assert [page["url"] for page in direct_pages] == [
        "https://example.com/docs/install"
    ]
    assert direct_pages[0]["state"] == "candidate"
    assert direct_pages[0]["anchor_text"] == "Installation"
    assert direct["visited_count"] == 1
    assert direct["skipped_count"] == 1

    recursive_pages = cast(list[dict[str, JsonValue]], recursive["pages"])
    assert [page["url"] for page in recursive_pages] == [
        "https://example.com/docs/install",
        "https://example.com/docs/advanced",
    ]
    assert recursive_pages[0]["state"] == "visited"
    assert recursive_pages[0]["title"] == "Install"
    assert recursive_pages[0]["h1"] == "Install TinySoul"
    assert recursive_pages[1]["state"] == "candidate"
    assert recursive["visited_count"] == 2


def test_discovery_service_returns_complete_inline_result(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    service = WebCapabilityService(
        workspace=workspace,
        settings=WebSettings(
            discover_pages=WebDiscoverySettings(enabled=True),
        ),
        runtime_env={},
        staging=_staging(local_tmp),
        process_runner=_DiscoveryRunner(page_count=2),
    )

    result = service.discover_pages(
        start_url="https://example.com/docs/",
        max_visit_depth=0,
        include_globs=("/docs/**",),
        exclude_globs=(),
        invoke_id="invoke_discovery",
        call_id="call_discovery",
        owner_turn_id="turn_1",
        control=ActionExecutionControl(deadline=monotonic() + 30),
    )

    assert result.payload["page_count"] == 2
    assert result.payload["truncated"] is False
    assert len(cast(list[JsonValue], result.payload["pages"])) == 2
    assert workspace.snapshot().resources == ()


def test_discovery_page_budget_is_hard_and_any_followable_reference_can_visit() -> None:
    pages = {
        "https://example.com/docs/": FetchedPage(
            final_url="https://example.com/docs/",
            html=(
                '<a href="https://example.com/docs/a" rel="nofollow">A blocked</a>'
                '<a href="https://example.com/docs/a">A followable</a>'
                '<a href="https://example.com/docs/b">B</a>'
            ),
            content_type="text/html",
        ),
        "https://example.com/docs/a": FetchedPage(
            final_url="https://example.com/docs/a",
            html="<title>A</title>",
            content_type="text/html",
        ),
    }

    def fetch_page(url: str, **kwargs: object) -> FetchedPage:
        del kwargs
        return pages[url]

    def fetch_robots(url: str, **kwargs: object) -> str:
        del url, kwargs
        return ""

    request = _discovery_request(depth=1, max_pages=2)
    result = asyncio.run(
        discover_pages(
            request,
            page_fetcher=fetch_page,
            robots_fetcher=fetch_robots,
        )
    )

    discovered = cast(list[dict[str, JsonValue]], result["pages"])
    assert [page["state"] for page in discovered] == ["visited", "candidate"]
    assert result["visited_count"] == 2
    assert result["stop_reason"] == "page_limit"


def test_oversized_discovery_spills_complete_json_and_emits_signal(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    bus = SignalBus()
    service = WebCapabilityService(
        workspace=workspace,
        settings=WebSettings(
            discover_pages=WebDiscoverySettings(
                enabled=True,
                max_inline_chars=1_000,
                max_result_chars=100_000,
            ),
        ),
        runtime_env={},
        staging=_staging(local_tmp),
        process_runner=_DiscoveryRunner(page_count=20, anchor_chars=400),
    )
    executor = WebDiscoveryExecutor(service=service, bus=bus)

    result = executor.execute(
        _discovery_execution(),
        ActionExecutionContext(
            control=ActionExecutionControl(deadline=monotonic() + 30),
        ),
    )

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload["truncated"] is True
    assert result.payload["page_count"] == 20
    assert len(dumps_json(result.payload)) <= 1_000
    link = result.payload["see_more_at"]
    assert link == "workspace:web/discovery/invoke_discovery-call_discovery.json"
    document = workspace.read_text(str(link), max_chars=100_000).text
    stored = json.loads(document)
    assert stored["truncated"] is False
    assert len(stored["pages"]) == 20
    assert stored["pages"][-1]["anchor_text"] == "A" * 400
    signals = bus.consume()
    assert len(signals) == 1
    assert signals[0].name == "context.workspace.sync"


class _DiscoveryRunner(ControlledProcessRunner):
    def __init__(self, *, page_count: int, anchor_chars: int = 20) -> None:
        self._page_count = page_count
        self._anchor_chars = anchor_chars

    def run(
        self,
        request: ProcessRequest,
        control: ActionExecutionControl,
    ) -> ProcessOutcome:
        del control
        assert request.stdin_text is not None
        worker_request = json.loads(request.stdin_text)
        assert worker_request["operation"] == "discover_pages"
        assert worker_request["max_visit_depth"] == 0
        assert worker_request["include_globs"] == ["/docs/**"]
        pages = [
            {
                "url": f"https://example.com/docs/page-{index}",
                "depth": 1,
                "state": "candidate",
                "discovered_from": "https://example.com/docs/",
                "anchor_text": "A" * self._anchor_chars,
                "link_title": "",
                "rel": "",
            }
            for index in range(self._page_count)
        ]
        return ProcessOutcome(
            status=ProcessStatus.COMPLETED,
            exit_code=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "source": {
                        "url": "https://example.com/docs/",
                        "final_url": "https://example.com/docs/",
                        "title": "Documentation",
                        "description": "Product docs",
                        "h1": "Documentation",
                        "canonical_url": "https://example.com/docs/",
                    },
                    "pages": pages,
                    "page_count": self._page_count,
                    "visited_count": 1,
                    "candidate_count": self._page_count,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "stop_reason": "completed",
                    "truncated": False,
                    "untrusted_external_content": True,
                }
            ),
        )


def _discovery_request(*, depth: int, max_pages: int = 10) -> DiscoveryRequest:
    return DiscoveryRequest(
        start_url="https://example.com/docs/",
        max_visit_depth=depth,
        include_globs=("/docs/**",),
        exclude_globs=(),
        max_pages=max_pages,
        max_candidates=20,
        max_links_per_page=20,
        max_concurrency=1,
        max_tasks_per_minute=1_000,
        max_request_retries=0,
        max_crawl_seconds=5,
        max_source_bytes=100_000,
        request_timeout_seconds=2,
        max_redirects=2,
        user_agent="TinySoul-Agent/0.1",
        allow_query_links=False,
    )


def _discovery_execution() -> ActionExecution:
    with builtin_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action(
            WEB_DISCOVER_PAGES_ACTION
        )
    return ActionExecution(
        action=action,
        call=ActionCall(
            call_id="call_discovery",
            action_name=WEB_DISCOVER_PAGES_ACTION,
            params={
                "start_url": "https://example.com/docs/",
                "max_visit_depth": 0,
                "include_globs": ["/docs/**"],
            },
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id="invoke_discovery",
            batch_id="batch_1",
            scope=RunScope(),
            domain="web",
            turn_id="turn_1",
        ),
    )


def _workspace(root: Path):
    return WorkspaceEngineBuilder(
        WorkspaceSettings(root=(root / "workspace").resolve(), max_files=100)
    ).build()


def _staging(root: Path) -> StagingDirectoryManager:
    staging = StagingDirectoryManager(root.resolve())
    staging.prepare()
    return staging
