"""Managed process primitives shared by synchronous and supervised actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Protocol

from tinysoul.action.core.errors import ActionContractError


@dataclass(frozen=True)
class ManagedProcessRequest:
    """One host-owned process invocation with captured output."""

    argv: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    inherit_env: bool = True
    stdin_text: str | None = None

    def __post_init__(self) -> None:
        if not self.argv or any(not isinstance(item, str) or not item for item in self.argv):
            raise ActionContractError("Managed process argv must contain non-empty strings")
        if self.cwd is not None and (not isinstance(self.cwd, str) or not self.cwd):
            raise ActionContractError("Managed process cwd must be text or None")
        if self.env is not None and any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            for key, value in self.env.items()
        ):
            raise ActionContractError("Managed process env must contain string values")
        if not isinstance(self.inherit_env, bool):
            raise ActionContractError("Managed process inherit_env must be boolean")
        if self.stdin_text is not None and not isinstance(self.stdin_text, str):
            raise ActionContractError("Managed process stdin must be text or None")


@dataclass(frozen=True)
class ProcessTextSlice:
    """One bounded incremental view over a captured UTF-8 stream."""

    text: str
    cursor: int
    next_cursor: int
    truncated: bool


class ManagedProcessStartError(Exception):
    """A managed child process could not be started."""


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
        capture_directory: TemporaryDirectory[str],
    ) -> None:
        self._process = process
        self._stdout = stdout_capture
        self._stderr = stderr_capture
        self._stdout_path = stdout_path
        self._stderr_path = stderr_path
        self._capture_directory = capture_directory
        self._lock = RLock()
        self._closed = False

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
            terminate_process_tree(self._process)

    def output_sizes(self) -> tuple[int, int]:
        with self._lock:
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

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self.running():
                self.terminate()
                try:
                    self._process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
            self._stdout.close()
            self._stderr.close()
            self._capture_directory.cleanup()
            self._closed = True

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
            raise ActionContractError("Managed process output boundaries are invalid")
        with self._lock:
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

    def start(self, request: ManagedProcessRequest) -> ManagedProcess:
        process_env: dict[str, str] | None = None
        if not request.inherit_env:
            process_env = dict(request.env or {})
        elif request.env is not None:
            process_env = {**os.environ, **request.env}
        capture_directory = TemporaryDirectory(prefix="tinysoul_process_")
        stdout_path = Path(capture_directory.name) / "stdout.log"
        stderr_path = Path(capture_directory.name) / "stderr.log"
        stdout_capture = stdout_path.open("w+b")
        stderr_capture = stderr_path.open("w+b")
        process_stdin = subprocess.PIPE if request.stdin_text is not None else subprocess.DEVNULL
        process: subprocess.Popen[str] | None = None
        try:
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
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
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
            if request.stdin_text is not None and process.stdin is not None:
                process.stdin.write(request.stdin_text)
                process.stdin.close()
        except OSError as exc:
            if process is not None:
                terminate_process_tree(process)
            stdout_capture.close()
            stderr_capture.close()
            capture_directory.cleanup()
            raise ManagedProcessStartError(str(exc)) from exc
        return ManagedProcess(
            process,
            stdout_capture=stdout_capture,
            stderr_capture=stderr_capture,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            capture_directory=capture_directory,
        )


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate one process group without raising cleanup failures."""

    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.killpg(process.pid, 9)
    except OSError:
        process.kill()


def _path_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_text(path: Path, *, max_bytes: int) -> tuple[str, bool]:
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            data = stream.read(max_bytes + 1)
    except OSError:
        return "", False
    has_more = size > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n"), has_more
