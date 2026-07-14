from __future__ import annotations

import sys
from pathlib import Path
from time import monotonic, sleep

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
from tinysoul.runtime import HOME_RUNTIME_COPY_REQUIRED, RunScope, RuntimeException


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
    assert results[0].frame_data["late_success"] is False
    assert isinstance(results[0].frame_data["cancel_requested"], bool)
    assert isinstance(results[0].frame_data["executor_started"], bool)
    assert results[1].status is ActionResultStatus.SUCCESS
    assert results[1].payload == {"started": True}


def test_native_timeout_before_worker_start_uses_stable_frame_data() -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.expired",
                runtime=ActionRuntimeSpec(timeout_seconds=0.001),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler="test.expired",
                ),
            ),
        ),
    )
    batch = _batch(
        catalog,
        (ToolCallRecord("call_1", "test.expired", {}, ToolKind.ACTION),),
    )
    executors = ExecutorRegistry()
    executors.register(
        "test.expired",
        NativeFunctionExecutor(lambda execution, context: {"started": True}),
    )
    runner = ActionBatchRunner(executors=executors)
    scheduled = runner._schedule_group(batch.executions)
    sleep(0.01)

    results = runner._run_group(scheduled, ActionExecutionContext()).results

    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[0].frame_data == {
        "reason": "deadline_before_start",
        "cancel_requested": False,
        "executor_started": False,
        "executor_leaked": False,
        "late_success": False,
    }


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


def test_runtime_transfer_terminates_parallel_subprocess_without_deadline(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "started.txt"
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.interrupt",
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler="test.interrupt",
                ),
            ),
            _action(
                "test.process",
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.SUBPROCESS,
                    handler="subprocess.default",
                    options={
                        "argv": [
                            sys.executable,
                            "-c",
                            (
                                "from pathlib import Path; import sys,time; "
                                "Path(sys.argv[1]).write_text('started'); "
                                "time.sleep(10)"
                            ),
                            str(marker),
                        ]
                    },
                ),
            ),
        ),
    )
    batch = _batch(
        catalog,
        (
            ToolCallRecord("call_1", "test.interrupt", {}, ToolKind.ACTION),
            ToolCallRecord("call_2", "test.process", {}, ToolKind.ACTION),
        ),
    )
    executors = ExecutorRegistry()

    def interrupt_after_process_starts(execution, context):
        deadline = monotonic() + 3.0
        while not marker.exists() and monotonic() < deadline:
            sleep(0.005)
        assert marker.exists()
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
        )

    executors.register(
        "test.interrupt",
        NativeFunctionExecutor(interrupt_after_process_starts),
    )
    executors.register("subprocess.default", SubprocessActionExecutor())
    started = monotonic()

    with pytest.raises(RuntimeException):
        ActionBatchRunner(
            executors=executors,
            process_cancel_grace_seconds=2.0,
        ).run(batch, ActionExecutionContext())

    assert monotonic() - started < 5.0


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
        ActionEngineBuilder(Path("tinysoul/action/catalog"))
        .register_native("context.trace.fold", lambda execution, context: {})
        .register_native("context.trace.inspect", lambda execution, context: {})
        .register_native("context.trace.recall", lambda execution, context: {})
        .register_native("core.answer", lambda execution, context: {"text": "done"})
        .register_native("core.reason", lambda execution, context: {"ok": True})
        .register_native("home.resource.delete", lambda execution, context: {"deleted": True})
        .register_native("home.resource.patch", lambda execution, context: {"patched": True})
        .register_native("home.resource.read", lambda execution, context: {"read": True})
        .register_native("home.resource.write", lambda execution, context: {"written": True})
        .register_native("home.top.delete", lambda execution, context: {"deleted": True})
        .register_native("home.top.patch", lambda execution, context: {"patched": True})
        .register_native("home.top.search", lambda execution, context: {"items": []})
        .register_native("home.top.write", lambda execution, context: {"written": True})
        .register_native("home.prompt_mount.patch", lambda execution, context: {"patched": True})
        .register_native("home.prompt_mount.write", lambda execution, context: {"written": True})
        .register_native("session.history.inspect", lambda execution, context: {})
        .register_native("session.history.recall", lambda execution, context: {})
        .register_native("workspace.delete", lambda execution, context: {"deleted": True})
        .register_native("workspace.describe", lambda execution, context: {"described": True})
        .register_native("workspace.patch", lambda execution, context: {"patched": True})
        .register_native("workspace.restore", lambda execution, context: {"restored": True})
        .register_native("workspace.trash.list", lambda execution, context: {"items": []})
        .register_native("workspace.rewrite", lambda execution, context: {"rewritten": True})
        .register_native("workspace.scan", lambda execution, context: {"scanned": True})
        .register_native("workspace.write", lambda execution, context: {"written": True})
        .build()
    )

    assert "home" in engine.domain_names()
    assert ("home", "home.top.write") in engine.action_identifiers()
    scope_preparation = engine.phase2_scope(("core",))
    normalization = engine.normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments={"guide_blocks": [{"text": "answer"}]},
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
        'schema = { type = "object", properties = {}, required = [], '
        'additionalProperties = false }\n'
        "\n"
        "[backend]\n"
        f'kind = "{backend_kind}"\n'
        f'handler = "{handler}"\n'
        "\n"
        "[backend.options]\n"
        f"{options}\n",
        encoding="utf-8",
    )
