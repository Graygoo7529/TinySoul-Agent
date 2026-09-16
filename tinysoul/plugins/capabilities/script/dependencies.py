"""Dependency requirements for enabled Script languages."""

from __future__ import annotations

from tinysoul.infra import DependencyChecker, DependencyRequirement
from tinysoul.infra.config import ConfigError

from .config import ScriptSettings


def script_dependency_requirements(
    settings: ScriptSettings,
) -> tuple[DependencyRequirement, ...]:
    if not settings.enabled or not settings.bash.enabled:
        return ()
    executable = settings.bash.executable or "bash"
    return (
        DependencyRequirement(
            id="script.bash",
            executables=(executable,),
        ),
    )


def require_script_dependencies(
    settings: ScriptSettings,
    *,
    checker: DependencyChecker | None = None,
) -> None:
    effective = checker or DependencyChecker()
    for result in effective.check_all(script_dependency_requirements(settings)):
        if result.available:
            continue
        raise ConfigError(
            "Enabled Script capability dependency is unavailable",
            key=f"capabilities.dependencies.{result.requirement_id}",
            value=list(result.missing_executables),
            expected="installed executable",
        )
