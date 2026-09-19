from __future__ import annotations

import ast
from enum import StrEnum
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from tinysoul.kernel.action.failures import ActionFailureKind
from tinysoul.agent.failures import AgentFailureKind
from tinysoul.gateway.endpoint.failures import EndpointFailureKind
from tinysoul.kernel.context.failures import ContextFailureKind
from tinysoul.plugins.home.failures import AgentHomeFailureKind
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.kernel.loop.failures import LoopFailureKind
from tinysoul.plugins.reflection.failures import ReflectionFailureKind
from tinysoul.plugins.archive.failures import ArchiveFailureKind
from tinysoul.plugins.memory.failures import MemoryFailureKind
from tinysoul.plugins.session.failures import SessionFailureKind
from tinysoul.plugins.execution.failures import ExecutionFailureKind
from tinysoul.kernel.jobs.failures import JobFailureKind
from tinysoul.plugins.workspace.failures import WorkspaceFailureKind


@pytest.mark.parametrize(
    ("module", "failure_kind"),
    (
        ("action", ActionFailureKind),
        ("agent", AgentFailureKind),
        ("archive", ArchiveFailureKind),
        ("context", ContextFailureKind),
        ("endpoint", EndpointFailureKind),
        ("home", AgentHomeFailureKind),
        ("llm", LLMFailureKind),
        ("loop", LoopFailureKind),
        ("reflection", ReflectionFailureKind),
        ("memory", MemoryFailureKind),
        ("session", SessionFailureKind),
        ("execution", ExecutionFailureKind),
        ("jobs", JobFailureKind),
        ("workspace", WorkspaceFailureKind),
    ),
)
def test_runtime_failure_kind_values_are_module_qualified(
    module: str,
    failure_kind: type[StrEnum],
) -> None:
    prefix = f"{module}."
    for item in failure_kind:
        assert item.value.startswith(prefix)
        assert item.value != prefix


@pytest.mark.parametrize(
    ("owner", "allowed"),
    (
        ("infra", {"infra"}),
        ("runtime", {"infra", "runtime"}),
        ("llm", {"infra", "runtime", "llm"}),
        ("kernel", {"infra", "runtime", "llm", "kernel"}),
        ("plugins", {"infra", "runtime", "llm", "kernel", "plugins"}),
        (
            "environment",
            {"infra", "runtime", "llm", "kernel", "plugins", "environment"},
        ),
        (
            "agent",
            {"infra", "runtime", "llm", "kernel", "plugins", "environment", "agent"},
        ),
    ),
)
def test_foundation_imports_follow_ownership(owner: str, allowed: set[str]) -> None:
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    for path in (root / "tinysoul" / owner).rglob("*.py"):
        package = ".".join(path.relative_to(root).parts[:-1])
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    module = importlib.util.resolve_name(
                        "." * node.level + module, package
                    )
                names = (
                    [f"{module}.{alias.name}" for alias in node.names]
                    if module == "tinysoul"
                    else [module]
                )
            else:
                continue
            for name in names:
                parts = name.split(".")
                if (
                    len(parts) > 1
                    and parts[0] == "tinysoul"
                    and parts[1] not in allowed
                ):
                    violations.append(f"{path.relative_to(root)}:{node.lineno}: {name}")
    assert not violations, "\n".join(violations)


def test_package_imports_in_fresh_process() -> None:
    script = """
import importlib
import pkgutil
import tinysoul

for module in pkgutil.walk_packages(tinysoul.__path__, tinysoul.__name__ + '.'):
    importlib.import_module(module.name)
try:
    importlib.import_module('tinysoul.runtime.bridge.action')
except ModuleNotFoundError:
    pass
else:
    raise AssertionError('legacy bridge is still importable')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


PROJECT_ROOT = Path(__file__).parents[1]
MAINLINE_PACKAGES = (
    "kernel",
    "plugins/home",
    "plugins/memory",
    "runtime",
    "plugins/session",
    "plugins/workspace",
)


def test_mainline_and_kernel_packages_do_not_import_reflection() -> None:
    violations: list[str] = []
    for package in MAINLINE_PACKAGES:
        assert (PROJECT_ROOT / "tinysoul" / package).is_dir()
        for path in (PROJECT_ROOT / "tinysoul" / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules = (node.module or "",)
                else:
                    continue
                if any(
                    module == "tinysoul.plugins.reflection"
                    or module.startswith("tinysoul.plugins.reflection.")
                    for module in modules
                ):
                    violations.append(str(path.relative_to(PROJECT_ROOT)))
    assert violations == []


def test_agent_builder_does_not_assemble_turn_kernel_details() -> None:
    source = (
        PROJECT_ROOT / "tinysoul" / "agent" / "composition" / "builder.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "Phase1Unit",
        "Phase2Unit",
        "Phase3Unit",
        "CycleRunner",
        "ContextSignalConsumer",
        "HomeReflectionActionController",
        "MemoryReflectionActionController",
    )
    assert [name for name in forbidden if name in source] == []


def test_infra_config_does_not_raise_builtin_configuration_errors() -> None:
    violations: list[str] = []
    config_root = PROJECT_ROOT / "tinysoul" / "infra" / "config"
    for path in config_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(raised, ast.Name) and raised.id in {
                "ValueError",
                "TypeError",
            }:
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}:{raised.id}"
                )
    assert violations == []
