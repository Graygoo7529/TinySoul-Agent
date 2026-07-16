from __future__ import annotations

import json
from pathlib import Path
import shutil
from time import monotonic
from typing import cast

import pytest

from tinysoul.action import (
    ActionCall,
    ActionEngineBuilder,
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
    WEB_FETCH_TRAFILATURA_ACTION,
    WEB_SEARCH_KIMI_ACTION,
    KimiSearchExecutor,
    WebFetchExecutor,
    register_web_actions,
)
from tinysoul.capabilities.web.config import (
    KimiSearchSettings,
    WebFetchSettings,
    WebSettings,
)
from tinysoul.capabilities.web.dependencies import kimi_search_api_key
from tinysoul.capabilities.web.errors import WebProcessingError, WebProcessTimeout
from tinysoul.capabilities.web.models import WebExtractor
from tinysoul.capabilities.web.network import validate_public_https_url
from tinysoul.capabilities.web.service import WebCapabilityService
from tinysoul.infra.config import ConfigError
from tinysoul.infra import JsonValue
from tinysoul.runtime import RunScope, SignalBus
from tinysoul.workspace import WorkspaceEngineBuilder, WorkspaceSettings


def test_web_config_parses_independent_kimi_search_and_fetch_actions() -> None:
    settings = parse_capabilities_settings(
        {
            "web": {
                "search_by_kimi": {
                    "enabled": True,
                    "model": "kimi-k3",
                    "max_results": 6,
                },
                "fetch_with_defuddle": {"enabled": True},
                "fetch_with_trafilatura": {"enabled": False},
            }
        }
    ).web

    assert settings.search_by_kimi.enabled is True
    assert settings.search_by_kimi.api_key_env == "KIMI_SEARCH_API_KEY"
    assert settings.search_by_kimi.max_results == 6
    assert settings.fetch_with_defuddle.enabled is True
    assert settings.fetch_with_trafilatura.enabled is False


def test_web_config_rejects_obsolete_search_mode() -> None:
    with pytest.raises(ConfigError) as error:
        parse_capabilities_settings(
            {"web": {"search_by_kimi": {"mode": "answer"}}}
        )

    assert error.value.key == "capabilities.web.search_by_kimi.mode"


def test_enabled_kimi_search_requires_independent_credential() -> None:
    settings = WebSettings(search_by_kimi=KimiSearchSettings(enabled=True))

    with pytest.raises(ConfigError) as error:
        kimi_search_api_key(settings, {})

    assert error.value.key == "capabilities.web.search_by_kimi.api_key_env"


def test_public_https_validation_rejects_private_targets() -> None:
    def private_resolver(*args, **kwargs):
        del args, kwargs
        return [(None, None, None, "", ("127.0.0.1", 443))]

    with pytest.raises(WebProcessingError) as error:
        validate_public_https_url(
            "https://example.test/page",
            resolver=private_resolver,
        )

    assert error.value.reason == "private_network_target"


def test_public_https_validation_canonicalizes_public_target() -> None:
    def public_resolver(*args, **kwargs):
        del args, kwargs
        return [(None, None, None, "", ("8.8.8.8", 443))]

    result = validate_public_https_url(
        "https://Example.COM/docs?q=1#fragment",
        resolver=public_resolver,
    )

    assert result == "https://example.com/docs?q=1"


def test_kimi_search_returns_answer_and_results_without_mode(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    service = WebCapabilityService(
        workspace=workspace,
        settings=WebSettings(search_by_kimi=KimiSearchSettings(enabled=True)),
        runtime_env={"PATH": "test-path"},
        kimi_api_key="search-secret",
        process_runner=_SearchRunner(answer="Current answer", result_count=2),
    )
    executor = KimiSearchExecutor(service=service, bus=SignalBus())

    result = executor.execute(
        _search_execution(),
        ActionExecutionContext(
            control=ActionExecutionControl(deadline=monotonic() + 30),
        ),
    )

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload["answer"] == "Current answer"
    assert len(cast(list[JsonValue], result.payload["results"])) == 2
    assert result.payload["truncated"] is False
    assert "mode" not in result.payload
    assert workspace.snapshot().resources == ()


def test_oversized_kimi_search_spills_complete_answer_and_results(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    settings = WebSettings(
        search_by_kimi=KimiSearchSettings(
            enabled=True,
            max_inline_chars=1_000,
            max_result_chars=10_000,
        )
    )
    service = WebCapabilityService(
        workspace=workspace,
        settings=settings,
        runtime_env={},
        kimi_api_key="search-secret",
        process_runner=_SearchRunner(answer="A" * 2_000, result_count=4),
    )

    result = service.search_by_kimi(
        query="current topic",
        invoke_id="invoke/1",
        call_id="call/1",
        owner_turn_id="turn_1",
        control=ActionExecutionControl(deadline=monotonic() + 30),
    )

    assert result.payload["truncated"] is True
    assert result.payload["answer"]
    assert isinstance(result.payload["results"], list)
    assert result.payload["see_more_at"] == "workspace:web/search/invoke-1-call-1.md"
    markdown = workspace.read_text(
        "workspace:web/search/invoke-1-call-1.md",
        max_chars=10_000,
    ).text
    assert "A" * 1_000 in markdown
    assert "## Results" in markdown
    assert result.manifest is not None


def test_trafilatura_fetch_commits_only_workspace_markdown_and_metadata(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    service = WebCapabilityService(
        workspace=workspace,
        settings=WebSettings(),
        runtime_env={},
        process_runner=_FetchRunner(),
    )

    result = service.fetch(
        extractor=WebExtractor.TRAFILATURA,
        url="https://example.com/article",
        target_link="workspace:web/pages/article.md",
        overwrite=False,
        expected_target_digest="",
        owner_turn_id="turn_1",
        control=ActionExecutionControl(deadline=monotonic() + 30),
    )

    assert result.markdown_link == "workspace:web/pages/article.md"
    assert result.extractor is WebExtractor.TRAFILATURA
    assert result.excerpt == "Readable page excerpt"
    assert "Readable page" in workspace.read_text(
        result.markdown_link,
        max_chars=1000,
    ).text


def test_fetch_action_result_omits_source_url_and_emits_workspace_signal(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    bus = SignalBus()
    executor = WebFetchExecutor(
        extractor=WebExtractor.TRAFILATURA,
        service=WebCapabilityService(
            workspace=workspace,
            settings=WebSettings(),
            runtime_env={},
            process_runner=_FetchRunner(),
        ),
        bus=bus,
    )

    result = executor.execute(
        _fetch_execution(),
        ActionExecutionContext(
            control=ActionExecutionControl(deadline=monotonic() + 30),
        ),
    )

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload["markdown_link"] == "workspace:web/pages/article.md"
    assert result.payload["excerpt"] == "Readable page excerpt"
    assert "url" not in result.payload
    signals = bus.consume()
    assert len(signals) == 1
    assert signals[0].name == "context.workspace.sync"


def test_fetch_cancellation_after_worker_prevents_workspace_commit(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    service = WebCapabilityService(
        workspace=workspace,
        settings=WebSettings(),
        runtime_env={},
        process_runner=_FetchCancellingRunner(),
    )

    with pytest.raises(WebProcessTimeout) as error:
        service.fetch(
            extractor=WebExtractor.TRAFILATURA,
            url="https://example.com/article",
            target_link="workspace:web/pages/article.md",
            overwrite=False,
            expected_target_digest="",
            owner_turn_id="turn_1",
            control=ActionExecutionControl(deadline=monotonic() + 30),
        )

    assert error.value.reason == "runtime_transfer"
    assert workspace.snapshot().resources == ()


def test_disabled_web_actions_are_absent_from_effective_catalog(
    local_tmp: Path,
) -> None:
    catalog_root = local_tmp / "catalog"
    with builtin_action_catalog_root() as package_catalog:
        shutil.copytree(package_catalog / "web", catalog_root / "web")
    settings = WebSettings(
        search_by_kimi=KimiSearchSettings(enabled=False),
        fetch_with_defuddle=WebFetchSettings(enabled=False),
        fetch_with_trafilatura=WebFetchSettings(enabled=False),
    )
    engine = register_web_actions(
        ActionEngineBuilder(catalog_root),
        settings=settings,
        runtime_env={},
        workspace=_workspace(local_tmp),
        bus=SignalBus(),
    ).build()

    assert "web" not in engine.domain_names()
    assert engine.action_identifiers() == ()


class _SearchRunner(ControlledProcessRunner):
    def __init__(self, *, answer: str, result_count: int) -> None:
        self._answer = answer
        self._result_count = result_count

    def run(
        self,
        request: ProcessRequest,
        control: ActionExecutionControl,
    ) -> ProcessOutcome:
        del control
        assert request.inherit_env is False
        assert request.env is not None
        assert request.env["TINYSOUL_KIMI_SEARCH_API_KEY"] == "search-secret"
        assert request.env["PYTHONIOENCODING"] == "utf-8"
        assert "KIMI_API_KEY" not in request.env
        results = [
            {
                "title": f"Source {index}",
                "url": f"https://example.com/{index}",
                "snippet": f"Snippet {index}",
            }
            for index in range(self._result_count)
        ]
        return ProcessOutcome(
            status=ProcessStatus.COMPLETED,
            exit_code=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "answer": self._answer,
                    "results": results,
                    "usage": {"tool_calls": 1},
                }
            ),
        )


class _FetchRunner(ControlledProcessRunner):
    def run(
        self,
        request: ProcessRequest,
        control: ActionExecutionControl,
    ) -> ProcessOutcome:
        del control
        response = _stage_fetch(request)
        return ProcessOutcome(
            status=ProcessStatus.COMPLETED,
            exit_code=0,
            stdout=json.dumps(response),
        )


class _FetchCancellingRunner(ControlledProcessRunner):
    def run(
        self,
        request: ProcessRequest,
        control: ActionExecutionControl,
    ) -> ProcessOutcome:
        response = _stage_fetch(request)
        control.request_cancel("runtime_transfer")
        return ProcessOutcome(
            status=ProcessStatus.COMPLETED,
            exit_code=0,
            stdout=json.dumps(response),
        )


def _stage_fetch(request: ProcessRequest) -> dict[str, object]:
    assert request.stdin_text is not None
    payload = json.loads(request.stdin_text)
    output = Path(payload["output_path"])
    output.mkdir(parents=True)
    markdown = "# Example\n\nReadable page\n"
    (output / "document.md").write_text(markdown, encoding="utf-8")
    return {
        "ok": True,
        "markdown_file": "document.md",
        "extractor": "trafilatura",
        "title": "Example",
        "excerpt": "Readable page excerpt",
        "content_chars": len(markdown),
        "remote_image_count": 0,
        "warning_codes": [],
    }


def _search_execution() -> ActionExecution:
    with builtin_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action(WEB_SEARCH_KIMI_ACTION)
    return ActionExecution(
        action=action,
        call=ActionCall(
            call_id="call_1",
            action_name=WEB_SEARCH_KIMI_ACTION,
            params={"query": "current topic"},
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id="invoke_1",
            batch_id="batch_1",
            scope=RunScope(),
            domain="web",
            turn_id="turn_1",
        ),
    )


def _fetch_execution() -> ActionExecution:
    with builtin_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action(
            WEB_FETCH_TRAFILATURA_ACTION
        )
    return ActionExecution(
        action=action,
        call=ActionCall(
            call_id="call_fetch",
            action_name=WEB_FETCH_TRAFILATURA_ACTION,
            params={
                "url": "https://example.com/article",
                "target_link": "workspace:web/pages/article.md",
            },
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id="invoke_fetch",
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
