from __future__ import annotations

import json
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
    for module, request, reason in (
        (
            "tinysoul.plugins.capabilities.web.backends.worker",
            {"operation": "unsupported"},
            "unsupported_operation",
        ),
        ("tinysoul.plugins.capabilities.resource.worker", {}, "invalid_request"),
    ):
        worker = subprocess.run(
            (sys.executable, "-m", module),
            input=json.dumps(request),
            cwd=tmp_path,
            env=isolated_environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert worker.returncode != 0
        reply = json.loads(worker.stdout)
        assert reply["ok"] is False
        assert reply["reason"] == reason
    script = f"""
import asyncio
import importlib.util
from pathlib import Path

from tinysoul.agent import Agent, AgentState, TurnState, UserTurnRequest
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.kernel.action.catalog.loader import ActionCatalogLoader
from tinysoul.gateway.cli import main

development = Path({str(development)!r})
assert main(["init", {str(initialized)!r}]) == 0
configuration = ConfigEnvironment.from_project_root(Path({str(initialized)!r}), env={{}})
catalog = ActionCatalogLoader().load_documents(configuration.document_set("action.catalog")).catalog
assert catalog.has_domain("core") and catalog.has_domain("memory")
assert importlib.util.find_spec("tinysoul.app") is None

async def verify_sdk():
    agent = await Agent.create(Path({str(initialized)!r}), overrides={{"reflection.schedule.enabled": False}})
    assert agent.state is AgentState.CREATED
    try:
        await agent.start()
        for scenario in ("user", "home_reflection", "memory_reflection"):
            surface = await agent.action_catalog(scenario=scenario)
            assert surface["scenario"] == scenario
        handle = await agent.submit_turn(UserTurnRequest("No provider is configured"))
        result = await handle.wait()
        assert handle.state is TurnState.FINISHED
        assert result.status.value == "failed"
    finally:
        assert await agent.shutdown() == ()

asyncio.run(verify_sdk())
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
    verified = subprocess.run(
        (sys.executable, "-c", script),
        cwd=tmp_path,
        env=isolated_environment,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stderr

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
