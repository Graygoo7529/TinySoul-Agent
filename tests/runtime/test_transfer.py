from __future__ import annotations

from tinysoul.runtime.scope import RunFrame, RunLevel
from tinysoul.runtime.transfer import RuntimeTransfer, RuntimeTransferAction


def test_transfer_retry_and_end() -> None:
    frame = RunFrame(RunLevel.PHASE, "phase1")

    retry = RuntimeTransfer.retry(frame)
    end = RuntimeTransfer.end(frame)

    assert retry.action is RuntimeTransferAction.RETRY
    assert retry.target == frame
    assert end.action is RuntimeTransferAction.END
    assert end.target == frame
