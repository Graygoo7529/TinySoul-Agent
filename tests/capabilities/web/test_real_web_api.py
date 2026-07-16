from __future__ import annotations

import os
from pathlib import Path
from time import monotonic
from typing import cast

import pytest

from tinysoul.action import ActionExecutionControl
from tinysoul.capabilities.web.config import KimiSearchSettings, WebSettings
from tinysoul.capabilities.web.dependencies import kimi_search_api_key
from tinysoul.capabilities.web.service import WebCapabilityService
from tinysoul.infra import JsonValue, StagingDirectoryManager
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.workspace import WorkspaceEngineBuilder, WorkspaceSettings


pytestmark = pytest.mark.skipif(
    os.environ.get("TINYSOUL_RUN_REAL_WEB_API_TESTS") != "1",
    reason="real Web API integration test is disabled",
)


def test_real_kimi_search_returns_answer_and_structured_results(
    local_tmp: Path,
) -> None:
    environment = ConfigEnvironment.from_project_root(Path.cwd())
    settings = WebSettings(
        search_by_kimi=KimiSearchSettings(
            enabled=True,
            max_inline_chars=80_000,
            max_result_chars=100_000,
            max_output_tokens=2_048,
        )
    )
    staging = StagingDirectoryManager(local_tmp.resolve())
    staging.prepare()
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(root=(local_tmp / "workspace").resolve(), max_files=20)
    ).build()
    service = WebCapabilityService(
        workspace=workspace,
        settings=settings,
        runtime_env=environment.runtime_env,
        staging=staging,
        kimi_api_key=kimi_search_api_key(settings, environment.runtime_env),
    )

    result = service.search_by_kimi(
        query=(
            "What is the official homepage URL for the Python programming "
            "language? Answer in one sentence and include the most relevant source."
        ),
        invoke_id="real_kimi_search",
        call_id="real_kimi_search_call",
        owner_turn_id="real_web_turn",
        control=ActionExecutionControl(deadline=monotonic() + 120),
    )

    answer = result.payload["answer"]
    results = cast(list[JsonValue], result.payload["results"])
    assert isinstance(answer, str) and answer.strip()
    assert results
    for raw in results:
        item = cast(dict[str, JsonValue], raw)
        assert isinstance(item.get("title"), str) and item["title"]
        assert isinstance(item.get("url"), str) and item["url"]
        assert isinstance(item.get("snippet"), str) and item["snippet"]
    assert "mode" not in result.payload
