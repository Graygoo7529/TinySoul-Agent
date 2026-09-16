"""Executable requirements for enabled Shell adapters."""

from tinysoul.infra import DependencyChecker, DependencyRequirement
from tinysoul.infra.config import ConfigError

from .config import ShellSettings


def shell_dependency_requirements(
    settings: ShellSettings,
) -> tuple[DependencyRequirement, ...]:
    if not settings.enabled:
        return ()
    requirements: list[DependencyRequirement] = []
    for name in ("powershell", "cmd", "bash"):
        adapter = getattr(settings, name)
        if adapter.enabled:
            requirements.append(
                DependencyRequirement(
                    id=f"shell.{name}",
                    executables=(adapter.executable,),
                )
            )
    return tuple(requirements)


def require_shell_dependencies(
    settings: ShellSettings,
    *,
    checker: DependencyChecker | None = None,
) -> None:
    effective = checker or DependencyChecker()
    for result in effective.check_all(shell_dependency_requirements(settings)):
        if result.available:
            continue
        raise ConfigError(
            "Enabled Shell capability dependency is unavailable",
            key=f"capabilities.dependencies.{result.requirement_id}",
            value=list(result.missing_executables),
            expected="installed executable",
        )
