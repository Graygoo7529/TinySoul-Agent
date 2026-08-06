from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep
from typing import cast

import pytest

from tinysoul.capabilities.script import SCRIPT_ACTIONS
from tinysoul.capabilities.shell import SHELL_ACTIONS
from tinysoul.capabilities.supervised_process import EXECUTION_LIFECYCLE_ACTIONS
from tinysoul.action.backends import process as process_backend
from tinysoul.action.backends.process import (
    ManagedProcess,
    ManagedProcessOptions,
    ManagedProcessRequest,
    ManagedProcessRunner,
)
from tinysoul.action.backends.subprocess import (
    ControlledProcessRunner,
    ProcessRequest,
    ProcessStatus,
)
from tinysoul.action.engine import ActionEngineBuilder
from tinysoul.action.core.call import ActionCallNormalizer, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.errors import ActionContractError
from tinysoul.action.core.executor import (
    ActionExecutionContext,
    ActionExecutionControl,
    ExecutorRegistry,
)
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
from tinysoul.runtime import HOME_RUNTIME_COPY_REQUIRED, RunScope, RuntimeException
from tests.action_helpers import FunctionActionEngineBuilder, FunctionActionExecutor


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
        FunctionActionExecutor(_cooperative_native_function),
    )
    executors.register(
        "test.next",
        FunctionActionExecutor(lambda execution, context: {"started": True}),
    )

    results = ActionBatchRunner(
        executors=executors,
        cooperative_cancel_grace_seconds=0.1,
    ).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[0].failure is not None
    assert results[0].failure.reason == "cancelled"
    assert results[0].failure.scope == "action.timeout"
    assert results[0].frame_data["cancel_reason"] in {"deadline_expired", "timeout"}
    assert isinstance(results[0].frame_data["cancel_requested"], bool)
    assert results[0].frame_data["executor_leaked"] is False
    assert results[0].frame_data["late_success"] is False
    assert isinstance(results[0].frame_data["executor_started"], bool)
    assert results[1].status is ActionResultStatus.SUCCESS
    assert results[1].payload == {"started": True}


def test_runner_maps_cooperative_cancellation_to_timeout() -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.cancelled",
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler="test.cancelled",
                ),
            ),
        ),
    )
    batch = _batch(
        catalog,
        (ToolCallRecord("call_1", "test.cancelled", {}, ToolKind.ACTION),),
    )

    def cancel(execution, context):
        context.control.request_cancel("test_cancel")
        context.control.check_cancelled()
        raise AssertionError("Cancellation check did not stop execution")

    executors = ExecutorRegistry()
    executors.register("test.cancelled", FunctionActionExecutor(cancel))

    result = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )[0]

    assert result.status is ActionResultStatus.TIMEOUT
    assert result.failure is not None
    assert result.failure.reason == "cancelled"
    assert result.failure.scope == "action.timeout"
    assert result.frame_data == {
        "cancel_reason": "test_cancel",
        "cancel_requested": True,
        "executor_started": True,
        "executor_leaked": False,
        "late_success": False,
    }


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
        FunctionActionExecutor(lambda execution, context: {"started": True}),
    )
    runner = ActionBatchRunner(executors=executors)
    scheduled = runner._schedule_group(batch.executions)
    sleep(0.01)

    results = runner._run_group(scheduled, ActionExecutionContext()).results

    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[0].failure is not None
    assert results[0].failure.reason == "deadline_before_start"
    assert results[0].frame_data == {
        "cancel_requested": False,
        "executor_started": False,
        "executor_leaked": False,
        "late_success": False,
    }


def test_controlled_process_runner_returns_success_output() -> None:
    outcome = ControlledProcessRunner().run(
        ProcessRequest(
            argv=(
                sys.executable,
                "-c",
                "import json,sys; print(json.load(sys.stdin)['value'])",
            ),
            stdin_text='{"value":"hello"}',
        ),
        ActionExecutionContext().control,
    )

    assert outcome.status is ProcessStatus.COMPLETED
    assert outcome.exit_code == 0
    assert outcome.stdout == "hello\n"


def test_managed_process_preserves_caller_owned_capture_directory(
    tmp_path: Path,
) -> None:
    capture_root = tmp_path / "job-logs"
    process = ManagedProcessRunner().start(
        ManagedProcessRequest(
            argv=(sys.executable, "-c", "print('captured')"),
        ),
        capture_root=capture_root,
    )

    assert process.wait(5.0) == 0
    process.close()

    assert (capture_root / "stdout.log").read_text(encoding="utf-8") == "captured\n"
    assert (capture_root / "stderr.log").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize("value", [-1.0, True, "1.0", float("nan"), float("inf")])
def test_managed_process_options_reject_invalid_termination_wait(value) -> None:
    with pytest.raises(ActionContractError):
        ManagedProcessOptions(termination_wait_seconds=value)


def test_managed_process_terminate_uses_configured_wait(
    monkeypatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess()
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    managed = ManagedProcess(
        cast(subprocess.Popen[str], process),
        stdout_capture=_FakeCapture(),
        stderr_capture=_FakeCapture(),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        capture_directory=None,
        options=ManagedProcessOptions(termination_wait_seconds=0.25),
    )
    monkeypatch.setattr(process_backend, "terminate_process_tree", lambda _process: None)

    managed.terminate()

    assert process.wait_timeouts == [0.25]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows termination fallback")
def test_managed_process_falls_back_when_taskkill_is_denied(monkeypatch) -> None:
    process = ManagedProcessRunner().start(
        ManagedProcessRequest(
            argv=(sys.executable, "-c", "import time; time.sleep(30)"),
        )
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode=1),
    )

    try:
        process.terminate()
        assert process.running() is False
    finally:
        process.close()


def test_controlled_process_runner_returns_bounded_output() -> None:
    outcome = ControlledProcessRunner().run(
        ProcessRequest(
            argv=(
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.stdout.write('abcdefgh'); "
                    "sys.stderr.write('uvwxyz')"
                ),
            ),
            stdout_limit=4,
            stderr_limit=3,
        ),
        ActionExecutionContext().control,
    )

    assert outcome.status is ProcessStatus.COMPLETED
    assert outcome.stdout == "abcd"
    assert outcome.stderr == "uvw"
    assert outcome.stdout_truncated is True
    assert outcome.stderr_truncated is True


def test_controlled_process_runner_kills_timed_out_process() -> None:
    control = ActionExecutionControl(deadline=monotonic() + 0.05)
    outcome = ControlledProcessRunner().run(
        ProcessRequest(
            argv=(sys.executable, "-c", "import time; time.sleep(1)"),
        ),
        control,
    )

    assert outcome.status is ProcessStatus.TIMED_OUT


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
                    handler="test.process",
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
        FunctionActionExecutor(interrupt_after_process_starts),
    )
    executors.register(
        "test.process",
        FunctionActionExecutor(
            lambda execution, context: _run_controlled_process(
                context,
                marker=marker,
            )
        ),
    )
    started = monotonic()

    with pytest.raises(RuntimeException):
        ActionBatchRunner(
            executors=executors,
            process_cancel_grace_seconds=2.0,
        ).run(batch, ActionExecutionContext())

    assert monotonic() - started < 5.0


def test_action_engine_assembles_catalog_hooks_and_runner() -> None:
    engine = (
        FunctionActionEngineBuilder(Path("tinysoul/action/catalog"))
        .register_function("core.answer", lambda execution, context: {"text": "done"})
        .register_function("core.reason", lambda execution, context: {"ok": True})
        .register_function("home.resource.delete", lambda execution, context: {"deleted": True})
        .register_function("home.resource.patch", lambda execution, context: {"patched": True})
        .register_function("home.resource.read", lambda execution, context: {"read": True})
        .register_function("home.resource.write", lambda execution, context: {"written": True})
        .register_function("home.top.delete", lambda execution, context: {"deleted": True})
        .register_function("home.top.patch", lambda execution, context: {"patched": True})
        .register_function("home.top.search", lambda execution, context: {"items": []})
            .register_function("home.top.write", lambda execution, context: {"written": True})
            .register_function("memory.inspect", lambda execution, context: {"items": []})
            .register_function("memory.memorize", lambda execution, context: {"digest": ""})
            .register_function("memory.recall", lambda execution, context: {"text": ""})
        .register_function("home.prompt_mount.patch", lambda execution, context: {"patched": True})
        .register_function("home.prompt_mount.write", lambda execution, context: {"written": True})
        .register_function("context.inspect", lambda execution, context: {})
        .register_function("session.inspect", lambda execution, context: {})
        .register_function("workspace.delete", lambda execution, context: {"deleted": True})
        .register_function("workspace.describe", lambda execution, context: {"described": True})
        .register_function("workspace.analyze", lambda execution, context: {"answer": "ok"})
        .register_function("workspace.read", lambda execution, context: {"text": "ok"})
        .register_function("workspace.search_text", lambda execution, context: {"items": []})
        .register_function("workspace.patch", lambda execution, context: {"patched": True})
        .register_function("workspace.restore", lambda execution, context: {"restored": True})
        .register_function("workspace.trash.list", lambda execution, context: {"items": []})
        .register_function("workspace.rewrite", lambda execution, context: {"rewritten": True})
        .register_function("workspace.scan", lambda execution, context: {"scanned": True})
        .register_function("workspace.write", lambda execution, context: {"written": True})
            .disable_actions(
                *SCRIPT_ACTIONS,
                *SHELL_ACTIONS,
                *EXECUTION_LIFECYCLE_ACTIONS,
                "workspace.convert_with_markitdown",
            "workspace.convert_with_pypdf",
            "web.discover_pages",
            "web.fetch_with_defuddle",
            "web.fetch_with_trafilatura",
            "web.search_by_kimi",
        )
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
    assert engine.render_tool_results(results)[0].visible_message.tool_name == "core.answer"
    assert engine.render_result_trace_payload(results[0])["action"] == "core.answer"


def test_action_engine_requires_an_explicit_subprocess_handler(tmp_path: Path) -> None:
    _write_catalog_action(
        tmp_path,
        backend_kind="subprocess",
        handler="test.process",
        options="",
    )

    with pytest.raises(ActionContractError, match="test.process"):
        ActionEngineBuilder(tmp_path).build()


def test_disabled_action_is_removed_with_its_empty_domain(tmp_path: Path) -> None:
    _write_catalog_action(
        tmp_path,
        backend_kind="native",
        handler="test.action",
        options="",
    )

    engine = ActionEngineBuilder(tmp_path).disable_actions("test.action").build()

    assert engine.domain_names() == ()
    assert engine.action_identifiers() == ()


class _FakeCapture:
    def close(self) -> None:
        pass

    def flush(self) -> None:
        pass


class _FakeProcess:
    pid = 12345

    def __init__(self) -> None:
        self.exit_code: int | None = None
        self.wait_timeouts: list[float | None] = []

    def poll(self) -> int | None:
        return self.exit_code

    def kill(self) -> None:
        self.exit_code = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        return self.exit_code or 0


def _cooperative_native_function(execution, context):
    while True:
        context.control.check_cancelled()
        sleep(0.005)


def _run_controlled_process(
    context: ActionExecutionContext,
    *,
    marker: Path,
):
    outcome = ControlledProcessRunner().run(
        ProcessRequest(
            argv=(
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; import sys,time; "
                    "Path(sys.argv[1]).write_text('started'); "
                    "time.sleep(10)"
                ),
                str(marker),
            ),
        ),
        context.control,
    )
    return {"status": outcome.status.value}


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
