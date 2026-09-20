"""TinySoul command-line entry points."""

from __future__ import annotations
import asyncio

import argparse
from pathlib import Path
from secrets import token_urlsafe
import signal as signal_module
import sys
from tinysoul.agent import Agent, UserTurnRequest
from tinysoul.agent.commands import AgentCommands
from tinysoul.agent.requests import ExitRequest
from collections.abc import Awaitable, Callable, Sequence
from types import FrameType

from tinysoul.gateway.endpoint import EndpointError, EndpointSettings
from tinysoul.infra import ConfigEnvironment, ConfigError
from tinysoul.kernel.loop import LoopControlKind
from tinysoul.runtime import ObservationLevel, RuntimeException, RuntimeGatewayError

from tinysoul.agent.composition.builder import AgentBuilder
from tinysoul.agent.composition.assembly import AgentAssembly
from tinysoul.agent.config import parse_agent_settings
from tinysoul.agent.errors import AgentError
from .errors import GatewayError
from .project.initializer import (
    ProjectConfigProfile,
    ProjectInitializer,
    ProjectResetter,
)
from .project.instance import ProjectInstanceLease
from .console import ConsoleOutputSink
from tinysoul.environment.sources.terminal import TerminalInputSource
from .endpoint.host import mount_endpoint


def main(argv: Sequence[str] | None = None) -> int:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "init":
        return _init(args[1:])
    if args and args[0] == "reset":
        return _reset(args[1:])
    if args and args[0] == "start":
        return _start(args[1:])
    parser = argparse.ArgumentParser(prog="tinysoul")
    parser.add_argument("command", choices=("start", "init", "reset"))
    try:
        parser.parse_args(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    return 2


def _init(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="tinysoul init",
        description="Create a TinySoul project from packaged editable templates.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="new or empty project directory (default: current directory)",
    )
    parser.add_argument(
        "--config-profile",
        type=ProjectConfigProfile,
        choices=tuple(ProjectConfigProfile),
        default=ProjectConfigProfile.STANDARD,
        help="initial configuration set: standard or development (default: standard)",
    )
    args = parser.parse_args(tuple(argv))
    try:
        outcome = ProjectInitializer().initialize(
            args.directory,
            config_profile=args.config_profile,
        )
    except GatewayError as exc:
        print(f"tinysoul: {exc}", file=sys.stderr)
        return 1
    print(
        f"Initialized TinySoul project at {outcome.root} "
        f"(config profile: {outcome.config_profile.value})"
    )
    return 0


def _reset(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="tinysoul reset",
        description=(
            "Recreate a TinySoul project from packaged templates, clear all "
            "project data, and preserve its .env file."
        ),
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="existing TinySoul project directory",
    )
    parser.add_argument(
        "--config-profile",
        type=ProjectConfigProfile,
        choices=tuple(ProjectConfigProfile),
        default=ProjectConfigProfile.DEVELOPMENT,
        help=(
            "replacement configuration set: standard or development "
            "(default: development)"
        ),
    )
    args = parser.parse_args(tuple(argv))
    root = args.directory.expanduser().resolve()
    try:
        with ProjectInstanceLease(root):
            outcome = ProjectResetter().reset(
                root,
                config_profile=args.config_profile,
            )
    except GatewayError as exc:
        print(f"tinysoul: {exc}", file=sys.stderr)
        return 1
    env_status = ".env preserved" if outcome.env_preserved else "no .env to preserve"
    print(
        f"Reset TinySoul project at {outcome.root} "
        f"(config profile: {outcome.config_profile.value}; {env_status})"
    )
    return 0


def _start(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="tinysoul start",
        description="Run TinySoul with Terminal input and the desktop Endpoint.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="project root containing tinysoul.toml (default: current directory)",
    )
    parser.add_argument(
        "--mode",
        choices=tuple(level.value for level in ObservationLevel),
        help="Terminal output detail: normal, verbose, or model",
    )
    parser.add_argument(
        "--once",
        metavar="TEXT",
        help="run one User Turn without opening an interactive Endpoint",
    )
    args = parser.parse_args(tuple(argv))
    root = args.root.resolve()
    overrides: dict[str, object] = {
        "agent.interactive": args.once is None,
    }
    if args.mode is not None:
        overrides["agent.output.mode"] = args.mode
    if args.once is not None:
        overrides["reflection.schedule.enabled"] = False
        overrides["workspace.watch.enabled"] = False

    try:
        with ProjectInstanceLease(root) as lease:
            config = ConfigEnvironment.from_project_root(root, overrides=overrides)
            agent_settings = config.parse_section("agent", parse_agent_settings)
            builder = (
                AgentBuilder(root)
                .with_config_environment(config)
                .with_agent_settings(agent_settings)
                .with_output_sink(
                    ConsoleOutputSink(max_chars=agent_settings.output.model_max_chars)
                )
            )
            endpoint_settings: EndpointSettings | None = None
            if args.once is None:
                endpoint_settings = EndpointSettings(
                    token=token_urlsafe(32),
                    instance_id=lease.identity.instance_id,
                    project_identity=lease.identity.project_identity,
                )
                builder = builder.with_input_source(
                    TerminalInputSource(
                        eof_command=agent_settings.input_commands.exit_commands[0]
                    )
                )

            async def factory() -> AgentAssembly:
                assembly = await builder.build()
                try:
                    if endpoint_settings is not None:
                        mount_endpoint(assembly, endpoint_settings, ready=lease.publish)
                    return assembly
                except BaseException:
                    await assembly.close()
                    raise

            return asyncio.run(_run_application(factory, args.once))
    except KeyboardInterrupt:
        return 130
    except (
        ConfigError,
        EndpointError,
        RuntimeException,
        AgentError,
        GatewayError,
    ) as exc:
        print(f"tinysoul: {exc}", file=sys.stderr)
        return 1


async def _run_application(
    factory: Callable[[], Awaitable[AgentAssembly]], once: str | None
) -> int:
    agent = await Agent.assemble(factory)
    try:
        await agent.start()
        if once is not None:
            handle = await agent.submit_turn(UserTurnRequest(once, source="cli"))
            result = await handle.wait()
            code = (
                0
                if result.outcome is not None
                and result.outcome.status.value == "answered"
                else 1
            )
        else:
            escalation = _SigintEscalation(agent.commands)
            previous_handler = signal_module.signal(
                signal_module.SIGINT, escalation.handle
            )
            try:
                await agent.wait()
                code = 0
            finally:
                signal_module.signal(signal_module.SIGINT, previous_handler)
    finally:
        diagnostics = await agent.shutdown()
        for item in diagnostics:
            print(
                f"tinysoul: cleanup failed: {item.resource} ({item.error_type})",
                file=sys.stderr,
            )
    return 1 if diagnostics else code


class _SigintEscalation:
    """Graded Ctrl-C handling for interactive runs.

    The first Ctrl-C stops the active Turn (or requests Program exit when
    idle); the next one requests Program exit; a further press falls back
    to a hard KeyboardInterrupt. Requests go through the same trusted
    command gateway as Terminal and Endpoint input.
    """

    def __init__(self, commands: AgentCommands) -> None:
        self._commands = commands
        self._stop_requested = False
        self._exit_requested = False

    def handle(self, signum: int, frame: FrameType | None) -> None:
        if self._exit_requested:
            raise KeyboardInterrupt
        try:
            if not self._stop_requested and self._commands.active_turn is not None:
                if self._request(LoopControlKind.STOP_TURN):
                    self._stop_requested = True
                    print(
                        "tinysoul: stopping the current turn "
                        "(press Ctrl-C again to exit)",
                        file=sys.stderr,
                    )
                    return
            self._exit_requested = True
            if self._request(LoopControlKind.EXIT_PROGRAM):
                print(
                    "tinysoul: exiting (press Ctrl-C again to force quit)",
                    file=sys.stderr,
                )
                return
        except KeyboardInterrupt:
            raise
        except Exception:
            pass
        raise KeyboardInterrupt

    def _request(self, kind: LoopControlKind) -> bool:
        if kind is LoopControlKind.STOP_TURN:
            active = self._commands.active_turn
            return active is not None and active.request_cancel()
        self._commands.request_exit(
            ExitRequest(source="terminal.sigint", text=kind.value)
        )
        return True
