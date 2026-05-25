"""Worker entry point for sandboxed script subprocesses."""

from __future__ import annotations

import sys

from tinysoul.infra.sandbox import _script_worker


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    _script_worker(sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
