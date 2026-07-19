"""Shell-owned argv and Workspace cwd preparation."""

from __future__ import annotations

from base64 import b64encode
from pathlib import Path, PurePosixPath, PureWindowsPath

from tinysoul.action.backends import ManagedProcessRequest
from tinysoul.capabilities.supervised_process import (
    build_supervised_process_environment,
)
from tinysoul.workspace import WorkspaceMirror

from .config import ShellAdapterSettings
from .errors import ShellContractError
from .models import ShellInterpreter


class ShellProcessPreparer:
    def __init__(
        self,
        *,
        interpreter: ShellInterpreter,
        adapter: ShellAdapterSettings,
        command: str,
        working_directory: str,
    ) -> None:
        self._interpreter = interpreter
        self._adapter = adapter
        self._command = command
        self._working_directory = working_directory

    def __call__(
        self,
        staging_root: Path,
        mirror: WorkspaceMirror,
    ) -> ManagedProcessRequest:
        del staging_root
        cwd = resolve_shell_working_directory(mirror.root, self._working_directory)
        return ManagedProcessRequest(
            argv=self._argv(),
            cwd=str(cwd),
            env=build_supervised_process_environment(mirror.root),
            inherit_env=False,
        )

    def _argv(self) -> tuple[str, ...]:
        executable = self._adapter.executable
        if self._interpreter is ShellInterpreter.POWERSHELL:
            encoded = b64encode(self._command.encode("utf-16-le")).decode("ascii")
            return (
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            )
        if self._interpreter is ShellInterpreter.CMD:
            return executable, "/D", "/Q", "/S", "/C", self._command
        return executable, "--noprofile", "--norc", "-c", self._command


def resolve_shell_working_directory(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ShellContractError("Shell working_directory must be non-empty text")
    if "\x00" in value or "\\" in value:
        raise ShellContractError(
            "Shell working_directory must use a relative POSIX path"
        )
    windows = PureWindowsPath(value)
    parsed = PurePosixPath(value)
    if windows.drive or windows.root or parsed.is_absolute():
        raise ShellContractError("Shell working_directory must be relative")
    if any(part == ".." for part in parsed.parts):
        raise ShellContractError("Shell working_directory cannot escape the mirror")
    current = root
    for part in parsed.parts:
        if part in ("", "."):
            continue
        current = current / part
        if current.is_symlink():
            raise ShellContractError(
                "Shell working_directory cannot contain symbolic links"
            )
    try:
        root_resolved = root.resolve()
        resolved = current.resolve()
    except OSError as exc:
        raise ShellContractError(
            "Shell working_directory could not be resolved"
        ) from exc
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ShellContractError("Shell working_directory must stay in the mirror")
    if not current.is_dir():
        raise ShellContractError(
            "Shell working_directory must be an existing mirror directory"
        )
    return current
