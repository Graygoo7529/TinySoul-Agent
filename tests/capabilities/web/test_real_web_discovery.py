from __future__ import annotations

import os
from pathlib import Path
from time import monotonic
from typing import cast

import pytest

from tinysoul.action import ActionExecutionControl
from tinysoul.capabilities.web.config import WebDiscoverySettings, WebSettings
from tinysoul.capabilities.web.service import WebCapabilityService
from tinysoul.infra import JsonValue, StagingDirectoryManager
from tinysoul.workspace import WorkspaceEngineBuilder, WorkspaceSettings


pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        os.environ.get("TINYSOUL_RUN_REAL_WEB_DISCOVERY_TESTS") != "1",
        reason="real Web discovery integration test is disabled",
    ),
]


def test_real_page_discovery_returns_same_origin_candidates(
    local_tmp: Path,
) -> None:
    staging = StagingDirectoryManager(local_tmp.resolve())
    staging.prepare()
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(root=(local_tmp / "workspace").resolve(), max_files=20)
    ).build()
    service = WebCapabilityService(
        workspace=workspace,
        settings=WebSettings(
            discover_pages=WebDiscoverySettings(
                enabled=True,
                max_pages=3,
                max_candidates=30,
                max_links_per_page=50,
                max_inline_chars=100_000,
                max_result_chars=100_000,
                max_concurrency=1,
                max_tasks_per_minute=60,
                max_crawl_seconds=60,
            )
        ),
        runtime_env=os.environ,
        staging=staging,
    )

    result = service.discover_pages(
        start_url="https://crawlee.dev/python/docs/",
        max_visit_depth=0,
        include_globs=("/python/docs/**",),
        exclude_globs=(),
        invoke_id="real_discovery",
        call_id="real_discovery_call",
        owner_turn_id="real_web_turn",
        control=ActionExecutionControl(deadline=monotonic() + 90),
    )

    source = cast(dict[str, JsonValue], result.payload["source"])
    pages = cast(list[dict[str, JsonValue]], result.payload["pages"])
    assert source["title"]
    assert pages
    assert all(str(page["url"]).startswith("https://crawlee.dev/") for page in pages)
    assert result.payload["visited_count"] == 1
    assert result.payload["truncated"] is False
