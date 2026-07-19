"""Script-owned preparation for the shared supervised process manager."""

from __future__ import annotations

from pathlib import Path
import sys

from tinysoul.action.backends import ManagedProcessRequest
from tinysoul.capabilities.supervised_process import (
    build_supervised_process_environment,
)
from tinysoul.infra.filesystem import file_digest
from tinysoul.workspace import WorkspaceMirror

from .config import ScriptSettings
from .errors import ScriptContractError
from .models import ScriptLanguage, ScriptSource


class ScriptProcessPreparer:
    """Freeze one validated ScriptSource and build its fixed process request."""

    def __init__(
        self,
        *,
        source: ScriptSource,
        args: tuple[str, ...],
        settings: ScriptSettings,
    ) -> None:
        self._source = source
        self._args = args
        self._settings = settings

    def __call__(
        self,
        staging_root: Path,
        mirror: WorkspaceMirror,
    ) -> ManagedProcessRequest:
        source = self._source
        if source.link.startswith("workspace:"):
            baseline = next(
                (item for item in mirror.entries if item.link == source.link),
                None,
            )
            if baseline is None or baseline.digest != source.digest:
                raise ScriptContractError(
                    "Script Workspace source changed after policy validation"
                )
        source_root = staging_root / "source"
        source_root.mkdir()
        entry = source_root / f"entry{source.language.suffix}"
        entry.write_bytes(source.text.encode("utf-8"))
        if file_digest(entry) != source.snapshot_digest:
            raise ScriptContractError(
                "Script source changed after policy validation"
            )
        return ManagedProcessRequest(
            argv=(self._executable(source.language), str(entry), *self._args),
            cwd=str(mirror.root),
            env=build_supervised_process_environment(
                mirror.root,
                extra={
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUNBUFFERED": "1",
                },
            ),
            inherit_env=False,
        )

    def _executable(self, language: ScriptLanguage) -> str:
        if language is ScriptLanguage.PYTHON:
            return sys.executable
        return self._settings.bash.executable or "bash"
