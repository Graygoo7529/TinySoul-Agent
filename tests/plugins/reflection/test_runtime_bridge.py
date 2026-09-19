from __future__ import annotations

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.plugins.reflection.errors import (
    ReflectionContractError,
    ReflectionInvariantError,
)
from tinysoul.plugins.reflection.failures import ReflectionFailureKind
from tinysoul.plugins.reflection.runtime_bridge import ReflectionRuntimeBridge
from tinysoul.runtime import RUNTIME_AGENT_END, RUNTIME_STARTUP_FAILED


@pytest.mark.parametrize(
    ("error", "kind"),
    (
        (
            ReflectionContractError("bad request"),
            ReflectionFailureKind.CONTRACT_VIOLATION,
        ),
        (
            ReflectionInvariantError("broken state"),
            ReflectionFailureKind.INVARIANT_VIOLATION,
        ),
    ),
)
def test_reflection_bridge_maps_control_failures(
    error: Exception,
    kind: ReflectionFailureKind,
) -> None:
    failure = ReflectionRuntimeBridge().from_reflection_error(error)

    assert failure.reason == RUNTIME_AGENT_END
    assert failure.payload["module"] == "reflection"
    assert failure.payload["kind"] == kind.value


def test_reflection_bridge_maps_config_error_to_startup() -> None:
    failure = ReflectionRuntimeBridge().from_config_error(
        ConfigError("bad config", key="reflection.enabled")
    )

    assert failure.reason == RUNTIME_STARTUP_FAILED
    assert failure.payload["kind"] == ReflectionFailureKind.CONFIGURATION_FAILED.value
