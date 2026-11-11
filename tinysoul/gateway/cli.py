"""Project commands and the long-running TinySoul backend host."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
import signal
import sys
from types import FrameType

from tinysoul.agent import Agent, AgentState
from tinysoul.agent.composition.assembly import AgentAssembly
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.errors import AgentError
from tinysoul.agent.observation.outputs import ObservationRoute
from tinysoul.infra import ConfigEnvironment, ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import ObservationLevel, RuntimeException

from .console import ConsoleMode, ConsoleMonitor
from .endpoint import (
    EndpointError,
    EndpointHost,
    EndpointLaunchSettings,
    EndpointSettings,
    load_endpoint_auth,
)
from .errors import GatewayError
from .project.initializer import ProjectConfigProfile, ProjectInitializer, ProjectResetter
from .project.instance import ProjectInstanceLease


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tinysoul")
    commands = parser.add_subparsers(dest="command", required=True)
    for command, description in (
        ("init", "Create a project from editable templates."),
        ("start", "Start the backend; interact through the frontend or SDK."),
        ("reset", "Clear project data and recreate templates, preserving .env and .auth."),
    ):
        sub = commands.add_parser(command, help=description, description=description)
        if command == "reset":
            sub.add_argument("directory", type=Path, help="existing project data directory")
        else:
            sub.add_argument("directory", nargs="?", type=Path, default=Path.cwd(),
                             help="project data directory (default: current directory)")
        if command == "start":
            sub.add_argument("--console", type=ConsoleMode, choices=tuple(ConsoleMode),
                             default=ConsoleMode.QUIET, help="terminal monitor (default: quiet)")
        else:
            sub.add_argument("--config-profile", type=ProjectConfigProfile,
                             choices=tuple(ProjectConfigProfile), default=ProjectConfigProfile.STANDARD,
                             help="project template (default: standard)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    if args.command == "start":
        return _start(args.directory, args.console)
    try:
        if args.command == "init":
            outcome = ProjectInitializer().initialize(args.directory, config_profile=args.config_profile)
            print(f"Initialized TinySoul project at {outcome.root} "
                  f"(config profile: {outcome.config_profile.value}; .auth generated)")
        else:
            root = args.directory.expanduser().resolve()
            with ProjectInstanceLease(root):
                reset = ProjectResetter().reset(root, config_profile=args.config_profile)
            env = ".env preserved" if reset.env_preserved else "no .env to preserve"
            auth = ".auth preserved" if reset.auth_preserved else "no .auth to preserve"
            print(f"Reset TinySoul project at {reset.root} "
                  f"(config profile: {reset.config_profile.value}; {env}; {auth})")
    except GatewayError as exc:
        print(f"tinysoul: {exc}", file=sys.stderr)
        return 1
    return 0


def _start(directory: Path, mode: ConsoleMode) -> int:
    root = directory.expanduser().resolve()
    monitor = ConsoleMonitor(mode=mode)
    monitor.report(f"backend starting project={root}")
    preparing = "project lock"
    try:
        with ProjectInstanceLease(root) as lease:
            preparing = "configuration"
            config = ConfigEnvironment.from_project_root(root)
            launch = config.load_section("endpoint", EndpointLaunchSettings)
            preparing = ".auth"
            auth = load_endpoint_auth(root)
            preparing = "runtime"
            host = EndpointHost(settings=EndpointSettings(
                host=launch.bind_host, port=launch.port, token=auth.token,
                instance_id=lease.identity.instance_id,
                project_identity=lease.identity.project_identity,
            ))
            assembly = (standard_agent(root)
                        .with_config_environment(config)
                        .with_observation_route(ObservationRoute(monitor, ObservationLevel.VERBOSE))
                        .build())
            return asyncio.run(_run_application(assembly, host, monitor))
    except KeyboardInterrupt:
        return 130
    except (ConfigError, EndpointError, RuntimeException, AgentError, GatewayError) as exc:
        detail = f" key={exc.key}" if isinstance(exc, ConfigError) else ""
        if isinstance(exc, RuntimeException):
            detail = f" reason={exc.reason}"
        monitor.report(f"backend failed while preparing {preparing} error={type(exc).__name__}{detail}")
        return 1


async def _run_application(
    assembly: AgentAssembly, endpoint_host: EndpointHost, monitor: ConsoleMonitor,
) -> int:
    agent = await Agent.assemble(assembly)
    endpoint_host.bind(agent.runtime)
    endpoint_host.set_availability(lambda: agent.state is AgentState.RUNNING)
    stop = asyncio.Event()
    with _ShutdownSignals(stop, monitor):
        try:
            await agent.start()
            endpoint_host.set_lifecycle(_EndpointLifecycle(agent, endpoint_host, monitor))
            await endpoint_host.start()
            monitor.report(f"backend ready listen={endpoint_host.settings.host}:{endpoint_host.port} auth=.auth")
            _report_runtime(agent, monitor)
            exited = asyncio.create_task(agent.wait_for_exit())
            requested = asyncio.create_task(stop.wait())
            try:
                done, _ = await asyncio.wait((exited, requested), return_when=asyncio.FIRST_COMPLETED)
                if exited in done:
                    await exited
                    monitor.report("agent run ended")
            finally:
                for waiter in (exited, requested):
                    waiter.cancel()
                await asyncio.gather(exited, requested, return_exceptions=True)
        finally:
            monitor.report("backend stopping")
            try:
                await endpoint_host.stop()
            finally:
                diagnostics = await agent.shutdown()
            for item in diagnostics:
                monitor.report(f"cleanup failed resource={item.resource} error={item.error_type}")
            monitor.report("backend stopped")
    return 1 if diagnostics or monitor.failure is not None else 0


def _report_runtime(agent: Agent, monitor: ConsoleMonitor) -> None:
    runtime = agent.runtime_status()
    monitor.report(f"agent running day={runtime['active_day']} generation={runtime['generation_id']}")
    for source in agent.status().sources:
        detail = f" error={source.error_type}" if source.error_type else ""
        monitor.report(f"source {source.source} state={source.state.value}{detail}")


class _EndpointLifecycle:
    """Rebind the stable Endpoint after the SDK replaces its runtime."""

    def __init__(self, agent: Agent, endpoint_host: EndpointHost, monitor: ConsoleMonitor) -> None:
        self._agent = agent
        self._endpoint_host = endpoint_host
        self._monitor = monitor

    async def restart(self) -> JsonObject:
        self._monitor.report("agent restarting")
        try:
            diagnostics = await self._agent.restart()
        except (RuntimeException, AgentError) as exc:
            self._monitor.report(f"agent restart failed error={type(exc).__name__}")
            raise
        finally:
            if self._agent.state is AgentState.RUNNING:
                self._endpoint_host.bind(self._agent.runtime)
        _report_runtime(self._agent, self._monitor)
        for item in diagnostics:
            self._monitor.report(f"cleanup failed resource={item.resource} error={item.error_type}")
        return {
            "accepted": True,
            "state": self._agent.state.value,
            "runtime": self._agent.runtime_status(),
            "cleanup": [{"resource": item.resource, "error_type": item.error_type} for item in diagnostics],
        }


class _ShutdownSignals(AbstractContextManager):
    """Signal the host once; business cancellation remains with Agent.shutdown."""

    def __init__(self, stop: asyncio.Event, monitor: ConsoleMonitor) -> None:
        self._stop = stop
        self._monitor = monitor
        self._previous: dict[int, Callable[[int, FrameType | None], object] | int | None] = {}

    def __enter__(self) -> _ShutdownSignals:
        for kind in (signal.SIGINT, signal.SIGTERM):
            self._previous[kind] = signal.signal(kind, self.handle)
        return self

    def __exit__(self, *args: object) -> None:
        for kind, handler in self._previous.items():
            signal.signal(kind, handler)

    def handle(self, signum: int, frame: FrameType | None) -> None:
        if self._stop.is_set():
            raise KeyboardInterrupt
        self._monitor.report("backend shutdown requested (interrupt again to force quit)")
        self._stop.set()
