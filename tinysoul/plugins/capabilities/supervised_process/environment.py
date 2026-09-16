"""Host-owned environment construction for supervised process jobs."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path


def build_supervised_process_environment(
    workspace_root: Path,
    *,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    allowed = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "HOME", "USERPROFILE")
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    env["TINYSOUL_WORKSPACE"] = str(workspace_root)
    if extra is not None:
        env.update(extra)
    return env
