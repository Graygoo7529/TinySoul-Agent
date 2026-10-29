"""Real process ownership, output retention and daily Workspace effects."""

import asyncio
import socket
import sys
import json
import shutil
from dataclasses import replace
from pathlib import Path
from time import monotonic

import pytest

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.json import dumps_json
from tinysoul.infra.network import NetworkMode, NetworkPolicy
from tinysoul.kernel.jobs import JobRegistry, JobRequestError, JobState
from tinysoul.kernel.loop.interaction.inbox import TurnInbox, WaitCondition, WaitReason, InboxKind, WakeReason
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
from tinysoul.plugins.execution.backend import ProcessJobBackend
from tinysoul.infra.process import ManagedProcessRequest, ManagedProcessRunner
from tinysoul.plugins.execution.failures import ExecutionRequestError
from tinysoul.infra.config import ConfigError
from tinysoul.plugins.execution.config import parse_execution_settings
from tinysoul.plugins.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.plugins.home.errors import AgentHomeContractError
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings
from tinysoul.plugins.workspace.errors import WorkspaceContractError
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.llm.protocol.messages import JsonPart
from tinysoul.prompts.plugins import execution as execution_text


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


@pytest.mark.parametrize("encoding", ["not-a-codec", "base64_codec", "hex_codec"])
def test_output_encoding_rejects_non_text_codecs(encoding):
    with pytest.raises(ConfigError):
        parse_execution_settings({"interpreters": {"python": {"output_encoding": encoding}}})


@pytest.mark.integration
async def test_final_output_limit_uses_normalized_log_bytes_after_root_exit(tmp_path):
    process = ManagedProcessRunner().start(
        ManagedProcessRequest((sys.executable, "-c", "import os; os.write(1, bytes.fromhex('d6d0cec4'))"), output_encoding="gbk"),
        capture_root=tmp_path / "logs",
    )
    backend = ProcessJobBackend("job", process, settings=ExecutionSettings(max_output_bytes=5), workspace_refs=(), result_refs=())
    try:
        assert await asyncio.to_thread(process.wait, 5) == 0
        snapshot = await backend.poll()
        assert snapshot.state is JobState.FAILED and snapshot.reason == "output_limit"
        assert backend.collect()["stdout"] == "中"
        assert (await backend.describe())["stdout_bytes"] == 6
    finally:
        await backend.close_execution()


@pytest.mark.skipif(sys.platform != "win32", reason="CMD source encoding")
async def test_unrepresentable_source_fails_before_job_start(tmp_path, monkeypatch):
    from tinysoul.plugins.execution import interpreters

    monkeypatch.setattr(interpreters, "text_encoding", lambda value: "ascii")
    engine, jobs, workspace, home = _owners(tmp_path, settings=ExecutionSettings(
        enabled=True, interpreters=(InterpreterSpec(Interpreter.CMD, "cmd"),)))
    workspace.write_text("workspace:source.cmd", "echo 中文")
    with pytest.raises(ExecutionRequestError):
        await engine.start(turn_id="2026-10-06/1000", interpreter="cmd", command=None,
            source_ref="workspace:source.cmd", args=(), cwd_ref="", interactive=False,
            home=home, operations=JoinedOperations())
    assert not jobs.ids("2026-10-06/1000")
    assert not (workspace.settings.root / "jobs").exists()


@pytest.mark.integration
async def test_running_job_output_is_readable_before_stdin_release(tmp_path):
    engine, jobs, workspace, home = _owners(tmp_path)
    inbox = TurnInbox()
    jobs.bind_inbox("2026-10-06/1000", inbox)
    backend = await _start(engine, workspace, home,
        "import os,sys\nos.write(1, '进行中'.encode('utf-8'))\n"
        "sys.stdin.buffer.read(1)\nos.write(1, '完成'.encode('utf-8'))\n", interactive=True)
    try:
        async with asyncio.timeout(5):
            while (first := backend.collect())["stdout"] != "进行中":
                await asyncio.sleep(0.01)
        assert jobs.snapshot("2026-10-06/1000", backend.job_id).state is JobState.RUNNING
        wake = await asyncio.wait_for(inbox.wait_for_cycle(
            WaitCondition(WaitReason.EVENT, 0, event_kind=InboxKind.JOB, deadline=monotonic() + 0.01)
        ), 2)
        assert wake.reason is WakeReason.TIMER
        assert (await backend.describe())["exit_code"] is None
        assert backend.collect() == first
        assert backend.write_stdin("x", close=True) == 1
        async with asyncio.timeout(5):
            await engine.wait("2026-10-06/1000", backend.job_id)
        assert backend.collect(stdout_cursor=first["stdout_cursor"])["stdout"] == "完成"
        ref = f"workspace:jobs/{backend.job_id}/logs/stdout.log"
        assert workspace.read_text(ref).text == "进行中完成"
    finally:
        await jobs.cleanup_turn("2026-10-06/1000")


@pytest.mark.integration
@pytest.mark.parametrize("interpreter", [Interpreter.PYTHON, Interpreter.POWERSHELL, Interpreter.CMD])
async def test_native_script_source_arguments_and_exit_status(tmp_path, interpreter):
    if interpreter is not Interpreter.PYTHON and sys.platform != "win32":
        pytest.skip("Windows interpreter")
    executable = sys.executable if interpreter is Interpreter.PYTHON else shutil.which(interpreter.value)
    if executable is None:
        pytest.skip("Interpreter unavailable")
    settings = ExecutionSettings(enabled=True, interpreters=(InterpreterSpec(interpreter, executable),))
    engine, jobs, workspace, home = _owners(tmp_path, settings=settings)
    if interpreter is Interpreter.PYTHON:
        source = "import sys,json\nprint(json.dumps(sys.argv[1:],ensure_ascii=False))\nsys.exit(7)"
        args = ("two words", "", 'a"b', "中文")
        expected = json.dumps(list(args), ensure_ascii=False)
    elif interpreter is Interpreter.POWERSHELL:
        source = 'param([string]$Name, [switch]$Flag)\n[Console]::WriteLine("中文|$Name|$Flag")\nexit 7'
        args = ("-Name", "two words", "-Flag")
        expected = "中文|two words|True"
    else:
        source = '@echo off\necho 中文^|%~1^|[%~2]^|%~3\nexit /b 7'
        args = ("two words", "", "plain")
        expected = "中文|two words|[]|plain"
    suffix = {Interpreter.PYTHON: ".py", Interpreter.POWERSHELL: ".ps1", Interpreter.CMD: ".cmd"}[interpreter]
    ref = f"workspace:source{suffix}"
    workspace.write_text(ref, source)
    backend = await engine.start(turn_id="2026-10-06/1000", interpreter=interpreter.value,
        command=None, source_ref=ref, args=args, cwd_ref="", interactive=False,
        home=home, operations=JoinedOperations())
    try:
        async with asyncio.timeout(10):
            await engine.wait("2026-10-06/1000", backend.job_id)
        output = backend.collect()
        assert output["exit_code"] == 7
        assert output["stdout"].strip() == expected
        assert workspace.read_text(ref).text == source
    finally:
        await jobs.cleanup_turn("2026-10-06/1000")


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows command line")
async def test_cmd_command_preserves_quoted_paths_and_explicit_output_encoding(tmp_path):
    executable = shutil.which("cmd")
    assert executable is not None
    engine, jobs, workspace, home = _owners(tmp_path, settings=ExecutionSettings(
        enabled=True, interpreters=(InterpreterSpec(Interpreter.CMD, executable),)))
    source = tmp_path / "script with spaces.py"
    source.write_text("import sys,json\nprint(json.dumps(sys.argv[1:],ensure_ascii=False))\nsys.exit(7)", encoding="utf-8")
    command = f'"{sys.executable}" "{source}" "two words" "" "a&b" "中文"'
    backend = await engine.start(turn_id="2026-10-06/1000", interpreter="cmd", command=command,
        source_ref=None, args=(), cwd_ref="", interactive=False,
        home=home, operations=JoinedOperations(), output_encoding="utf-8")
    try:
        async with asyncio.timeout(10):
            await engine.wait("2026-10-06/1000", backend.job_id)
        output = backend.collect()
        assert output["exit_code"] == 7
        assert json.loads(output["stdout"]) == ["two words", "", "a&b", "中文"]
    finally:
        await jobs.cleanup_turn("2026-10-06/1000")


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


@pytest.mark.parametrize(
    ("error_type", "feedback"),
    [
        (WorkspaceContractError, "Check the requested resource."),
        (AgentHomeContractError, "Choose an existing resource."),
        (JobRequestError, "Wait for the active work to finish."),
        (AgentHomeContractError, ""),
    ],
)
async def test_owner_feedback_reaches_execution_tool_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: (
        type[WorkspaceContractError] | type[AgentHomeContractError] | type[JobRequestError]
    ),
    feedback: str,
) -> None:
    engine, jobs, workspace, home = _owners(tmp_path)
    diagnostic = f"Internal diagnostic: {tmp_path / 'private-file'}"

    async def reject_start(**_kwargs: object) -> None:
        raise error_type(diagnostic, feedback=feedback)

    monkeypatch.setattr(engine, "start", reject_start)
    builder = ActionEngineBuilder(sample_catalog().with_actions(("execution.run",)))
    builder.register_executor(
        "execution.run",
        ExecutionActionExecutor(
            engine, ExecutionOperation.RUN, home=home,
            workspace=WorkspaceService(workspace),
        ),
    )
    actions = builder.build()
    turn_id = "2026-10-06/1000"
    prepared = actions.prepare_batch(
        (ActionCall("request", "execution.run", {
            "interpreter": "python", "source_ref": "workspace:input.py",
        }, 1),),
        scope=RunScope().push(RunLevel.TURN, turn_id),
    )
    results = await actions.run_batch(prepared.batch)
    result, = results
    failure = result.failure
    assert failure is not None
    assert failure.reason == "invalid_request" and failure.scope == "execution.action"
    assert failure.disposition is ActionFailureDisposition.CHANGE_REQUEST
    assert failure.feedback == (
        feedback or execution_text.THE_EXECUTION_REQUEST_IS_UNAVAILABLE_OR_INVALID
    )
    rendered, = actions.render_tool_results(results)
    part, = rendered.visible_message.parts
    assert isinstance(part, JsonPart)
    assert part.value["failure"] == failure.to_json()
    assert "Internal diagnostic" not in dumps_json(part.value)
    assert str(tmp_path) not in dumps_json(part.value)
    assert not jobs.ids(turn_id)


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
