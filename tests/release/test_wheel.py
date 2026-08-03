from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
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

    assert "tinysoul/action/catalog/core/actions/answer.toml" in names
    assert (
        "tinysoul/action/catalog/workspace/actions/convert_with_markitdown.toml"
        in names
    )
    assert "tinysoul/action/catalog/workspace/actions/convert_with_pypdf.toml" in names
    assert "tinysoul/action/catalog/web/actions/search_by_kimi.toml" in names
    assert "tinysoul/action/catalog/web/actions/discover_pages.toml" in names
    assert "tinysoul/action/catalog/web/actions/fetch_with_defuddle.toml" in names
    assert "tinysoul/action/catalog/web/actions/fetch_with_trafilatura.toml" in names
    assert "tinysoul/action/catalog/execution/actions/run_python_script.toml" in names
    assert "tinysoul/action/catalog/execution/actions/run_powershell.toml" in names
    assert "tinysoul/action/catalog/execution/actions/run_cmd.toml" in names
    assert "tinysoul/action/catalog/execution/actions/apply.toml" in names
    assert "tinysoul/action/catalog/maintenance/domain.toml" in names
    assert "tinysoul/action/catalog/maintenance/actions/complete.toml" in names
    assert (
        "tinysoul/action/catalog/maintenance/actions/memory_consolidate.toml"
        in names
    )
    assert "tinysoul/app/program.py" in names
    assert "tinysoul/app/requests.py" in names
    assert "tinysoul/loop/maintenance/completion.py" in names
    assert "tinysoul/loop/user/completion.py" in names
    assert "tinysoul/maintenance/engine.py" in names
    assert "tinysoul/maintenance/archive/engine.py" in names
    assert "tinysoul/maintenance/home/task.py" in names
    assert "tinysoul/maintenance/memory/task.py" in names
    assert "tinysoul/app/maintenance.py" not in names
    assert "tinysoul/loop/program.py" not in names
    assert "tinysoul/maintenance/service.py" not in names
    assert not any(name.startswith("tinysoul/action/catalog/resource/") for name in names)
    assert not any(name.startswith("tinysoul/action/catalog/script/") for name in names)
    assert not any(name.startswith("tinysoul/action/catalog/shell/") for name in names)
    assert "tinysoul/action/catalog/workspace/actions/read.toml" in names
    assert "tinysoul/action/catalog/workspace/actions/search_text.toml" in names
    assert "tinysoul/action/catalog/workspace/actions/analyze.toml" in names
    assert "tinysoul/action/catalog/core/actions/context_inspect.toml" in names
    assert "tinysoul/action/catalog/core/actions/session_inspect.toml" in names
    assert not any(name.startswith("tinysoul/action/catalog/context/") for name in names)
    assert not any(name.startswith("tinysoul/action/catalog/session/") for name in names)
    for profile in ("standard", "development"):
        profile_root = f"tinysoul/assets/project/config_profiles/{profile}"
        assert f"{profile_root}/configs/home.toml" in names
        assert f"{profile_root}/configs/maintenance.toml" in names
        assert f"{profile_root}/configs/session.toml" in names
        assert f"{profile_root}/configs/capabilities.resource.toml" in names
        assert f"{profile_root}/configs/capabilities.web.toml" in names
        assert f"{profile_root}/configs/capabilities.script.toml" in names
        assert f"{profile_root}/configs/capabilities.shell.toml" in names
        assert f"{profile_root}/configs/capabilities.supervised_process.toml" in names
        assert f"{profile_root}/.env.example" in names
        assert f"{profile_root}/home/agent/user/user.md" in names
    assert "tinysoul/assets/project/README.md" in names
    assert "tinysoul/assets/project/home/agent/context/background.md" in names
    assert "tinysoul/assets/project/home/agent/context/turn-trace.md" in names
    assert "tinysoul/assets/project/home/agent/context/working.md" in names
    assert "tinysoul/assets/project/home/agent/identity/identity.md" in names
    assert "tinysoul/assets/project/home/agent/identity/soul.md" in names
    assert "tinysoul/assets/project/home/agent/user/user.md" not in names
    assert "tinysoul/assets/project/home/what/entity/tiny-soul.md" in names
    assert "tinysoul/assets/project/home/how/tinysoul-docs/SKILL.md" in names
    assert "tinysoul/assets/project/home/how_domain/execution/DOMAIN.md" in names
    assert "tinysoul/assets/project/home/how_domain/web/DOMAIN.md" in names
    assert not any(
        name.startswith("tinysoul/assets/project/home/how_domain/resource/")
        for name in names
    )
    assert not any(
        name.startswith("tinysoul/assets/project/home/how_domain/script/")
        for name in names
    )
    assert not any(
        name.startswith("tinysoul/assets/project/home/how_domain/shell/")
        for name in names
    )
    assert not any(
        name.startswith("tinysoul/assets/project/home/how_domain/session/")
        for name in names
    )
    assert not any(
        name.startswith("tinysoul/assets/project/home/how_domain/context/")
        for name in names
    )
    assert (
        "tinysoul/assets/project/home/how_domain/workspace/DOMAIN.md" in names
    )
    assert "tinysoul/assets/project/home/how_action/workspace/read.md" in names
    assert "tinysoul/assets/project/home/how_action/workspace/search_text.md" in names
    assert "tinysoul/assets/project/home/how_action/workspace/analyze.md" in names
    assert "tinysoul/assets/project/home/how_action/workspace/write.md" in names
    assert "tinysoul/assets/project/home/how_action/workspace/rewrite.md" in names
    assert "tinysoul/assets/project/home/how_action/core/answer.md" in names
    assert not any(
        name.startswith("tinysoul/assets/project/home/how_action/session/")
        for name in names
    )
    assert (
        "tinysoul/assets/project/home/how/tinysoul-docs/references/"
        "use-tinysoul-context-and-link.md"
    ) in names
    assert any(name.endswith(".dist-info/entry_points.txt") for name in names)
    assert "tinysoul/action/config.py" not in names
    assert "tinysoul/action/backends/native.py" not in names
    assert "tinysoul/action/backends/script.py" not in names

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
    assert not (initialized / "config_profiles").exists()
    assert (
        initialized / "home" / "how" / "tinysoul-docs" / "SKILL.md"
    ).is_file()
    assert (initialized / "configs" / "capabilities.resource.toml").is_file()
    assert (initialized / "configs" / "capabilities.web.toml").is_file()
    assert (initialized / "configs" / "capabilities.script.toml").is_file()
    assert (initialized / "configs" / "capabilities.shell.toml").is_file()
    assert (
        initialized / "configs" / "capabilities.supervised_process.toml"
    ).is_file()
    assert (
        initialized / "home" / "how_domain" / "execution" / "DOMAIN.md"
    ).is_file()
    assert (
        initialized / "home" / "how_domain" / "web" / "DOMAIN.md"
    ).is_file()
    assert not (initialized / "home" / "how_domain" / "resource").exists()
    assert not (initialized / "home" / "how_domain" / "script").exists()
    assert not (initialized / "home" / "how_domain" / "shell").exists()
    assert not (initialized / "home" / "how_domain" / "session").exists()
    assert not (initialized / "home" / "how_domain" / "context").exists()
    assert not (initialized / "home" / "how_action" / "session").exists()
    session_config = tomllib.loads(
        (initialized / "configs" / "session.toml").read_text(encoding="utf-8")
    )["session"]
    assert session_config["inspect_max_chars"] == 8000
    script_config = tomllib.loads(
        (initialized / "configs" / "capabilities.script.toml").read_text(
            encoding="utf-8"
        )
    )["capabilities"]["script"]
    assert script_config["enabled"] is False
    assert script_config["python"]["enabled"] is False
    assert "enabled = false" in (
        initialized / "configs" / "capabilities.shell.toml"
    ).read_text(encoding="utf-8")
    assert (
        initialized / "home" / "how_domain" / "workspace" / "DOMAIN.md"
    ).is_file()
    assert (
        initialized / "home" / "how_action" / "workspace" / "read.md"
    ).is_file()
    assert (
        initialized / "home" / "how_action" / "workspace" / "search_text.md"
    ).is_file()
    assert (
        initialized / "home" / "how_action" / "workspace" / "analyze.md"
    ).is_file()
    assert (
        initialized / "home" / "how_action" / "workspace" / "write.md"
    ).is_file()
    assert (
        initialized / "home" / "how_action" / "workspace" / "rewrite.md"
    ).is_file()
    assert (initialized / "memory").is_dir()
    assert (development / "README.md").is_file()
    assert (development / ".env").read_bytes() == b"SUBLYX_API_KEY=wheel-secret\n"
    assert not (development / "runtime").exists()
    assert not (development / "config_profiles").exists()
    assert (development / "home" / "agent" / "AGENT.md").read_bytes() == (
        initialized / "home" / "agent" / "AGENT.md"
    ).read_bytes()
    assert "enabled = true" in (
        development / "configs" / "capabilities.shell.toml"
    ).read_text(encoding="utf-8")
    assert "sublyx_proxy" in (
        development / "configs" / "llm.providers.toml"
    ).read_text(encoding="utf-8")
