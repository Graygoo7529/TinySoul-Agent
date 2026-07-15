from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import zipfile


def test_wheel_contains_resources_and_installed_package_initializes_project(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    wheel_root = tmp_path / "wheel"
    wheel_root.mkdir()
    environment = {
        **os.environ,
        "PIP_NO_CACHE_DIR": "1",
        "TMP": str(tmp_path),
        "TEMP": str(tmp_path),
    }
    subprocess.run(
        (
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--no-cache-dir",
            "--wheel-dir",
            str(wheel_root),
        ),
        cwd=project_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_root.glob("tinysoul-*.whl"))

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    assert "tinysoul/action/catalog/core/actions/answer.toml" in names
    assert "tinysoul/assets/project/configs/home.toml" in names
    assert "tinysoul/assets/project/.env.example" in names
    assert "tinysoul/assets/project/home/agent/user/user.md" in names
    assert "tinysoul/assets/project/home/what/entity/tiny-soul.md" in names
    assert "tinysoul/assets/project/home/how/tinysoul-docs/SKILL.md" in names
    assert (
        "tinysoul/assets/project/home/how/tinysoul-docs/references/"
        "use-tinysoul-context-and-link.md"
    ) in names
    assert any(name.endswith(".dist-info/entry_points.txt") for name in names)
    assert not any("/action/catalog/shell/" in name for name in names)
    assert not any("/action/catalog/script/" in name for name in names)
    assert "tinysoul/action/config.py" not in names

    installed = tmp_path / "installed"
    subprocess.run(
        (
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-cache-dir",
            "--target",
            str(installed),
            str(wheel),
        ),
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    initialized = tmp_path / "initialized"
    isolated_environment = {
        **environment,
        "PYTHONPATH": str(installed),
    }
    script = f"""
from tinysoul.action import builtin_action_catalog_root
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.app.cli import main

with builtin_action_catalog_root() as root:
    catalog = ActionCatalogLoader().load(root)
assert catalog.has_domain("core")
raise SystemExit(main(["init", {str(initialized)!r}]))
"""
    subprocess.run(
        (sys.executable, "-c", script),
        cwd=tmp_path,
        env=isolated_environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (initialized / "tinysoul.toml").is_file()
    assert (
        initialized / "home" / "how" / "tinysoul-docs" / "SKILL.md"
    ).is_file()
    assert (initialized / "memory").is_dir()
