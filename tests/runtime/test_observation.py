from __future__ import annotations

from typing import cast

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.runtime import (
    ObservationEvent,
    ObservationLevel,
    RuntimeContractError,
    emit_observation,
    observation_enabled,
)


class _BrokenEmitter:
    def enabled(self, level: ObservationLevel) -> bool:
        raise OSError("broken enabled check")

    def emit(self, event: ObservationEvent) -> None:
        raise OSError("broken emit")


def test_observation_emitter_failures_do_not_cross_runtime_boundary() -> None:
    emitter = _BrokenEmitter()

    assert not observation_enabled(emitter, ObservationLevel.VERBOSE)
    emit_observation(
        emitter,
        ObservationEvent(
            name="runtime.test",
            level=ObservationLevel.VERBOSE,
            source="test",
        ),
    )


def test_observation_event_maps_non_json_payload_to_runtime_contract_error() -> None:
    with pytest.raises(RuntimeContractError, match="payload must be a JSON object"):
        ObservationEvent(
            name="runtime.test",
            level=ObservationLevel.VERBOSE,
            source="test",
            payload=cast(JsonObject, {"invalid": object()}),
        )
