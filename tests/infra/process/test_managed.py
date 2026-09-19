"""Process ownership is independent of Action and Job policy."""

from pathlib import Path
import socket
import subprocess
import sys
from typing import cast

import pytest

from tinysoul.infra.process import (
    ManagedProcess,
    ManagedProcessCloseError,
    ManagedProcessOptions,
    ManagedProcessRequest,
    ManagedProcessRunner,
    ManagedProcessStartError,
    ProcessContractError,
)

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
    with pytest.raises(ProcessContractError):
        ManagedProcessOptions(termination_wait_seconds=value)


def test_managed_process_terminate_uses_configured_wait(
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
        scope=_FakeScope(process),
    )

    managed.terminate()

    assert process.wait_timeouts == [0.25]


class _FakeCapture:
    def close(self) -> None:
        pass

    def flush(self) -> None:
        pass


class _FakeProcess:
    pid = 12345
    stdin = None

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


class _FakeScope:
    def __init__(self, process: _FakeProcess) -> None:
        self.process = process

    def terminate(self, timeout_seconds: float) -> None:
        self.process.kill()
        if self.process.poll() is None:
            raise TimeoutError("Controlled execution remains alive")

    def close(self) -> None:
        pass


@pytest.mark.parametrize("root_exited", [False, True])
def test_failed_stop_keeps_execution_retryable_and_ancillary_failure_is_diagnostic(
    tmp_path: Path,
    root_exited: bool,
) -> None:
    class ResistantScope(_FakeScope):
        resistant = True

        def terminate(self, timeout_seconds: float) -> None:
            if self.resistant:
                raise TimeoutError("private descendant still running")
            super().terminate(timeout_seconds)

    class Capture(_FakeCapture):
        closes = 0

        def close(self) -> None:
            self.closes += 1
            raise OSError("private log path")

    child, capture = _FakeProcess(), Capture()
    if root_exited:
        child.exit_code = 0
    scope = ResistantScope(child)
    managed = ManagedProcess(
        cast(subprocess.Popen[str], child),
        stdout_capture=capture,
        stderr_capture=_FakeCapture(),
        stdout_path=tmp_path / "out",
        stderr_path=tmp_path / "err",
        capture_directory=None,
        options=ManagedProcessOptions(0.01),
        scope=scope,
    )
    with pytest.raises(ManagedProcessCloseError):
        managed.close()
    assert managed.running() is not root_exited
    assert capture.closes == 0
    scope.resistant = False
    diagnostics = managed.close()
    assert not managed.running() and capture.closes == 1
    assert diagnostics[0].resource == "process.stdout"
    assert "private" not in repr(diagnostics)
    assert managed.close() == diagnostics and capture.closes == 1


@pytest.mark.parametrize("root_exits", [False, True])
def test_close_stops_descendants_even_after_the_root_exits(
    tmp_path: Path,
    root_exits: bool,
) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(8)
        child = (
            "import socket\n"
            f"with socket.create_connection({listener.getsockname()!r}) as connection:\n"
            " connection.settimeout(8)\n"
            " connection.sendall(b'ready')\n"
            " connection.recv(1)\n"
        )
        parent = (
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            + ("" if root_exits else "time.sleep(8)\n")
        )
        with ManagedProcessRunner().start(
            ManagedProcessRequest((sys.executable, "-c", parent)),
            capture_root=tmp_path / "capture",
        ) as process:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                assert connection.recv(5) == b"ready"
                if root_exits:
                    assert process.wait(5) == 0
                process.close()
                # The child's socket stays open until the child actually exits.
                try:
                    assert connection.recv(1) == b""
                except ConnectionResetError:
                    pass  # Windows reports a forcibly closed peer as a reset.
                assert not process.running()
                if root_exits:
                    assert process.exit_code == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows suspended startup")
def test_failed_assignment_reaps_root_without_running_user_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tinysoul.infra.process.windows import WindowsProcessJob

    children: list[subprocess.Popen[str]] = []
    start = subprocess.Popen

    def capture(*args, **kwargs):
        process = start(*args, **kwargs)
        children.append(process)
        return process

    def reject(self: WindowsProcessJob, pid: int) -> None:
        raise OSError("private assignment failure")

    marker = tmp_path / "should-not-run"
    monkeypatch.setattr(subprocess, "Popen", capture)
    monkeypatch.setattr(WindowsProcessJob, "attach", reject)
    with pytest.raises(ManagedProcessStartError) as raised:
        ManagedProcessRunner().start(
            ManagedProcessRequest((
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            ))
        )
    assert len(children) == 1 and children[0].poll() is not None
    assert not marker.exists()
    assert "private" not in str(raised.value)


def test_interactive_input_and_fixed_large_input_do_not_block_start(
    tmp_path: Path,
) -> None:
    process = ManagedProcessRunner().start(
        ManagedProcessRequest(
            (sys.executable, "-c", "import sys; print(len(sys.stdin.buffer.read()))"),
            interactive=True,
        ),
        capture_root=tmp_path / "interactive",
    )
    try:
        assert process.write_stdin(b"hello", close=True) == 5
        assert process.wait(5) == 0
        assert (
            process.read_stdout(cursor=0, max_chars=100, max_bytes=100).text.strip()
            == "5"
        )
    finally:
        process.close()
    with ManagedProcessRunner().start(
        ManagedProcessRequest(
            (sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"),
            stdin_text="a" * 1_000_000,
        )
    ) as process:
        assert process.wait(5) == 0
        assert (
            process.read_stdout(cursor=0, max_chars=100, max_bytes=100).text.strip()
            == "1000000"
        )
