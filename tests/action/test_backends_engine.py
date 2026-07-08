from __future__ import annotations

import sys
from pathlib import Path
from time import sleep

import pytest

from tinysoul.action.backends.native import NativeFunctionExecutor
from tinysoul.action.backends.script import TemporaryScriptExecutor
from tinysoul.action.backends.subprocess import SubprocessActionExecutor
from tinysoul.action.engine import ActionEngineBuilder
from tinysoul.action.core.call import ActionCallNormalizer, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.executor import ActionExecutionContext, ExecutorRegistry
from tinysoul.action.core.result import ActionResultStatus
from tinysoul.action.core.runner import ActionBatchRunner
from tinysoul.action.core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionParallelPolicy,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.infra.config import ConfigError
from tinysoul.runtime import RunScope


def test_native_cooperative_timeout_does_not_block_later_group() -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.cooperative",
                runtime=ActionRuntimeSpec(
                    timeout_seconds=0.01,
                    parallel_policy=ActionParallelPolicy.SERIAL,
                ),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler="test.cooperative",
                ),
            ),
            _action(
                "test.next",
                runtime=ActionRuntimeSpec(parallel_policy=ActionParallelPolicy.SERIAL),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler="test.next",
                ),
            ),
        ),
    )
    batch = _batch(
        catalog,
        (
            ToolCallRecord("call_1", "test.cooperative", {}, ToolKind.ACTION),
            ToolCallRecord("call_2", "test.next", {}, ToolKind.ACTION),
        ),
    )
    executors = ExecutorRegistry()
    executors.register(
        "test.cooperative",
        NativeFunctionExecutor(_cooperative_native_function),
    )
    executors.register(
        "test.next",
        NativeFunctionExecutor(lambda execution, context: {"started": True}),
    )

    results = ActionBatchRunner(
        executors=executors,
        cooperative_cancel_grace_seconds=0.1,
    ).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[0].frame_data["executor_leaked"] is False
    assert results[1].status is ActionResultStatus.SUCCESS
    assert results[1].payload == {"started": True}


def test_subprocess_executor_returns_success_payload() -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.echo",
                schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.SUBPROCESS,
                    handler="subprocess.default",
                    options={
                        "argv": [
                            sys.executable,
                            "-c",
                            "import json,sys; print(json.load(sys.stdin)['value'])",
                        ]
                    },
                ),
            ),
        ),
    )
    batch = _batch(
        catalog,
        (ToolCallRecord("call_1", "test.echo", {"value": "hello"}, ToolKind.ACTION),),
    )
    executors = ExecutorRegistry()
    executors.register("subprocess.default", SubprocessActionExecutor())

    results = ActionBatchRunner(executors=executors).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.SUCCESS
    assert results[0].payload["stdout"] == "hello\n"
    assert results[0].payload["exit_code"] == 0


def test_subprocess_executor_kills_timed_out_process() -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.sleep",
                runtime=ActionRuntimeSpec(timeout_seconds=0.05),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.SUBPROCESS,
                    handler="subprocess.default",
                    options={
                        "argv": [
                            sys.executable,
                            "-c",
                            "import time; time.sleep(1)",
                        ]
                    },
                ),
            ),
        ),
    )
    batch = _batch(
        catalog,
        (ToolCallRecord("call_1", "test.sleep", {}, ToolKind.ACTION),),
    )
    executors = ExecutorRegistry()
    executors.register("subprocess.default", SubprocessActionExecutor())

    results = ActionBatchRunner(executors=executors).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[0].frame_data["reason"] == "process_timeout"


def test_temporary_script_executor_runs_python_code() -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.script",
                schema={
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                    "required": ["code"],
                    "additionalProperties": False,
                },
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.SCRIPT,
                    handler="script.temporary",
                ),
            ),
        ),
    )
    batch = _batch(
        catalog,
        (ToolCallRecord("call_1", "test.script", {"code": "print('hi')"}, ToolKind.ACTION),),
    )
    executors = ExecutorRegistry()
    executors.register("script.temporary", TemporaryScriptExecutor())

    results = ActionBatchRunner(executors=executors).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.SUCCESS
    assert results[0].payload["stdout"] == "hi\n"


def test_action_engine_assembles_catalog_hooks_and_runner() -> None:
    engine = (
        ActionEngineBuilder(Path("tinysoul/action/builtin"))
        .register_native("core.answer", lambda execution, context: {"text": execution.call.params["text"]})
        .register_native("llm_step.context_task", lambda execution, context: {"ok": True})
        .register_native("home.resource.read", lambda execution, context: {"read": True})
        .register_native("workspace.delete", lambda execution, context: {"deleted": True})
        .register_native("workspace.describe", lambda execution, context: {"described": True})
        .register_native("workspace.patch", lambda execution, context: {"patched": True})
        .register_native("workspace.scan", lambda execution, context: {"scanned": True})
        .register_native("workspace.write", lambda execution, context: {"written": True})
        .build()
    )

    scope_preparation = engine.phase2_scope(("core",))
    normalization = engine.normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments={"text": "done"},
                kind=ToolKind.ACTION,
            ),
        )
    )
    batch_preparation = engine.prepare_batch(
        normalization.calls,
        scope=RunScope(),
        batch_id="batch_1",
    )
    results = engine.run_batch(batch_preparation.batch)

    assert scope_preparation.tool_scope is not None
    assert normalization.results == ()
    assert batch_preparation.results == ()
    assert results[0].status is ActionResultStatus.SUCCESS
    assert results[0].payload == {"text": "done"}
    assert engine.to_tool_result_messages(results)[0].tool_name == "core.answer"
    assert engine.render_result_trace_payload(results[0])["action"] == "core.answer"


def test_action_engine_validates_subprocess_options_at_load_time(tmp_path: Path) -> None:
    _write_catalog_action(
        tmp_path,
        backend_kind="subprocess",
        handler="subprocess.default",
        options='argv = "not-a-list"',
    )

    with pytest.raises(ConfigError) as error:
        ActionEngineBuilder(tmp_path).build()

    assert error.value.key.endswith("backend.options.argv")


def test_subprocess_stdin_uses_explicit_mode_option(tmp_path: Path) -> None:
    _write_catalog_action(
        tmp_path,
        backend_kind="subprocess",
        handler="subprocess.default",
        options='argv = ["python", "-c", "print(1)"]\nstdin = "literal"',
    )

    with pytest.raises(ConfigError) as error:
        ActionEngineBuilder(tmp_path).build()

    assert error.value.key.endswith("backend.options.stdin")


def _cooperative_native_function(execution, context):
    while True:
        context.control.check_cancelled()
        sleep(0.005)


def _action(
    name: str,
    *,
    schema=None,
    runtime: ActionRuntimeSpec | None = None,
    backend: ActionBackendSpec,
) -> ActionSpec:
    return ActionSpec(
        name=name,
        domain="test",
        tool=ActionToolSpec(
            name=name,
            description="Test action.",
            schema=schema
            or {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
        semantic=ActionSemanticSpec(),
        runtime=runtime or ActionRuntimeSpec(),
        backend=backend,
    )


def _batch(catalog: ActionCatalog, tool_calls: tuple[ToolCallRecord, ...]):
    normalization = ActionCallNormalizer().normalize(tool_calls, catalog=catalog)
    return ActionExecutionBuilder().build_batch(
        normalization.calls,
        catalog=catalog,
        scope=RunScope(),
        batch_id="batch_1",
    )


def _write_catalog_action(
    root: Path,
    *,
    backend_kind: str,
    handler: str,
    options: str,
) -> None:
    domain_dir = root / "test"
    action_dir = domain_dir / "actions"
    action_dir.mkdir(parents=True)
    (domain_dir / "domain.toml").write_text(
        'name = "test"\n'
        'description = "Test actions."\n'
        "\n"
        "[runtime]\n"
        "timeout_seconds = 1\n",
        encoding="utf-8",
    )
    (action_dir / "action.toml").write_text(
        'name = "test.action"\n'
        'domain = "test"\n'
        "\n"
        "[tool]\n"
        'description = "Test action."\n'
        'schema = { type = "object", properties = {}, required = [], additionalProperties = false }\n'
        "\n"
        "[backend]\n"
        f'kind = "{backend_kind}"\n'
        f'handler = "{handler}"\n'
        "\n"
        "[backend.options]\n"
        f"{options}\n",
        encoding="utf-8",
    )
