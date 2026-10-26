"""Run TinySoul tests using the current Python; all policy lives in conftest."""

from pathlib import Path
import subprocess
import sys


def main() -> int:
    return subprocess.call(
        [sys.executable, "-m", "pytest", *sys.argv[1:]],
        cwd=Path(__file__).resolve().parents[1],
    )


if __name__ == "__main__":
    raise SystemExit(main())
