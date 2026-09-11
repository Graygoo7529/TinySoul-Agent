from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


pytestmark = pytest.mark.release


def test_wheel_contains_resources_and_installed_package_initializes_project(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    build_root = tmp_path.parent / "wheel-build"
    source_root = build_root / "source"
    wheel_root = build_root / "wheel"
    source_root.mkdir(parents=True)
    wheel_root.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(project_root / name, source_root / name)
    shutil.copytree(
        project_root / "tinysoul",
        source_root / "tinysoul",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    environment = {
        **os.environ,
        "PIP_NO_CACHE_DIR": "1",
        "TMP": str(build_root),
        "TEMP": str(build_root),
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
        cwd=source_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_root.glob("tinysoul-*.whl"))

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    expected_files = {
        path.relative_to(source_root).as_posix()
        for path in (source_root / "tinysoul").rglob("*")
        if path.is_file()
    }
    assert expected_files <= names
    assert any(name.endswith(".dist-info/entry_points.txt") for name in names)

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
    development = tmp_path / "development"
    isolated_environment = {
        **environment,
        "PYTHONPATH": str(installed),
    }
    script = f"""
from pathlib import Path

from tinysoul.action import builtin_action_catalog_root
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.app.cli import main

development = Path({str(development)!r})
with builtin_action_catalog_root() as root:
    catalog = ActionCatalogLoader().load(root)
assert catalog.has_domain("core")
assert main(["init", {str(initialized)!r}]) == 0
assert main([
    "init",
    {str(development)!r},
    "--config-profile",
    "development",
]) == 0
(development / ".env").write_bytes(b"SUBLYX_API_KEY=wheel-secret\\n")
(development / "runtime").mkdir()
(development / "runtime" / "old.txt").write_text("old", encoding="utf-8")
raise SystemExit(main(["reset", {str(development)!r}]))
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
    assert (initialized / "README.md").is_file()
    assert (initialized / "home").is_dir()
    assert (initialized / "configs").is_dir()
    assert (initialized / "memory").is_dir()
    assert any((initialized / "home").rglob("*.md"))
    assert any((initialized / "configs").rglob("*.toml"))
    assert (development / ".env").read_bytes() == b"SUBLYX_API_KEY=wheel-secret\n"
    assert not (development / "runtime").exists()
    assert not (development / "config_profiles").exists()
    assert (development / "home").is_dir()
    assert (development / "configs").is_dir()
