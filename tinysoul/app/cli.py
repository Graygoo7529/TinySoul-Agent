"""TinySoul command-line entry points."""

from __future__ import annotations

import argparse
from pathlib import Path
from secrets import token_urlsafe
import signal as signal_module
import sys
from collections.abc import Sequence
from types import FrameType

from tinysoul.endpoint import EndpointError, EndpointSettings
from tinysoul.infra import ConfigEnvironment, ConfigError
from tinysoul.loop import LoopControlKind
from tinysoul.runtime import ObservationLevel, RuntimeException, RuntimeGatewayError

from .builder import TinySoulAppBuilder
from .config import parse_app_settings
from .errors import AppError
from .gateway import AppCommandGateway
from .initializer import ProjectConfigProfile, ProjectInitializer, ProjectResetter
from .instance import ProjectInstanceLease
from .outputs import ConsoleOutputSink
from .sources import TerminalInputSource


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
    except AppError as exc:
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
    except AppError as exc:
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
        "app.interactive": args.once is None,
    }
    if args.mode is not None:
        overrides["app.output.mode"] = args.mode

    try:
        with ProjectInstanceLease(root) as lease:
            config = ConfigEnvironment.from_project_root(root, overrides=overrides)
            app_settings = config.parse_section("app", parse_app_settings)
            builder = (
                TinySoulAppBuilder(root)
                .with_config_environment(config)
                .with_app_settings(app_settings)
                .with_output_sink(
                    ConsoleOutputSink(max_chars=app_settings.output.model_max_chars)
                )
            )
            if args.once is None:
                endpoint_settings = EndpointSettings(
                    token=token_urlsafe(32),
                    instance_id=lease.identity.instance_id,
                    project_identity=lease.identity.project_identity,
                )
                builder = (
                    builder.with_endpoint(endpoint_settings, ready=lease.publish)
                    .with_input_source(
                        TerminalInputSource(
                            eof_command=app_settings.input_commands.exit_commands[0]
                        )
                    )
                )
            app = builder.build()
            if args.once is not None:
                outcome = app.run_once(args.once)
                return 0 if outcome.status.value == "answered" else 1
            escalation = _SigintEscalation(app.gateway)
            previous_handler = signal_module.signal(
                signal_module.SIGINT,
                escalation.handle,
            )
            try:
                app.run()
            finally:
                signal_module.signal(signal_module.SIGINT, previous_handler)
            return 0
    except KeyboardInterrupt:
        return 130
    except (ConfigError, EndpointError, RuntimeException, AppError) as exc:
        print(f"tinysoul: {exc}", file=sys.stderr)
        return 1


class _SigintEscalation:
    """Graded Ctrl-C handling for interactive runs.

    The first Ctrl-C stops the active Turn (or requests Program exit when
    idle); the next one requests Program exit; a further press falls back
    to a hard KeyboardInterrupt. Requests go through the same trusted
    command gateway as Terminal and Endpoint input.
    """

    def __init__(self, gateway: AppCommandGateway) -> None:
        self._gateway = gateway
        self._stop_requested = False
        self._exit_requested = False

    def handle(self, signum: int, frame: FrameType | None) -> None:
        if self._exit_requested:
            raise KeyboardInterrupt
        try:
            if not self._stop_requested and self._gateway.active_turn_scope is not None:
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
        try:
            receipt = self._gateway.request_control(
                kind,
                source="terminal.sigint",
                text=kind.value,
            )
        except RuntimeGatewayError:
            return False
        return receipt.accepted
