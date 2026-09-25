from __future__ import annotations

from tests.action_helpers import builtin_catalog

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import pytest

from tinysoul.plugins.execution.actions import EXECUTION_ACTIONS
from tinysoul.kernel.action.backends.subprocess import (
    ControlledProcessRunner,
    ProcessRequest,
    ProcessStatus,
)
from tinysoul.kernel.action.engine import ActionEngineBuilder
from tinysoul.kernel.action.planning.normalization import ActionCallNormalizer
from tinysoul.kernel.action.execution.preparation import ActionExecutionBuilder
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.kernel.action.execution.executor import (
    ActionExecutionCancelled,
    ActionExecutionContext,
    ActionExecutionControl,
    ExecutorRegistry,
)
from tinysoul.kernel.action.result import ActionResult, ActionResultStatus
from tinysoul.kernel.action.execution.runner import ActionBatchRunner
from tinysoul.kernel.action.catalog.specs import (
    ActionExecutionSpec,
    ActionDomainSpec,
    ActionParallelPolicy,
    ActionRuntimeSpec,
    ActionVisibilitySpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.plugins.home.failures import HOME_RUNTIME_COPY_REQUIRED
from tinysoul.runtime import (
    RunScope,
    RuntimeException,
)
from tests.action_helpers import (
    FunctionActionEngineBuilder,
    FunctionActionExecutor,
    load_action_catalog,
)
from tests.support.process import PYTHON_WAIT_FOREVER


async def test_native_cooperative_timeout_does_not_block_later_group() -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.cooperative",
                runtime=ActionRuntimeSpec(
                    timeout_seconds=0.01,
                    parallel_policy=ActionParallelPolicy.SERIAL,
                ),
                execution=ActionExecutionSpec(
                    executor="test.cooperative",
                ),
            ),
            _action(
                "test.next",
                runtime=ActionRuntimeSpec(parallel_policy=ActionParallelPolicy.SERIAL),
                execution=ActionExecutionSpec(
                    executor="test.next",
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

    results = await ActionBatchRunner(
        executors=executors,
    ).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[0].failure is not None
    assert results[0].failure.reason == "execution_timeout"
    assert results[0].failure.scope == "action.timeout"
    assert results[0].frame_data["cancel_reason"] in {"deadline_expired", "timeout"}
    assert isinstance(results[0].frame_data["cancel_requested"], bool)
    assert results[0].frame_data["executor_leaked"] is False
    assert results[0].frame_data["late_success"] is False
    assert isinstance(results[0].frame_data["executor_started"], bool)
    assert results[1].status is ActionResultStatus.SUCCESS
    assert results[1].payload == {"started": True}


async def test_runner_preserves_cooperative_cancellation_identity() -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.cancelled",
                execution=ActionExecutionSpec(executor="test.cancelled"),
            ),
        ),
    )
    batch = _batch(
        catalog, (ToolCallRecord("call_1", "test.cancelled", {}, ToolKind.ACTION),)
    )
    cancellation = ActionExecutionCancelled("test_cancel")

    def cancel(execution, context):
        raise cancellation

    executors = ExecutorRegistry()
    executors.register("test.cancelled", FunctionActionExecutor(cancel))
    with pytest.raises(ActionExecutionCancelled) as raised:
        await ActionBatchRunner(executors=executors).run(
            batch, ActionExecutionContext()
        )
    assert raised.value is cancellation


async def test_action_deadline_cancels_async_io_and_joins_cleanup() -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.expired",
                runtime=ActionRuntimeSpec(timeout_seconds=0.01),
                execution=ActionExecutionSpec(executor="test.expired"),
            ),
        ),
    )
    batch = _batch(
        catalog, (ToolCallRecord("call_1", "test.expired", {}, ToolKind.ACTION),)
    )
    closed = asyncio.Event()

    class WaitingExecutor:
        async def execute(self, execution, context) -> ActionResult:
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
            raise AssertionError("unreachable")

    executors = ExecutorRegistry()
    executors.register("test.expired", WaitingExecutor())
    async with asyncio.timeout(2.0):
        results = await ActionBatchRunner(executors=executors).run(
            batch, ActionExecutionContext()
        )
    assert closed.is_set()
    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[0].failure is not None
    assert results[0].failure.reason == "execution_timeout"


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
            argv=(sys.executable, "-c", PYTHON_WAIT_FOREVER),
        ),
        control,
    )

    assert outcome.status is ProcessStatus.TIMED_OUT


async def test_runtime_transfer_terminates_parallel_subprocess_without_deadline(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "started.txt"
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _action(
                "test.interrupt",
                execution=ActionExecutionSpec(
                    executor="test.interrupt",
                ),
            ),
            _action(
                "test.process",
                execution=ActionExecutionSpec(
                    executor="test.process",
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
        (
            await ActionBatchRunner(
                executors=executors,
            ).run(batch, ActionExecutionContext())
        )

    assert monotonic() - started < 5.0


async def test_action_engine_assembles_catalog_hooks_and_runner() -> None:
    engine = (
        FunctionActionEngineBuilder(builtin_catalog())
        .register_function("core.answer", lambda execution, context: {"text": "done"})
        .register_function("core.ask", lambda execution, context: {"text": "choose"})
        .register_function("core.reason", lambda execution, context: {"ok": True})
        .register_function(
            "home.resource.delete", lambda execution, context: {"deleted": True}
        )
        .register_function(
            "home.resource.patch", lambda execution, context: {"patched": True}
        )
        .register_function("home.inspect", lambda execution, context: {"read": True})
        .register_function(
            "home.resource.write", lambda execution, context: {"written": True}
        )
        .register_function(
            "home.top.delete", lambda execution, context: {"deleted": True}
        )
        .register_function(
            "home.top.patch", lambda execution, context: {"patched": True}
        )
        .register_function("home.search", lambda execution, context: {"items": []})
        .register_function(
            "home.top.write", lambda execution, context: {"written": True}
        )
        .register_function("memory.search", lambda execution, context: {"items": []})
        .register_function("memory.memorize", lambda execution, context: {"digest": ""})
        .register_function("memory.inspect", lambda execution, context: {"text": ""})
        .register_function(
            "home.prompt_mount.patch", lambda execution, context: {"patched": True}
        )
        .register_function(
            "home.prompt_mount.write", lambda execution, context: {"written": True}
        )
        .register_function(
            "core.context.inspect",
            lambda execution, context: {},
            executor_id="context.inspect",
        )
        .register_function(
            "workspace.delete", lambda execution, context: {"deleted": True}
        )
        .register_function(
            "workspace.describe", lambda execution, context: {"described": True}
        )
        .register_function(
            "workspace.analyze", lambda execution, context: {"answer": "ok"}
        )
        .register_function("workspace.read", lambda execution, context: {"text": "ok"})
        .register_function("workspace.search", lambda execution, context: {"items": []})
        .register_function(
            "workspace.append", lambda execution, context: {"appended": True}
        )
        .register_function(
            "workspace.edit", lambda execution, context: {"patched": True}
        )
        .register_function(
            "workspace.restore", lambda execution, context: {"restored": True}
        )
        .register_function(
            "workspace.trash_list", lambda execution, context: {"items": []}
        )
        .register_function(
            "workspace.compose", lambda execution, context: {"rewritten": True}
        )
        .register_function(
            "workspace.list", lambda execution, context: {"scanned": True}
        )
        .mark_actions_unsupported(
            "core.session.organize",
            "core.wait",
            "core.job.status",
            "core.job.stop",
            "core.job.wait",
            *EXECUTION_ACTIONS,
            "workspace.write",
            "workspace.move",
            "workspace.mkdir",
            "workspace.tag",
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
    results = await engine.run_batch(batch_preparation.batch)

    assert scope_preparation.tool_scope is not None
    assert normalization.results == ()
    assert batch_preparation.results == ()
    assert results[0].status is ActionResultStatus.SUCCESS
    assert results[0].payload == {"text": "done"}
    assert (
        engine.render_tool_results(results)[0].visible_message.tool_name
        == "core.answer"
    )
    assert engine.render_result_trace_payload(results[0])["action"] == "core.answer"


def test_catalog_subprocess_does_not_implicitly_register_execution(
    tmp_path: Path,
) -> None:
    _write_catalog_action(
        tmp_path,
        executor_id="test.process",
        options="",
    )

    engine = ActionEngineBuilder(load_action_catalog(tmp_path)).build()
    assert engine.action_identifiers() == ()
    assert not engine.normalize(
        (ToolCallRecord("invoke", "test.action", {}, ToolKind.ACTION),)
    ).calls


def test_unsupported_action_is_removed_with_its_empty_domain(tmp_path: Path) -> None:
    _write_catalog_action(
        tmp_path,
        executor_id="test.action",
        options="",
    )

    engine = (
        ActionEngineBuilder(load_action_catalog(tmp_path))
        .mark_actions_unsupported("test.action")
        .build()
    )

    assert engine.domain_names() == ()
    assert engine.action_identifiers() == ()


@pytest.mark.parametrize(
    ("enabled", "supported", "available"),
    (
        (True, True, True),
        (False, True, False),
        (True, False, False),
        (False, False, False),
    ),
)
def test_action_availability_combines_policy_and_runtime_support(
    enabled: bool,
    supported: bool,
    available: bool,
) -> None:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            replace(
                _action(
                    "test.action",
                    execution=ActionExecutionSpec(
                        executor="test.action",
                    ),
                ),
                visibility=ActionVisibilitySpec(default=enabled),
            ),
        ),
    )
    builder = ActionEngineBuilder(catalog)
    if supported:
        builder.register_executor(
            "test.action",
            FunctionActionExecutor(lambda execution, context: {"ok": True}),
        )
    else:
        builder.mark_actions_unsupported("test.action")

    engine = builder.build()
    view = engine.view(("test.action",))
    actions = view.catalog_json()["actions"]
    assert isinstance(actions, list)
    projection = actions[0]
    assert isinstance(projection, dict)
    selection = projection["selection"]
    assert isinstance(selection, dict)

    assert view.action_identifiers() == (
        (("test", "test.action"),) if available else ()
    )
    assert selection["enabled"] is enabled
    assert projection["supported"] is supported
    assert projection["available"] is available


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
                    "from pathlib import Path; import sys,threading; "
                    "Path(sys.argv[1]).write_text('started'); "
                    "threading.Event().wait()"
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
    execution: ActionExecutionSpec,
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
        execution=execution,
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
    executor_id: str,
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
        "additionalProperties = false }\n"
        "\n"
        "[execution]\n"
        f'executor = "{executor_id}"\n'
        "\n"
        "[execution.options]\n"
        f"{options}\n",
        encoding="utf-8",
    )
