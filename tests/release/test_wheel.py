from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


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
        "tinysoul/action/catalog/resource/actions/convert_with_markitdown.toml"
        in names
    )
    assert "tinysoul/action/catalog/resource/actions/convert_with_pypdf.toml" in names
    assert "tinysoul/action/catalog/web/actions/search_by_kimi.toml" in names
    assert "tinysoul/action/catalog/web/actions/discover_pages.toml" in names
    assert "tinysoul/action/catalog/web/actions/fetch_with_defuddle.toml" in names
    assert "tinysoul/action/catalog/web/actions/fetch_with_trafilatura.toml" in names
    assert "tinysoul/action/catalog/script/actions/run_python.toml" in names
    assert "tinysoul/action/catalog/script/actions/apply.toml" in names
    assert "tinysoul/action/catalog/shell/actions/run_powershell.toml" in names
    assert "tinysoul/action/catalog/shell/actions/run_cmd.toml" in names
    assert "tinysoul/action/catalog/shell/actions/apply.toml" in names
    assert "tinysoul/action/catalog/workspace/actions/read.toml" in names
    assert "tinysoul/action/catalog/workspace/actions/search_text.toml" in names
    assert "tinysoul/action/catalog/workspace/actions/analyze.toml" in names
    for profile in ("standard", "development"):
        profile_root = f"tinysoul/assets/project/config_profiles/{profile}"
        assert f"{profile_root}/configs/home.toml" in names
        assert f"{profile_root}/configs/capabilities.resource.toml" in names
        assert f"{profile_root}/configs/capabilities.web.toml" in names
        assert f"{profile_root}/configs/capabilities.script.toml" in names
        assert f"{profile_root}/configs/capabilities.shell.toml" in names
        assert f"{profile_root}/configs/capabilities.supervised_process.toml" in names
        assert f"{profile_root}/.env.example" in names
    assert "tinysoul/assets/project/README.md" in names
    assert "tinysoul/assets/project/home/agent/user/user.md" in names
    assert "tinysoul/assets/project/home/what/entity/tiny-soul.md" in names
    assert "tinysoul/assets/project/home/how/tinysoul-docs/SKILL.md" in names
    assert (
        "tinysoul/assets/project/home/how_domain/resource/DOMAIN.md" in names
    )
    assert "tinysoul/assets/project/home/how_domain/web/DOMAIN.md" in names
    assert "tinysoul/assets/project/home/how_domain/script/DOMAIN.md" in names
    assert "tinysoul/assets/project/home/how_domain/shell/DOMAIN.md" in names
    assert (
        "tinysoul/assets/project/home/how_domain/workspace/DOMAIN.md" in names
    )
    assert "tinysoul/assets/project/home/how_action/workspace/read.md" in names
    assert "tinysoul/assets/project/home/how_action/workspace/search_text.md" in names
    assert "tinysoul/assets/project/home/how_action/workspace/analyze.md" in names
    assert "tinysoul/assets/project/home/how_action/workspace/write.md" in names
    assert "tinysoul/assets/project/home/how_action/workspace/rewrite.md" in names
    assert (
        "tinysoul/assets/project/home/how/tinysoul-docs/references/"
        "use-tinysoul-context-and-link.md"
    ) in names
    assert any(name.endswith(".dist-info/entry_points.txt") for name in names)
    assert "tinysoul/action/config.py" not in names
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
from tinysoul.action import builtin_action_catalog_root
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.app.cli import main

with builtin_action_catalog_root() as root:
    catalog = ActionCatalogLoader().load(root)
assert catalog.has_domain("core")
assert main(["init", {str(initialized)!r}]) == 0
raise SystemExit(
    main([
        "init",
        {str(development)!r},
        "--config-profile",
        "development",
    ])
)
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
        initialized / "home" / "how_domain" / "resource" / "DOMAIN.md"
    ).is_file()
    assert (
        initialized / "home" / "how_domain" / "web" / "DOMAIN.md"
    ).is_file()
    assert (
        initialized / "home" / "how_domain" / "script" / "DOMAIN.md"
    ).is_file()
    assert (
        initialized / "home" / "how_domain" / "shell" / "DOMAIN.md"
    ).is_file()
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
