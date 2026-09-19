"""Process ownership is independent of Action and Job policy."""

from pathlib import Path
import subprocess
import sys
from typing import cast

import pytest

from tinysoul.infra.process import managed as process_backend
from tinysoul.infra.process import (
    ManagedProcess,
    ManagedProcessCloseError,
    ManagedProcessOptions,
    ManagedProcessRequest,
    ManagedProcessRunner,
    ProcessContractError,
)

PYTHON_WAIT_FOREVER = "import threading; threading.Event().wait()"


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
    monkeypatch.setattr(
        process_backend, "terminate_process_tree", lambda _process: None
    )

    managed.terminate()

    assert process.wait_timeouts == [0.25]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows termination fallback")
def test_managed_process_falls_back_when_taskkill_is_denied(monkeypatch) -> None:
    process = ManagedProcessRunner().start(
        ManagedProcessRequest(
            argv=(sys.executable, "-c", PYTHON_WAIT_FOREVER),
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


def test_failed_stop_keeps_execution_retryable_and_ancillary_failure_is_diagnostic(
    tmp_path: Path, monkeypatch
) -> None:
    class ResistantProcess(_FakeProcess):
        resistant = True

        def kill(self) -> None:
            if not self.resistant:
                super().kill()

        def wait(self, timeout=None) -> int:
            if self.resistant:
                raise subprocess.TimeoutExpired("private command", timeout or 0)
            return super().wait(timeout)

    class Capture(_FakeCapture):
        closes = 0

        def close(self) -> None:
            self.closes += 1
            raise OSError("private log path")

    child, capture = ResistantProcess(), Capture()
    managed = ManagedProcess(
        cast(subprocess.Popen[str], child),
        stdout_capture=capture,
        stderr_capture=_FakeCapture(),
        stdout_path=tmp_path / "out",
        stderr_path=tmp_path / "err",
        capture_directory=None,
        options=ManagedProcessOptions(0.01),
    )
    monkeypatch.setattr(process_backend, "terminate_process_tree", lambda _: None)
    with pytest.raises(ManagedProcessCloseError):
        managed.close()
    assert managed.running() and capture.closes == 0
    child.resistant = False
    diagnostics = managed.close()
    assert not managed.running() and capture.closes == 1
    assert diagnostics[0].resource == "process.stdout"
    assert "private" not in repr(diagnostics)
    assert managed.close() == diagnostics and capture.closes == 1


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
