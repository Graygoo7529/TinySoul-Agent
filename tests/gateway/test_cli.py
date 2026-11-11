from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path
import signal
from types import SimpleNamespace
from typing import cast

import pytest

from tinysoul.gateway import cli
from tinysoul.gateway.console import ConsoleMode, ConsoleMonitor
from tinysoul.gateway.endpoint import EndpointLaunchSettings
from tinysoul.agent.observation.outputs import ObservationRoute
from tinysoul.gateway.endpoint import EndpointHost
from tinysoul.runtime import ObservationLevel


@pytest.mark.parametrize("mode", ConsoleMode)
def test_start_mounts_independent_console_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: ConsoleMode,
) -> None:
    captured: dict[str, object] = {}

    class Config:
        def load_section(self, section, settings_type):
            return EndpointLaunchSettings()

    class Builder:
        def with_config_environment(self, config):
            captured["config"] = config
            return self

        def with_observation_route(self, route):
            captured["route"] = route
            return self

        def build(self):
            return self

    class Lease:
        identity = SimpleNamespace(instance_id="instance", project_identity="project")

        def __init__(self, root):
            captured["root"] = root

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    async def run(assembly, host, monitor):
        captured["host"] = host
        captured["monitor"] = monitor
        return 0

    monkeypatch.setattr(cli, "standard_agent", lambda root: Builder())
    monkeypatch.setattr(cli.ConfigEnvironment, "from_project_root", lambda root: Config())
    monkeypatch.setattr(cli, "ProjectInstanceLease", Lease)
    monkeypatch.setattr(cli, "load_endpoint_auth", lambda root: SimpleNamespace(token="x" * 32))
    monkeypatch.setattr(cli, "_run_application", run)
    assert cli.main(["start", str(tmp_path), "--console", mode.value]) == 0
    route = cast(ObservationRoute, captured["route"])
    assert route.mode is ObservationLevel.VERBOSE
    assert route.sink is captured["monitor"]
    assert isinstance(route.sink, ConsoleMonitor)
    assert route.sink.mode is mode
    assert captured["root"] == tmp_path.resolve()
    assert cast(EndpointHost, captured["host"]).settings.instance_id == "instance"


def test_start_defaults_to_current_directory_and_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    received = []
    monkeypatch.setattr(cli, "_start", lambda directory, mode: received.append((directory, mode)) or 0)
    assert cli.main(["start"]) == 0
    assert received == [(Path.cwd(), ConsoleMode.QUIET)]


def test_reset_requires_explicit_target() -> None:
    assert cli.main(["reset"]) == 2


def test_shutdown_signal_requests_once_then_forces_and_restores() -> None:
    stop = asyncio.Event()
    monitor = ConsoleMonitor(stream=StringIO())
    previous = signal.getsignal(signal.SIGINT)
    with cli._ShutdownSignals(stop, monitor) as handler:
        handler.handle(signal.SIGINT, None)
        assert stop.is_set()
        with pytest.raises(KeyboardInterrupt):
            handler.handle(signal.SIGINT, None)
    assert signal.getsignal(signal.SIGINT) is previous
