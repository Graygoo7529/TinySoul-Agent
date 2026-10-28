"""Real process ownership, output retention and daily Workspace effects."""

import asyncio
import socket
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.network import NetworkMode, NetworkPolicy
from tinysoul.kernel.jobs import JobRegistry, JobRequestError, JobState
from tinysoul.kernel.action import ActionEngineBuilder, ActionCall, ActionFailureDisposition
from tests.support.actions import sample_catalog
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.plugins.execution.actions import (
    ExecutionActionExecutor, ExecutionOperation, register_execution_actions,
)
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.plugins.execution import (
    ExecutionSettings,
    Interpreter,
    InterpreterSpec,
)
from tinysoul.plugins.execution.engine import ExecutionEngine
from tinysoul.plugins.execution.failures import ExecutionRequestError
from tinysoul.plugins.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings
from tinysoul.plugins.workspace.services import WorkspaceService


def _owners(
    tmp_path: Path, *, capacity: int = 16, settings: ExecutionSettings | None = None
):
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace")
    ).build()
    home_root = tmp_path / "home"
    home_root.mkdir()
    home = HomeService(
        AgentHomeEngineBuilder(
            AgentHomeSettings(
                original_root=home_root,
                runtime_root=tmp_path / "runtime" / "home",
            )
        ).build()
    )
    settings = settings or ExecutionSettings(
        enabled=True,
        interpreters=(InterpreterSpec(Interpreter.PYTHON, sys.executable),),
    )
    jobs = JobRegistry(capacity=capacity)
    engine = ExecutionEngine(settings=settings, jobs=jobs, workspace=workspace)
    return engine, jobs, workspace, home


async def _start(
    engine, workspace, home, text: str, *, cwd_ref: str = "", interactive: bool = False
):
    ref = "workspace:input.py"
    workspace.write_text(ref, text, overwrite=True)
    return await engine.start(
        turn_id="2026-10-06/1000",
        interpreter="python",
        command=None,
        source_ref=ref,
        args=(),
        cwd_ref=cwd_ref,
        interactive=interactive,
        home=home,
        operations=JoinedOperations(),
    )


@pytest.mark.integration
async def test_real_workspace_effects_and_repeated_output_collection(
    tmp_path: Path,
) -> None:
    engine, jobs, workspace, home = _owners(tmp_path)
    backend = await _start(
        engine,
        workspace,
        home,
        "from pathlib import Path\nPath('result.txt').write_text('committed', encoding='utf-8')\nprint('abcdefghij')\n",
    )
    try:
        async with asyncio.timeout(10):
            await engine.wait("2026-10-06/1000", backend.job_id)
        assert (
            jobs.snapshot("2026-10-06/1000", backend.job_id).state is JobState.SUCCEEDED
        )
        result_path = workspace.settings.root / "jobs" / backend.job_id / "result.txt"
        assert result_path.read_text(encoding="utf-8") == "committed"
        first = backend.collect(max_chars=4)
        assert first["stdout"] == "abcd"
        assert first == backend.collect(max_chars=4)
        assert backend.collect(stdout_cursor=4, max_chars=4)["stdout"] == "efgh"
        assert not jobs.has_unresolved("2026-10-06/1000")
        await jobs.stop(
            "2026-10-06/1000", backend.job_id, operations=JoinedOperations()
        )
        assert (
            jobs.snapshot("2026-10-06/1000", backend.job_id).state is JobState.SUCCEEDED
        )
    finally:
        await jobs.cleanup_turn("2026-10-06/1000")
    assert result_path.exists()
    assert (result_path.parent / "logs" / "stdout.log").exists()


@pytest.mark.integration
@pytest.mark.parametrize("direct", [False, True])
async def test_interpreter_network_replaces_inherited_process_proxies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direct: bool,
) -> None:
    monkeypatch.setenv("ALL_PROXY", "http://host:8000")
    monkeypatch.setenv("HTTP_PROXY", "http://host:8000")
    policy = NetworkPolicy(NetworkMode.DIRECT) if direct else NetworkPolicy()
    settings = ExecutionSettings(
        enabled=True,
        network=NetworkPolicy(NetworkMode.OVERRIDE, https_proxy="http://project:9000"),
        interpreters=(
            InterpreterSpec(Interpreter.PYTHON, sys.executable, network=policy),
        ),
    )
    engine, jobs, workspace, home = _owners(tmp_path, settings=settings)
    expected = None if direct else "http://project:9000"
    backend = await _start(
        engine,
        workspace,
        home,
        "import os\ne = {k.lower(): v for k, v in os.environ.items()}\n"
        "assert e.get('path')\nassert 'all_proxy' not in e and 'http_proxy' not in e\n"
        f"assert e.get('https_proxy') == {expected!r}\nprint('network-ok')\n",
    )
    try:
        async with asyncio.timeout(10):
            await engine.wait("2026-10-06/1000", backend.job_id)
        assert (
            jobs.snapshot("2026-10-06/1000", backend.job_id).state is JobState.SUCCEEDED
        )
        assert "network-ok" in backend.collect()["stdout"]
    finally:
        await jobs.cleanup_turn("2026-10-06/1000")


@pytest.mark.integration
async def test_successful_root_closes_children_before_job_becomes_resolved(
    tmp_path: Path,
) -> None:
    engine, jobs, workspace, home = _owners(tmp_path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(8)
        child = (
            "import socket\nfrom pathlib import Path\n"
            f"with socket.create_connection({listener.getsockname()!r}) as connection:\n"
            " connection.settimeout(8)\n"
            " Path('child-ready.txt').write_text('kept')\n"
            " connection.sendall(b'ready')\n"
            " print('ready', flush=True)\n"
            " connection.recv(1)\n"
        )
        parent = (
            "import subprocess,sys\n"
            f"child = subprocess.Popen([sys.executable, '-c', {child!r}], "
            "stdout=subprocess.PIPE, text=True)\n"
            "assert child.stdout.readline() == 'ready\\n'\n"
        )
        backend = await _start(engine, workspace, home, parent)
        try:
            connection, _ = await asyncio.to_thread(listener.accept)
            with connection:
                connection.settimeout(1)
                assert connection.recv(5) == b"ready"
                async with asyncio.timeout(8):
                    await engine.wait("2026-10-06/1000", backend.job_id)
                assert (
                    jobs.snapshot("2026-10-06/1000", backend.job_id).state
                    is JobState.SUCCEEDED
                )
                assert not jobs.has_unresolved("2026-10-06/1000")
                try:
                    assert connection.recv(1) == b""
                except ConnectionResetError:
                    pass
                assert backend.collect()["exit_code"] == 0
        finally:
            await jobs.cleanup_turn("2026-10-06/1000")
        assert jobs.ids("2026-10-06/1000") == ()
        assert (
            workspace.root / "jobs" / backend.job_id / "child-ready.txt"
        ).read_text() == "kept"


@pytest.mark.integration
async def test_terminal_results_do_not_occupy_live_slot_but_capacity_is_retained(
    tmp_path: Path,
) -> None:
    engine, jobs, workspace, home = _owners(tmp_path, capacity=2)
    try:
        for _ in range(2):
            backend = await _start(engine, workspace, home, "print('done')")
            async with asyncio.timeout(10):
                await engine.wait("2026-10-06/1000", backend.job_id)
        with pytest.raises(JobRequestError):
            await _start(engine, workspace, home, "print('not admitted')")
        assert len(jobs.ids("2026-10-06/1000")) == 2
        with pytest.raises(JobRequestError):
            jobs.get("another-turn", backend.job_id)
    finally:
        await jobs.cleanup_turn("2026-10-06/1000")


@pytest.mark.integration
async def test_cancelled_bounded_run_stops_process_and_keeps_written_files(
    tmp_path: Path,
) -> None:
    engine, jobs, workspace, home = _owners(tmp_path)
    backend = await _start(
        engine,
        workspace,
        home,
        "from pathlib import Path\nimport threading\n"
        "Path('before-stop.txt').write_text('kept', encoding='utf-8')\n"
        "print('written', flush=True)\n"
        "threading.Event().wait()\n",
        cwd_ref="workspace:",
    )
    try:
        path = workspace.settings.root / "before-stop.txt"
        # Existence only proves the file was opened, not that write_text closed it.
        async with asyncio.timeout(10):
            while backend.collect()["stdout"] != "written\n":
                assert not jobs.snapshot(
                    "2026-10-06/1000", backend.job_id
                ).state.terminal
                await asyncio.sleep(0.01)
        waiter = asyncio.create_task(engine.wait("2026-10-06/1000", backend.job_id))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert (
            jobs.snapshot("2026-10-06/1000", backend.job_id).state is JobState.CANCELLED
        )
        assert not jobs.has_unresolved("2026-10-06/1000")
        assert path.read_text(encoding="utf-8") == "kept"
    finally:
        await jobs.cleanup_turn("2026-10-06/1000")


@pytest.mark.integration
async def test_interactive_input_reports_accepted_utf8_bytes_and_no_silence_inference(
    tmp_path: Path,
) -> None:
    engine, jobs, workspace, home = _owners(tmp_path)
    backend = await _start(
        engine, workspace, home, "import sys\nprint(sys.stdin.read())", interactive=True
    )
    try:
        # A silent process is RUNNING; no invented waiting_input state.
        assert (await backend.poll()).state is JobState.RUNNING
        assert backend.write_stdin("中文", close=True) == 6
        async with asyncio.timeout(10):
            await engine.wait("2026-10-06/1000", backend.job_id)
        assert backend.collect()["stdout"].strip() == "中文"
        with pytest.raises(ExecutionRequestError):
            backend.write_stdin("late")
    finally:
        await jobs.cleanup_turn("2026-10-06/1000")


@pytest.mark.parametrize(
    "names", [tuple(Interpreter), (Interpreter.PYTHON,), (Interpreter.CMD,), ()]
)
def test_runtime_interpreters_reach_effective_tools_only(
    tmp_path: Path, names: tuple[Interpreter, ...]
) -> None:
    settings = ExecutionSettings(
        enabled=True,
        interpreters=tuple(
            InterpreterSpec(name, sys.executable, enabled=name in names)
            for name in Interpreter
        ),
    )
    engine, _jobs, workspace, home = _owners(tmp_path, settings=settings)
    assert engine.available_interpreters == names
    baseline = sample_catalog()
    run = baseline.get_action("execution.run")
    catalog = ActionCatalog(
        domains=baseline.domains(),
        actions=tuple(
            replace(
                run, name=name, tool=replace(run.tool, name=name),
                execution=replace(run.execution, executor=name),
            )
            for name in (
                "execution.run", "execution.start", "execution.stdin", "execution.collect"
            )
        ),
    )
    actions = register_execution_actions(
        ActionEngineBuilder(catalog), engine=engine,
        home=home, workspace=WorkspaceService(workspace),
    ).build()
    assert "Available in this runtime:" not in str(actions.catalog_json())
    if not names:
        assert not actions.action_identifiers()
        return
    scope = actions.phase2_scope(("execution",)).tool_scope
    assert scope is not None
    for tool in scope.visible_tools():
        if tool.name in {"execution.run", "execution.start"}:
            assert (
                "Available in this runtime: " + ", ".join(names) + "."
            ) in tool.description
            assert catalog.get_action(tool.name).tool.description in tool.description
            assert tool.parameters == catalog.get_action(tool.name).tool.schema
            if names == (Interpreter.PYTHON,):
                assert "inline commands are unavailable" in tool.description
            elif names == (Interpreter.CMD,):
                assert "Inline commands use cmd" in tool.description
                assert "Python uses" not in tool.description
        else:
            assert "Available in this runtime:" not in tool.description


async def test_disabled_interpreter_has_bounded_corrective_feedback(
    tmp_path: Path,
) -> None:
    engine, jobs, workspace, home = _owners(tmp_path)
    with pytest.raises(ExecutionRequestError) as raised:
        await engine.start(
            turn_id="2026-10-06/1000",
            interpreter="bash",
            command="echo unavailable",
            source_ref=None,
            args=(),
            cwd_ref="",
            interactive=False,
            home=home,
            operations=JoinedOperations(),
        )

    assert "bash interpreter is not enabled" in raised.value.feedback
    assert "Available interpreters: python" in raised.value.feedback
    assert len(raised.value.feedback) <= 240
    assert not jobs.ids("2026-10-06/1000")

    action = ActionEngineBuilder(sample_catalog().with_actions(("execution.run",)))
    action.register_executor(
        "execution.run",
        ExecutionActionExecutor(
            engine, ExecutionOperation.RUN, home=home,
            workspace=WorkspaceService(workspace),
        ),
    )
    actions = action.build()
    prepared = actions.prepare_batch(
        (ActionCall("disabled", "execution.run", {
            "interpreter": "bash", "command": "echo unavailable",
        }, 1),),
        scope=RunScope().push(RunLevel.TURN, "2026-10-06/1000"),
    )
    result, = await actions.run_batch(prepared.batch)
    assert result.failure is not None
    assert result.failure.reason == "invalid_request"
    assert result.failure.scope == "execution.action"
    assert result.failure.disposition is ActionFailureDisposition.CHANGE_REQUEST
    assert result.failure.feedback == raised.value.feedback
    assert not jobs.ids("2026-10-06/1000")


@pytest.mark.integration
@pytest.mark.parametrize("reason", ["timeout", "output_limit"])
async def test_execution_limits_are_failed_job_reasons(
    tmp_path: Path, reason: str
) -> None:
    settings = ExecutionSettings(
        enabled=True,
        interpreters=(InterpreterSpec(Interpreter.PYTHON, sys.executable),),
    )
    settings = (
        replace(settings, max_runtime_seconds=1)
        if reason == "timeout"
        else replace(settings, max_output_bytes=1000)
    )
    engine, jobs, workspace, home = _owners(tmp_path, settings=settings)
    source = (
        "import threading\n"
        + ("print('x'*2000, flush=True)\n" if reason == "output_limit" else "")
        + "threading.Event().wait()"
    )
    backend = await _start(engine, workspace, home, source)
    try:
        async with asyncio.timeout(10):
            await engine.wait("2026-10-06/1000", backend.job_id)
        snapshot = jobs.snapshot("2026-10-06/1000", backend.job_id)
        assert snapshot.state is JobState.FAILED and snapshot.reason == reason
        assert not jobs.has_unresolved("2026-10-06/1000")
    finally:
        await jobs.cleanup_turn("2026-10-06/1000")
