from __future__ import annotations

import os
from pathlib import Path
from shutil import copytree

from tinysoul.app import ProjectConfigProfile, ProjectInitializer
from tests.support import TestSupportConfigurationError


def copy_initialized_project(
    destination: Path,
    *,
    config_profile: ProjectConfigProfile = ProjectConfigProfile.STANDARD,
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
    copytree(template, destination)
    return destination
