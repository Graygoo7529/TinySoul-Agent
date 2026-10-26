from __future__ import annotations

import os
from pathlib import Path
from shutil import copytree

from tests.support import TestSupportConfigurationError
from tinysoul.gateway.project.initializer import (
    ProjectConfigProfile,
    ProjectInitializer,
)


def copy_initialized_project(
    destination: Path,
    *,
    config_profile: ProjectConfigProfile = ProjectConfigProfile.STANDARD,
    minimal_home: bool = False,
) -> Path:
    """Copy one isolated project from the per-run immutable template."""
    template = _template(config_profile)

    def ignore(source: str, _names: list[str]) -> list[str]:
        return ["home"] if minimal_home and Path(source) == template else []

    copytree(template, destination, ignore=ignore)
    if minimal_home:
        # SDK behavior uses real Home owners without loading unrelated bundled skills.
        agent_file = destination / "home" / "agent" / "AGENT.md"
        agent_file.parent.mkdir(parents=True)
        agent_file.write_text("# Agent\nTest agent instructions.\n", encoding="utf-8")
    return destination


def create_test_project(destination: Path) -> Path:
    """Real plugin resources with a small, test-owned model setup and Home."""
    template = _template(ProjectConfigProfile.STANDARD)

    def ignore(source: str, _names: list[str]) -> list[str]:
        path = Path(source)
        if path == template:
            return ["home"]
        if path == template / "configs":
            return ["llm"]
        return []

    copytree(template, destination, ignore=ignore)
    copytree(
        Path(__file__).resolve().parents[1] / "fixtures" / "project" / "llm",
        destination / "configs" / "llm",
    )
    agent = destination / "home" / "agent" / "AGENT.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("# Agent\nTest agent instructions.\n", encoding="utf-8")
    return destination


def _template(profile: ProjectConfigProfile) -> Path:
    run_root_value = os.environ.get("PYTEST_TINYSOUL_RUN_ROOT", "").strip()
    if not run_root_value:
        raise TestSupportConfigurationError(
            "PYTEST_TINYSOUL_RUN_ROOT must be configured"
        )
    template = Path(run_root_value) / f"project-template-{profile.value}"
    if not template.exists():
        ProjectInitializer().initialize(template, config_profile=profile)
    return template
