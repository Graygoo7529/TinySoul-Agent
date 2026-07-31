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
        capture_directory: TemporaryDirectory[str] | None,
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
            if self._process.poll() is None:
                try:
                    self._process.kill()
                except OSError:
                    pass
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass

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
            try:
                if self.running():
                    self.terminate()
                    if self.running():
                        self._process.kill()
                        self._process.wait()
            except Exception:
                pass
            try:
                self._stdout.close()
            except Exception:
                pass
            try:
                self._stderr.close()
            except Exception:
                pass
            if self._capture_directory is not None:
                try:
                    self._capture_directory.cleanup()
                except Exception:
                    pass
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
        process_stdin = subprocess.PIPE if request.stdin_text is not None else subprocess.DEVNULL
        process: subprocess.Popen[str] | None = None
        try:
            if capture_root is None:
                capture_directory = TemporaryDirectory(prefix="tinysoul_process_")
                root = Path(capture_directory.name)
            else:
                if not isinstance(capture_root, Path):
                    raise ActionContractError(
                        "Managed process capture root must be a Path or None"
                    )
                if capture_root.exists():
                    raise ActionContractError(
                        "Managed process capture root must not already exist"
                    )
                capture_root.mkdir(parents=True)
                root = capture_root
            stdout_path = root / "stdout.log"
            stderr_path = root / "stderr.log"
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
        except Exception as exc:
            if process is not None:
                terminate_process_tree(process)
            if stdout_capture is not None:
                stdout_capture.close()
            if stderr_capture is not None:
                stderr_capture.close()
            if capture_directory is not None:
                capture_directory.cleanup()
            if isinstance(exc, ActionContractError):
                raise
            raise ManagedProcessStartError(str(exc)) from exc
        assert stdout_capture is not None
        assert stderr_capture is not None
        return ManagedProcess(
            process,
            stdout_capture=stdout_capture,
            stderr_capture=stderr_capture,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            capture_directory=capture_directory,
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
            )
            if result.returncode == 0:
                return
        except OSError:
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
