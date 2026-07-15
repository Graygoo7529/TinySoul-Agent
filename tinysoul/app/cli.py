"""Console entry point for a configured TinySoul application."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from tinysoul.infra.config import ConfigEnvironment, ConfigError
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
