"""Console entry point for a configured TinySoul application."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from secrets import token_urlsafe
import sys

from tinysoul.endpoint import EndpointError, EndpointReady, EndpointSettings
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.infra.json import dumps_json
from tinysoul.loop import TurnOutcomeStatus
from tinysoul.runtime import ObservationLevel, RuntimeException

from .builder import TinySoulAppBuilder
from .config import parse_app_settings
from .errors import AppError
from .outputs import ConsoleOutputSink
from .initializer import ProjectInitializer


def main(argv: Sequence[str] | None = None) -> int:
    """Run TinySoul interactively or execute exactly one user turn."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "init":
        return _initialize(arguments[1:])
    if arguments and arguments[0] == "serve":
        return _serve(arguments[1:])

    parser = _build_parser()
    args = parser.parse_args(arguments)
    root = args.root.resolve()
    overrides: dict[str, object] = {
        "app.interactive": args.once is None,
    }
    if args.mode is not None:
        overrides["app.output.mode"] = args.mode

    try:
        config = ConfigEnvironment.from_project_root(root, overrides=overrides)
        app_settings = config.parse_section("app", parse_app_settings)
        sink = ConsoleOutputSink(
            max_chars=app_settings.output.model_max_chars,
        )
        app = (
            TinySoulAppBuilder(root)
            .with_config_environment(config)
            .with_app_settings(app_settings)
            .with_output_sink(sink)
            .build()
        )
        if args.once is not None:
            outcome = app.run_once(args.once)
            return 0 if outcome.status is TurnOutcomeStatus.ANSWERED else 1
        else:
            app.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except (ConfigError, RuntimeException, AppError) as exc:
        print(f"tinysoul: {exc}", file=sys.stderr)
        return 1


def _initialize(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="tinysoul init",
        description="Initialize an editable TinySoul project.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="new or empty project directory (default: current directory)",
    )
    args = parser.parse_args(argv)
    try:
        outcome = ProjectInitializer().initialize(args.directory)
    except AppError as exc:
        print(f"tinysoul: {exc}", file=sys.stderr)
        return 1
    print(f"Initialized TinySoul project at {outcome.root}")
    return 0


def _serve(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="tinysoul serve",
        description="Run the authenticated local desktop Endpoint.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="project root containing tinysoul.toml (default: current directory)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="")
    parser.add_argument(
        "--mode",
        choices=tuple(level.value for level in ObservationLevel),
        default=ObservationLevel.MODEL.value,
    )
    args = parser.parse_args(tuple(argv))
    root = args.root.resolve()
    token = args.token or token_urlsafe(32)
    try:
        mode = ObservationLevel(args.mode)
        config = ConfigEnvironment.from_project_root(
            root,
            overrides={
                "app.interactive": True,
                "app.output.mode": mode.value,
            },
        )
        app_settings = config.parse_section("app", parse_app_settings)
        endpoint_settings = EndpointSettings(
            host=args.host,
            port=args.port,
            token=token,
            observation_mode=mode,
        )

        def ready(value: EndpointReady) -> None:
            print(dumps_json(value.to_json()), flush=True)

        app = (
            TinySoulAppBuilder(root)
            .with_config_environment(config)
            .with_app_settings(app_settings)
            .with_endpoint(endpoint_settings, ready=ready)
            .build()
        )
        app.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except (ConfigError, EndpointError, RuntimeException, AppError) as exc:
        print(f"tinysoul: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tinysoul",
        description="Run the TinySoul agent from a project configuration.",
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
        help="output detail: normal, verbose, or model",
    )
    parser.add_argument(
        "--once",
        metavar="TEXT",
        help="run one user turn instead of starting the interactive console",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
