from __future__ import annotations

import os
from pathlib import Path
from shutil import copytree

from tests.support import TestSupportConfigurationError
from tinysoul.gateway.project.initializer import ProjectConfigProfile, ProjectInitializer


def copy_initialized_project(
    destination: Path,
    *,
    config_profile: ProjectConfigProfile = ProjectConfigProfile.STANDARD,
    minimal_home: bool = False,
) -> Path:
    """Copy one isolated project from the per-run immutable template."""
    run_root_value = os.environ.get("PYTEST_TINYSOUL_RUN_ROOT", "").strip()
    if not run_root_value:
        raise TestSupportConfigurationError(
            "PYTEST_TINYSOUL_RUN_ROOT must be configured"
        )
    template = Path(run_root_value) / f"project-template-{config_profile.value}"
    if not template.exists():
        ProjectInitializer().initialize(template, config_profile=config_profile)

    def ignore(source: str, _names: list[str]) -> list[str]:
        return ["home"] if minimal_home and Path(source) == template else []

    copytree(template, destination, ignore=ignore)
    if minimal_home:
        # SDK behavior uses real Home owners without loading unrelated bundled skills.
        agent_file = destination / "home" / "agent" / "AGENT.md"
        agent_file.parent.mkdir(parents=True)
        agent_file.write_text("# Agent\nTest agent instructions.\n", encoding="utf-8")
    return destination
