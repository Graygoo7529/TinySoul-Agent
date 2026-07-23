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
    ActionFailureDisposition,
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
from tinysoul.capabilities.web.errors import (
    WebProcessingError,
    WebProcessTimeout,
    web_failure_disposition,
)
from tinysoul.capabilities.web.models import WebExtractor
from tinysoul.capabilities.web.network import FetchedPage, validate_public_https_url
from tinysoul.capabilities.web.service import (
    WebCapabilityService,
    _worker_failure_facts,
)
from tinysoul.capabilities.web.worker import (
    _extract_with_defuddle,
    _kimi_search_request_options,
    _normalize_search_result,
    _parse_kimi_tool_round,
    _read_bounded_json_file,
)
from tinysoul.infra.config import ConfigError
from tinysoul.infra import JsonValue, StagingDirectoryManager, dumps_json, to_json_object
from tinysoul.runtime import RunScope, SignalBus
from tinysoul.workspace import WorkspaceEngineBuilder, WorkspaceSettings


def test_web_config_parses_independent_kimi_search_and_fetch_actions() -> None:
    settings = parse_capabilities_settings(
        {
            "web": {
                "search_by_kimi": {
                    "enabled": True,
                    "max_output_tokens": 4_096,
                },
                "fetch_with_defuddle": {"enabled": True},
                "fetch_with_trafilatura": {"enabled": False},
            }
        }
    ).web

    assert settings.search_by_kimi.enabled is True
    assert settings.search_by_kimi.api_key_env == "KIMI_SEARCH_API_KEY"
    assert settings.search_by_kimi.model == "kimi-k2.6"
    assert settings.search_by_kimi.max_output_tokens == 4_096
    assert settings.fetch_with_defuddle.enabled is True
    assert settings.fetch_with_trafilatura.enabled is False


def test_web_config_rejects_obsolete_search_mode() -> None:
    with pytest.raises(ConfigError) as error:
        parse_capabilities_settings(
            {"web": {"search_by_kimi": {"mode": "answer"}}}
        )

    assert error.value.key == "capabilities.web.search_by_kimi.mode"


def test_web_config_accepts_supported_no_thinking_kimi_model() -> None:
    settings = parse_capabilities_settings(
        {"web": {"search_by_kimi": {"model": "kimi-k2.5"}}}
    ).web

    assert settings.search_by_kimi.model == "kimi-k2.5"


@pytest.mark.parametrize("model", ["kimi-k3", "kimi-k2.6-preview"])
def test_web_config_rejects_kimi_model_without_no_thinking_protocol(
    model: str,
) -> None:
    with pytest.raises(ConfigError) as error:
        parse_capabilities_settings(
            {"web": {"search_by_kimi": {"model": model}}}
        )

    assert error.value.key == "capabilities.web.search_by_kimi.model"


def test_enabled_kimi_search_requires_independent_credential() -> None:
    settings = WebSettings(search_by_kimi=KimiSearchSettings(enabled=True))

    with pytest.raises(ConfigError) as error:
        kimi_search_api_key(settings, {})

    assert error.value.key == "capabilities.web.search_by_kimi.api_key_env"


def test_kimi_worker_normalization_preserves_all_results_and_snippets() -> None:
    long_snippet = "detail " * 300
    normalized = _normalize_search_result(
        to_json_object(
            {
                "answer": "Complete answer",
                "results": [
                    {
                        "title": f"Source {index}",
                        "url": f"https://example.com/{index}",
                        "snippet": long_snippet,
                    }
                    for index in range(12)
                ],
            }
        )
    )

    results = cast(list[JsonValue], normalized["results"])
    assert len(results) == 12
    last = cast(dict[str, JsonValue], results[-1])
    assert last["snippet"] == long_snippet.strip()


@pytest.mark.parametrize("call_type", ["builtin_function", "function"])
def test_kimi_tool_round_preserves_assistant_and_raw_arguments(
    call_type: str,
) -> None:
    first_arguments = '{ "query": "current topic", "usage": {"total_tokens": 7} }'
    second_arguments = '{"query":"second source"}'
    assistant = to_json_object(
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "provider reasoning",
            "tool_calls": [
                {
                    "id": "search_1",
                    "type": call_type,
                    "function": {
                        "name": "$web_search",
                        "arguments": first_arguments,
                    },
                },
                {
                    "id": "search_2",
                    "type": call_type,
                    "function": {
                        "name": "$web_search",
                        "arguments": second_arguments,
                    },
                },
            ],
        }
    )

    tool_round = _parse_kimi_tool_round(assistant)

    assert tool_round.assistant_message == assistant
    assert tool_round.assistant_message["reasoning_content"] == "provider reasoning"
    assert tool_round.search_tokens == 7
    assert tool_round.tool_messages == (
        {
            "role": "tool",
            "tool_call_id": "search_1",
            "name": "$web_search",
            "content": first_arguments,
        },
        {
            "role": "tool",
            "tool_call_id": "search_2",
            "name": "$web_search",
            "content": second_arguments,
        },
    )


def test_kimi_tool_round_rejects_unknown_shape_with_bounded_facts() -> None:
    assistant = to_json_object(
        {
            "role": "assistant",
            "reasoning_content": "provider reasoning",
            "tool_calls": [
                {
                    "id": "search_1",
                    "type": "custom",
                    "function": {
                        "name": "$web_search",
                        "arguments": "{}",
                    },
                }
            ],
        }
    )

    with pytest.raises(WebProcessingError) as error:
        _parse_kimi_tool_round(assistant)

    assert error.value.reason == "provider_protocol_invalid"
    assert error.value.payload == {
        "call_index": 0,
        "has_reasoning_content": True,
        "has_function": True,
        "has_arguments": True,
        "call_type": "custom",
        "function_name": "$web_search",
    }


def test_kimi_tool_round_rejects_wrong_tool_and_invalid_arguments() -> None:
    wrong_tool = to_json_object(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "search_1",
                    "type": "builtin_function",
                    "function": {"name": "other_tool", "arguments": "{}"},
                }
            ],
        }
    )
    invalid_arguments = to_json_object(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "search_1",
                    "type": "builtin_function",
                    "function": {
                        "name": "$web_search",
                        "arguments": "not-json",
                    },
                }
            ],
        }
    )

    with pytest.raises(WebProcessingError, match="unsupported tool"):
        _parse_kimi_tool_round(wrong_tool)
    with pytest.raises(WebProcessingError, match="invalid tool arguments"):
        _parse_kimi_tool_round(invalid_arguments)


@pytest.mark.parametrize(
    ("tool_call", "message"),
    [
        (
            {
                "type": "builtin_function",
                "function": {"name": "$web_search", "arguments": "{}"},
            },
            "invalid tool call id",
        ),
        (
            {
                "id": "search_1",
                "type": "builtin_function",
                "function": {"name": "$web_search"},
            },
            "invalid tool arguments",
        ),
    ],
)
def test_kimi_tool_round_rejects_missing_required_fields(
    tool_call: dict[str, object],
    message: str,
) -> None:
    assistant = to_json_object(
        {"role": "assistant", "tool_calls": [tool_call]}
    )

    with pytest.raises(WebProcessingError, match=message):
        _parse_kimi_tool_round(assistant)


def test_kimi_search_always_disables_thinking() -> None:
    assert _kimi_search_request_options() == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }


@pytest.mark.parametrize(
    ("reason", "facts", "expected"),
    [
        (
            "network_request_failed",
            {},
            ActionFailureDisposition.RETRY_SAME,
        ),
        (
            "http_status_error",
            {"status_code": 503},
            ActionFailureDisposition.RETRY_SAME,
        ),
        (
            "http_status_error",
            {"status_code": 404},
            ActionFailureDisposition.CHANGE_REQUEST,
        ),
        (
            "invalid_url",
            {},
            ActionFailureDisposition.CHANGE_REQUEST,
        ),
        (
            "provider_protocol_invalid",
            {},
            ActionFailureDisposition.USE_FALLBACK,
        ),
        (
            "provider_request_failed",
            {"error_type": "RateLimitError"},
            ActionFailureDisposition.RETRY_SAME,
        ),
        (
            "provider_request_failed",
            {"error_type": "AuthenticationError"},
            ActionFailureDisposition.STOP,
        ),
        (
            "provider_request_failed",
            {"error_type": "BadRequestError"},
            ActionFailureDisposition.USE_FALLBACK,
        ),
        (
            "credential_unavailable",
            {},
            ActionFailureDisposition.STOP,
        ),
        (
            "unknown_web_failure",
            {},
            ActionFailureDisposition.STOP,
        ),
    ],
)
def test_web_failure_disposition_is_conservative_and_fact_aware(
    reason: str,
    facts: dict[str, JsonValue],
    expected: ActionFailureDisposition,
) -> None:
    assert web_failure_disposition(reason, facts) is expected


def test_worker_failure_facts_keep_only_bounded_classification_data() -> None:
    assert _worker_failure_facts(
        to_json_object(
            {
                "error_type": "HTTPStatusError",
                "status_code": 503,
                "content_type": "application/json",
                "has_function": True,
                "provider_response": "must not cross the worker boundary",
                "oversized_status": 10_000,
            }
        )
    ) == {
        "error_type": "HTTPStatusError",
        "content_type": "application/json",
        "has_function": True,
        "status_code": 503,
    }


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
        staging=_staging(local_tmp),
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


def test_kimi_worker_failure_preserves_only_safe_shape_facts(
    local_tmp: Path,
) -> None:
    service = WebCapabilityService(
        workspace=_workspace(local_tmp),
        settings=WebSettings(search_by_kimi=KimiSearchSettings(enabled=True)),
        runtime_env={},
        staging=_staging(local_tmp),
        kimi_api_key="search-secret",
        process_runner=_SearchProtocolFailureRunner(),
    )

    with pytest.raises(WebProcessingError) as error:
        service.search_by_kimi(
            query="current topic",
            invoke_id="invoke/1",
            call_id="call/1",
            owner_turn_id="turn_1",
            control=ActionExecutionControl(deadline=monotonic() + 30),
        )

    assert error.value.reason == "provider_protocol_invalid"
    assert error.value.payload == {
        "call_type": "builtin_function",
        "function_name": "$web_search",
        "has_reasoning_content": True,
        "has_function": True,
        "has_arguments": True,
        "call_index": 0,
    }

    action_result = KimiSearchExecutor(
        service=service,
        bus=SignalBus(),
    ).execute(
        _search_execution(),
        ActionExecutionContext(
            control=ActionExecutionControl(deadline=monotonic() + 30),
        ),
    )

    assert action_result.status is ActionResultStatus.FAILED
    assert action_result.payload == {}
    assert action_result.failure is not None
    assert action_result.failure.reason == "provider_protocol_invalid"
    assert action_result.failure.disposition is ActionFailureDisposition.USE_FALLBACK
    assert action_result.frame_data == {
        "call_type": "builtin_function",
        "function_name": "$web_search",
        "has_reasoning_content": True,
        "has_function": True,
        "has_arguments": True,
        "call_index": 0,
    }


def test_kimi_timeout_returns_model_visible_fallback_disposition(
    local_tmp: Path,
) -> None:
    service = WebCapabilityService(
        workspace=_workspace(local_tmp),
        settings=WebSettings(search_by_kimi=KimiSearchSettings(enabled=True)),
        runtime_env={},
        staging=_staging(local_tmp),
        kimi_api_key="search-secret",
        process_runner=_SearchTimeoutRunner(),
    )

    result = KimiSearchExecutor(service=service, bus=SignalBus()).execute(
        _search_execution(),
        ActionExecutionContext(
            control=ActionExecutionControl(deadline=monotonic() + 30),
        ),
    )

    assert result.status is ActionResultStatus.TIMEOUT
    assert result.payload == {}
    assert result.failure is not None
    assert result.failure.reason == "process_timeout"
    assert result.failure.disposition is ActionFailureDisposition.USE_FALLBACK
    assert result.frame_data == {"executor_leaked": False}


def test_oversized_kimi_search_spills_complete_answer_and_results(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    settings = WebSettings(
        search_by_kimi=KimiSearchSettings(
            enabled=True,
            max_inline_chars=1_000,
            max_result_chars=100_000,
        )
    )
    service = WebCapabilityService(
        workspace=workspace,
        settings=settings,
        runtime_env={},
        staging=_staging(local_tmp),
        kimi_api_key="search-secret",
        process_runner=_SearchRunner(
            answer="A" * 2_000,
            result_count=12,
            snippet_chars=1_200,
        ),
    )

    result = service.search_by_kimi(
        query="current topic",
        invoke_id="invoke/1",
        call_id="call/1",
        owner_turn_id="turn_1",
        control=ActionExecutionControl(deadline=monotonic() + 30),
    )

    assert result.payload["truncated"] is True
    assert result.payload["result_count"] == 12
    assert result.payload["answer"]
    assert isinstance(result.payload["results"], list)
    assert len(dumps_json(result.payload)) <= 1_000
    assert result.payload["see_more_at"] == "workspace:web/search/invoke-1-call-1.md"
    markdown = workspace.read_text(
        "workspace:web/search/invoke-1-call-1.md",
        max_chars=100_000,
    ).text
    assert "A" * 1_000 in markdown
    assert "## Results" in markdown
    assert "Source 11" in markdown
    assert "S" * 1_200 in markdown
    assert result.manifest is not None


def test_defuddle_staged_json_read_is_bounded(local_tmp: Path) -> None:
    result = local_tmp / "defuddle.json"
    result.write_bytes(b"x" * 101)

    with pytest.raises(WebProcessingError) as error:
        _read_bounded_json_file(result, max_bytes=100)

    assert error.value.reason == "staged_result_bytes_limit_exceeded"


def test_local_defuddle_cli_extracts_only_staged_html(local_tmp: Path) -> None:
    executable = shutil.which("defuddle")
    if executable is None:
        pytest.skip("Defuddle CLI is not installed")
    assert executable is not None
    manager = _staging(local_tmp)
    with manager.allocate("defuddle-test") as output_path:
        title, body = _extract_with_defuddle(
            FetchedPage(
                final_url="https://example.com/article",
                html=(
                    "<html><head><title>Local</title></head><body><main>"
                    "<h1>Heading</h1><p>Staged extraction content.</p>"
                    "</main></body></html>"
                ),
                content_type="text/html",
            ),
            output_path=output_path,
            executable=executable,
            max_output_chars=10_000,
        )

    assert title == "Local"
    assert "Staged extraction content" in body


def test_trafilatura_fetch_commits_only_workspace_markdown_and_metadata(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    service = WebCapabilityService(
        workspace=workspace,
        settings=WebSettings(),
        runtime_env={},
        staging=_staging(local_tmp),
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
            staging=_staging(local_tmp),
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
        staging=_staging(local_tmp),
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
        staging=_staging(local_tmp),
    ).build()

    assert "web" not in engine.domain_names()
    assert engine.action_identifiers() == ()


class _SearchRunner(ControlledProcessRunner):
    def __init__(
        self,
        *,
        answer: str,
        result_count: int,
        snippet_chars: int = 0,
    ) -> None:
        self._answer = answer
        self._result_count = result_count
        self._snippet_chars = snippet_chars

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
                "snippet": (
                    "S" * self._snippet_chars
                    if self._snippet_chars
                    else f"Snippet {index}"
                ),
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


class _SearchProtocolFailureRunner(ControlledProcessRunner):
    def run(
        self,
        request: ProcessRequest,
        control: ActionExecutionControl,
    ) -> ProcessOutcome:
        del request, control
        return ProcessOutcome(
            status=ProcessStatus.COMPLETED,
            exit_code=1,
            stdout=json.dumps(
                {
                    "ok": False,
                    "reason": "provider_protocol_invalid",
                    "message": "Kimi Search returned an unsupported tool call shape",
                    "call_type": "builtin_function",
                    "function_name": "$web_search",
                    "has_reasoning_content": True,
                    "has_function": True,
                    "has_arguments": True,
                    "call_index": 0,
                    "provider_response": "must not cross the worker boundary",
                }
            ),
        )


class _SearchTimeoutRunner(ControlledProcessRunner):
    def run(
        self,
        request: ProcessRequest,
        control: ActionExecutionControl,
    ) -> ProcessOutcome:
        del request, control
        return ProcessOutcome(status=ProcessStatus.TIMED_OUT)


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
    output.mkdir(parents=True, exist_ok=True)
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


def _staging(root: Path) -> StagingDirectoryManager:
    staging = StagingDirectoryManager(root.resolve())
    staging.prepare()
    return staging
