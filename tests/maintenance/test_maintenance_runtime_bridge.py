from __future__ import annotations

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.maintenance.errors import (
    MaintenanceContractError,
    MaintenanceInvariantError,
)
from tinysoul.maintenance.failures import MaintenanceFailureKind
from tinysoul.maintenance.runtime_bridge import MaintenanceRuntimeBridge
from tinysoul.runtime import RUNTIME_PROGRAM_END, RUNTIME_STARTUP_FAILED


@pytest.mark.parametrize(
    ("error", "kind"),
    (
        (
            MaintenanceContractError("bad request"),
            MaintenanceFailureKind.CONTRACT_VIOLATION,
        ),
        (
            MaintenanceInvariantError("broken state"),
            MaintenanceFailureKind.INVARIANT_VIOLATION,
        ),
    ),
)
def test_maintenance_bridge_maps_control_failures(
    error: Exception,
    kind: MaintenanceFailureKind,
) -> None:
    failure = MaintenanceRuntimeBridge().from_maintenance_error(error)

    assert failure.reason == RUNTIME_PROGRAM_END
    assert failure.payload["module"] == "maintenance"
    assert failure.payload["kind"] == kind.value


def test_maintenance_bridge_maps_config_error_to_startup() -> None:
    failure = MaintenanceRuntimeBridge().from_config_error(
        ConfigError("bad config", key="maintenance.enabled")
    )

    assert failure.reason == RUNTIME_STARTUP_FAILED
    assert failure.payload["kind"] == MaintenanceFailureKind.CONFIGURATION_FAILED.value
