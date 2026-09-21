"""Real process ownership, output retention and daily Workspace effects."""

import asyncio
from dataclasses import replace
from pathlib import Path
import socket
import sys

import pytest

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.kernel.jobs import JobRegistry, JobRequestError, JobState
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
    engine, workspace, home, text: str, *, cwd_link: str = "", interactive: bool = False
):
    link = "workspace:input.py"
    workspace.write_text(link, text, overwrite=True)
    return await engine.start(
        turn_id="turn",
        interpreter="python",
        command=None,
        source_link=link,
        args=(),
        cwd_link=cwd_link,
        interactive=interactive,
        home=home,
        operations=JoinedOperations(),
    )


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
            await engine.wait("turn", backend.job_id)
        assert jobs.snapshot("turn", backend.job_id).state is JobState.SUCCEEDED
        result_path = workspace.settings.root / "jobs" / backend.job_id / "result.txt"
        assert result_path.read_text(encoding="utf-8") == "committed"
        first = backend.collect(max_chars=4)
        assert first["stdout"] == "abcd"
        assert first == backend.collect(max_chars=4)
        assert backend.collect(stdout_cursor=4, max_chars=4)["stdout"] == "efgh"
        assert not jobs.has_unresolved("turn")
        await jobs.stop("turn", backend.job_id, operations=JoinedOperations())
        assert jobs.snapshot("turn", backend.job_id).state is JobState.SUCCEEDED
    finally:
        await jobs.cleanup_turn("turn")
    assert result_path.exists()
    assert (result_path.parent / "logs" / "stdout.log").exists()


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
            " connection.sendall(b'ready')\n"
            " Path('child-ready.txt').write_text('kept')\n"
            " connection.recv(1)\n"
        )
        parent = (
            "import subprocess,sys,time\nfrom pathlib import Path\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            "deadline = time.monotonic() + 8\n"
            "while not Path('child-ready.txt').exists() and time.monotonic() < deadline:\n"
            " time.sleep(0.01)\n"
        )
        backend = await _start(engine, workspace, home, parent)
        try:
            connection, _ = await asyncio.to_thread(listener.accept)
            with connection:
                connection.settimeout(1)
                assert connection.recv(5) == b"ready"
                async with asyncio.timeout(8):
                    await engine.wait("turn", backend.job_id)
                assert jobs.snapshot("turn", backend.job_id).state is JobState.SUCCEEDED
                assert not jobs.has_unresolved("turn")
                try:
                    assert connection.recv(1) == b""
                except ConnectionResetError:
                    pass
                assert backend.collect()["exit_code"] == 0
        finally:
            await jobs.cleanup_turn("turn")
        assert jobs.ids("turn") == ()
        assert (
            workspace.root / "jobs" / backend.job_id / "child-ready.txt"
        ).read_text() == "kept"


async def test_terminal_results_do_not_occupy_live_slot_but_capacity_is_retained(
    tmp_path: Path,
) -> None:
    engine, jobs, workspace, home = _owners(tmp_path, capacity=2)
    try:
        for _ in range(2):
            backend = await _start(engine, workspace, home, "print('done')")
            async with asyncio.timeout(10):
                await engine.wait("turn", backend.job_id)
        with pytest.raises(JobRequestError):
            await _start(engine, workspace, home, "print('not admitted')")
        assert len(jobs.ids("turn")) == 2
        with pytest.raises(JobRequestError):
            jobs.get("another-turn", backend.job_id)
    finally:
        await jobs.cleanup_turn("turn")


async def test_cancelled_bounded_run_stops_process_and_keeps_written_files(
    tmp_path: Path,
) -> None:
    engine, jobs, workspace, home = _owners(tmp_path)
    backend = await _start(
        engine,
        workspace,
        home,
        "from pathlib import Path\nimport threading\nPath('before-stop.txt').write_text('kept')\nthreading.Event().wait()\n",
        cwd_link="workspace:",
    )
    try:
        path = workspace.settings.root / "before-stop.txt"
        async with asyncio.timeout(10):
            while not path.exists():
                await asyncio.sleep(0.01)
        waiter = asyncio.create_task(engine.wait("turn", backend.job_id))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert jobs.snapshot("turn", backend.job_id).state is JobState.CANCELLED
        assert not jobs.has_unresolved("turn")
        assert path.read_text() == "kept"
    finally:
        await jobs.cleanup_turn("turn")


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
            await engine.wait("turn", backend.job_id)
        assert backend.collect()["stdout"].strip() == "中文"
        with pytest.raises(ExecutionRequestError):
            backend.write_stdin("late")
    finally:
        await jobs.cleanup_turn("turn")


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
            await engine.wait("turn", backend.job_id)
        snapshot = jobs.snapshot("turn", backend.job_id)
        assert snapshot.state is JobState.FAILED and snapshot.reason == reason
        assert not jobs.has_unresolved("turn")
    finally:
        await jobs.cleanup_turn("turn")
