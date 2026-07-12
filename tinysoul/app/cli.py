"""Console entry point for a configured TinySoul application."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.runtime import ObservationLevel, RuntimeException

from .builder import TinySoulAppBuilder
from .config import parse_app_settings
from .errors import AppError
from .outputs import ConsoleOutputSink


def main(argv: Sequence[str] | None = None) -> int:
    """Run TinySoul interactively or execute exactly one user turn."""

    parser = _build_parser()
    args = parser.parse_args(argv)
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
            app.run_once(args.once)
        else:
            app.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except (ConfigError, RuntimeException, AppError) as exc:
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
