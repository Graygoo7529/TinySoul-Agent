from __future__ import annotations

from typing import cast

import pytest

from tinysoul.runtime.errors import RuntimeContractError
from tinysoul.runtime.scope import RunFrame, RunLevel, RunScope


def test_scope_push_and_current() -> None:
    scope = RunScope().push(RunLevel.PROGRAM, "main").push(RunLevel.TURN, "user")

    assert scope.current() == RunFrame(RunLevel.TURN, "user")
    assert len(scope) == 2


def test_scope_nearest() -> None:
    scope = RunScope.of(
        RunFrame(RunLevel.PROGRAM, "main"),
        RunFrame(RunLevel.TURN, "user"),
        RunFrame(RunLevel.CYCLE, "1"),
        RunFrame(RunLevel.PHASE, "phase1"),
    )

    assert scope.nearest(RunLevel.TURN) == RunFrame(RunLevel.TURN, "user")
    assert scope.nearest(RunLevel.MODULE) is None


def test_frame_and_scope_validate() -> None:
    with pytest.raises(RuntimeContractError):
        RunFrame(RunLevel.PROGRAM, "")

    with pytest.raises(RuntimeContractError):
        RunScope(frames=cast(tuple[RunFrame, ...], ("bad",)))
