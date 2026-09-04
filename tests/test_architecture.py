from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
MAINLINE_PACKAGES = (
    "action",
    "context",
    "home",
    "loop",
    "memory",
    "runtime",
    "session",
    "workspace",
)


def test_mainline_and_kernel_packages_do_not_import_maintenance() -> None:
    violations: list[str] = []
    for package in MAINLINE_PACKAGES:
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
                    module == "tinysoul.maintenance"
                    or module.startswith("tinysoul.maintenance.")
                    for module in modules
                ):
                    violations.append(str(path.relative_to(PROJECT_ROOT)))
    assert violations == []


def test_app_builder_does_not_assemble_turn_kernel_details() -> None:
    source = (PROJECT_ROOT / "tinysoul" / "app" / "builder.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "Phase1Unit",
        "Phase2Unit",
        "Phase3Unit",
        "CycleRunner",
        "ContextSignalConsumer",
        "HomeMaintenanceActionController",
        "MemoryMaintenanceActionController",
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
            if isinstance(raised, ast.Name) and raised.id in {"ValueError", "TypeError"}:
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}:{raised.id}"
                )
    assert violations == []
