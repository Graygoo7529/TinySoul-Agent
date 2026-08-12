from __future__ import annotations

import pytest

from tinysoul.runtime.generation import (
    RuntimeActivationState,
    RuntimeActivity,
    RuntimeGenerationError,
    RuntimeHandle,
)


def test_runtime_handle_reads_and_replaces_generation() -> None:
    handle = RuntimeHandle("old", generation_id="generation_old")
    assert handle.snapshot().generation == "old"
    with handle.read() as generation:
        assert generation == "old"

    handle.begin_activation()
    with handle.write():
        generation_id = handle.activate("new", generation_id="generation_new")

    snapshot = handle.snapshot()
    assert generation_id == "generation_new"
    assert snapshot.generation == "new"
    assert snapshot.activation is RuntimeActivationState.ACTIVE


def test_runtime_handle_rejects_activation_while_active() -> None:
    handle = RuntimeHandle("old")
    handle.set_activity(RuntimeActivity.USER_TURN)
    with pytest.raises(RuntimeGenerationError, match="idle"):
        handle.begin_activation()


def test_runtime_handle_failed_activation_is_visible() -> None:
    handle = RuntimeHandle("old")
    handle.begin_activation()
    handle.fail_activation()
    assert handle.snapshot().activation is RuntimeActivationState.FAILED


def test_runtime_activity_lease_reports_and_releases_activity() -> None:
    handle = RuntimeHandle("generation")

    with handle.activity_lease(RuntimeActivity.MAINTENANCE_TURN):
        assert handle.activity is RuntimeActivity.MAINTENANCE_TURN
        with pytest.raises(RuntimeGenerationError, match="idle"):
            handle.begin_activation()

    assert handle.activity is RuntimeActivity.IDLE
