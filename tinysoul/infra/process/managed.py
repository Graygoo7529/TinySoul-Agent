"""Host process ownership, bounded stream access and termination."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
import os
from pathlib import Path
import subprocess
from typing import BinaryIO
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Protocol

from tinysoul.infra.concurrency import CleanupDiagnostic


class ProcessContractError(Exception):
    """The caller supplied an invalid process or stream contract."""


@dataclass(frozen=True)
class ManagedProcessRequest:
    """One host-owned process invocation with captured output."""

    argv: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    inherit_env: bool = True
    stdin_text: str | None = None
    interactive: bool = False

    def __post_init__(self) -> None:
        if not self.argv or any(
            not isinstance(item, str) or not item for item in self.argv
        ):
            raise ProcessContractError(
                "Managed process argv must contain non-empty strings"
            )
        if self.cwd is not None and (not isinstance(self.cwd, str) or not self.cwd):
            raise ProcessContractError("Managed process cwd must be text or None")
        if self.env is not None and any(
            not isinstance(key, str) or not key or not isinstance(value, str)
            for key, value in self.env.items()
        ):
            raise ProcessContractError("Managed process env must contain string values")
        if not isinstance(self.inherit_env, bool):
            raise ProcessContractError("Managed process inherit_env must be boolean")
        if self.stdin_text is not None and not isinstance(self.stdin_text, str):
            raise ProcessContractError("Managed process stdin must be text or None")
        if not isinstance(self.interactive, bool) or (
            self.interactive and self.stdin_text is not None
        ):
            raise ProcessContractError(
                "Interactive stdin cannot also use a fixed input document"
            )


@dataclass(frozen=True)
class ProcessTextSlice:
    """One bounded incremental view over a captured UTF-8 stream."""

    text: str
    cursor: int
    next_cursor: int
    truncated: bool


class ManagedProcessStartError(Exception):
    """A managed child process could not be started."""


class ManagedProcessCloseError(Exception):
    """Owned process resources did not all close within the bounded lifecycle."""


@dataclass(frozen=True)
class ManagedProcessOptions:
    """Host process lifecycle options shared by process-backed actions."""

    termination_wait_seconds: float = 1.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.termination_wait_seconds, bool)
            or not isinstance(self.termination_wait_seconds, (int, float))
            or not isfinite(self.termination_wait_seconds)
            or self.termination_wait_seconds < 0
        ):
            raise ProcessContractError(
                "Managed process termination wait must be a finite non-negative number"
            )


class CapturedOutput(Protocol):
    def close(self) -> None: ...

    def flush(self) -> None: ...


class ManagedProcess:
    """A live process handle with bounded observation and hard termination."""

    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        stdout_capture: CapturedOutput,
        stderr_capture: CapturedOutput,
        stdout_path: Path,
        stderr_path: Path,
        capture_directory: TemporaryDirectory[str] | None,
        options: ManagedProcessOptions,
    ) -> None:
        self._process = process
        self._stdout = stdout_capture
        self._stderr = stderr_capture
        self._stdout_path = stdout_path
        self._stderr_path = stderr_path
        self._capture_directory = capture_directory
        self._options = options
        self._lock = RLock()
        self._closed = False
        self._diagnostics: tuple[CleanupDiagnostic, ...] = ()

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def exit_code(self) -> int | None:
        return self._process.poll()

    def running(self) -> bool:
        return self._process.poll() is None

    def wait(self, timeout_seconds: float | None = None) -> int | None:
        try:
            return self._process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return None

    def terminate(self) -> None:
        with self._lock:
            last_error: Exception | None = None
            for _ in range(2):
                try:
                    if self._process.poll() is not None:
                        return
                    terminate_process_tree(self._process)
                    if self._process.poll() is None:
                        self._process.kill()
                    self._process.wait(timeout=self._options.termination_wait_seconds)
                    return
                except (OSError, subprocess.TimeoutExpired) as exc:
                    last_error = exc
            try:
                running = self._process.poll() is None
            except OSError as exc:
                raise ManagedProcessCloseError(
                    "Process state could not be read after bounded stop"
                ) from exc
            if running:
                raise ManagedProcessCloseError(
                    "Controlled process remains alive after bounded stop"
                ) from last_error

    def write_stdin(self, data: bytes, *, close: bool = False) -> int:
        """Accept a bounded nonblocking prefix; the caller owns any remainder."""
        if (
            not isinstance(data, bytes)
            or len(data) > 4096
            or not isinstance(close, bool)
        ):
            raise ProcessContractError("Process input must be at most 4096 bytes")
        with self._lock:
            stream = self._process.stdin
            if self._closed or stream is None or stream.closed or not self.running():
                raise ProcessContractError("Process stdin is unavailable")
            try:
                accepted = os.write(stream.fileno(), data) if data else 0
            except BlockingIOError:
                accepted = 0
            except (BrokenPipeError, OSError) as exc:
                raise ProcessContractError("Process stdin is closed") from exc
            if close and accepted == len(data):
                stream.close()
            return accepted

    def output_sizes(self) -> tuple[int, int]:
        with self._lock:
            if not self._closed:
                self._stdout.flush()
                self._stderr.flush()
            return _path_size(self._stdout_path), _path_size(self._stderr_path)

    def read_stdout(
        self,
        *,
        cursor: int,
        max_chars: int,
        max_bytes: int,
    ) -> ProcessTextSlice:
        return self._read_stream(
            self._stdout,
            self._stdout_path,
            cursor=cursor,
            max_chars=max_chars,
            max_bytes=max_bytes,
        )

    def read_stderr(
        self,
        *,
        cursor: int,
        max_chars: int,
        max_bytes: int,
    ) -> ProcessTextSlice:
        return self._read_stream(
            self._stderr,
            self._stderr_path,
            cursor=cursor,
            max_chars=max_chars,
            max_bytes=max_bytes,
        )

    def close(self) -> tuple[CleanupDiagnostic, ...]:
        with self._lock:
            if self._closed:
                return self._diagnostics
            # A failed stop keeps the handle open and retryable. Ancillary failures
            # cannot make a running process look closed.
            self.terminate()
            failures: list[CleanupDiagnostic] = []
            streams = (
                ("stdout", self._stdout),
                ("stderr", self._stderr),
                ("stdin", self._process.stdin),
            )
            for name, stream in streams:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception as exc:
                        failures.append(
                            CleanupDiagnostic(f"process.{name}", type(exc).__name__)
                        )
            if self._capture_directory is not None:
                try:
                    self._capture_directory.cleanup()
                except Exception as exc:
                    failures.append(
                        CleanupDiagnostic("process.capture", type(exc).__name__)
                    )
            self._closed = True
            self._diagnostics = tuple(failures)
            return self._diagnostics

    def _read_stream(
        self,
        stream: CapturedOutput,
        path: Path,
        *,
        cursor: int,
        max_chars: int,
        max_bytes: int,
    ) -> ProcessTextSlice:
        if cursor < 0 or max_chars <= 0 or max_bytes <= 0:
            raise ProcessContractError("Managed process output boundaries are invalid")
        with self._lock:
            if not self._closed:
                stream.flush()
            text, has_more_bytes = _read_text(path, max_bytes=max_bytes)
        effective_cursor = min(cursor, len(text))
        end = min(len(text), effective_cursor + max_chars)
        return ProcessTextSlice(
            text=text[effective_cursor:end],
            cursor=effective_cursor,
            next_cursor=end,
            truncated=end < len(text) or has_more_bytes,
        )

    def __enter__(self) -> "ManagedProcess":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class ManagedProcessRunner:
    """Start process-group-owned children without waiting for completion."""

    def __init__(self, options: ManagedProcessOptions | None = None) -> None:
        self._options = options or ManagedProcessOptions()

    def start(
        self,
        request: ManagedProcessRequest,
        *,
        capture_root: Path | None = None,
    ) -> ManagedProcess:
        process_env: dict[str, str] | None = None
        if not request.inherit_env:
            process_env = dict(request.env or {})
        elif request.env is not None:
            process_env = {**os.environ, **request.env}
        capture_directory: TemporaryDirectory[str] | None = None
        stdout_capture: CapturedOutput | None = None
        stderr_capture: CapturedOutput | None = None
        input_document: BinaryIO | None = None
        process_stdin: int | BinaryIO = (
            subprocess.PIPE if request.interactive else subprocess.DEVNULL
        )
        process: subprocess.Popen[str] | None = None
        try:
            if capture_root is None:
                capture_directory = TemporaryDirectory(prefix="tinysoul_process_")
                root = Path(capture_directory.name)
            else:
                if not isinstance(capture_root, Path):
                    raise ProcessContractError(
                        "Managed process capture root must be a Path or None"
                    )
                if capture_root.exists():
                    raise ProcessContractError(
                        "Managed process capture root must not already exist"
                    )
                capture_root.mkdir(parents=True)
                root = capture_root
            stdout_path = root / "stdout.log"
            stderr_path = root / "stderr.log"
            if request.stdin_text is not None:
                input_document = (root / "stdin.txt").open("w+b")
                input_document.write(request.stdin_text.encode("utf-8"))
                input_document.seek(0)
                process_stdin = input_document
            stdout_capture = stdout_path.open("w+b")
            stderr_capture = stderr_path.open("w+b")
            if os.name == "nt":
                process = subprocess.Popen(
                    list(request.argv),
                    cwd=request.cwd,
                    env=process_env,
                    stdin=process_stdin,
                    stdout=stdout_capture,
                    stderr=stderr_capture,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.CREATE_NO_WINDOW,
                )
            else:
                process = subprocess.Popen(
                    list(request.argv),
                    cwd=request.cwd,
                    env=process_env,
                    stdin=process_stdin,
                    stdout=stdout_capture,
                    stderr=stderr_capture,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    start_new_session=True,
                )
            if request.interactive and process.stdin is not None:
                os.set_blocking(process.stdin.fileno(), False)
        except Exception as exc:
            if process is not None:
                terminate_process_tree(process)
            if stdout_capture is not None:
                stdout_capture.close()
            if stderr_capture is not None:
                stderr_capture.close()
            if capture_directory is not None:
                capture_directory.cleanup()
            if isinstance(exc, ProcessContractError):
                raise
            raise ManagedProcessStartError(
                "Controlled process could not be started"
            ) from exc
        finally:
            if input_document is not None:
                input_document.close()
        assert stdout_capture is not None
        assert stderr_capture is not None
        return ManagedProcess(
            process,
            stdout_capture=stdout_capture,
            stderr_capture=stderr_capture,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            capture_directory=capture_directory,
            options=self._options,
        )


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Request hard termination of one process tree without waiting for reaping."""

    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=1.0,
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            process.kill()
        except OSError:
            pass
        return
    try:
        os.killpg(process.pid, 9)
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def _path_size(path: Path) -> int:
    return path.stat().st_size


def _read_text(path: Path, *, max_bytes: int) -> tuple[str, bool]:
    size = path.stat().st_size
    with path.open("rb") as stream:
        data = stream.read(max_bytes + 1)
    has_more = size > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n"), has_more
