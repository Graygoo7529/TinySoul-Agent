from __future__ import annotations

import pytest

from tinysoul.endpoint.errors import (
    EndpointContractError,
    EndpointError,
    EndpointServerError,
)
from tinysoul.endpoint.failures import EndpointFailureKind
from tinysoul.runtime import RUNTIME_STARTUP_FAILED
from tinysoul.runtime.bridge import RuntimeEndpointBridge


@pytest.mark.parametrize(
    ("error", "kind"),
    (
        (
            EndpointContractError("bad settings"),
            EndpointFailureKind.CONFIGURATION_FAILED,
        ),
        (EndpointServerError("bind failed"), EndpointFailureKind.SERVER_FAILED),
    ),
)
def test_endpoint_bridge_maps_startup_failures(
    error: EndpointError,
    kind: EndpointFailureKind,
) -> None:
    failure = RuntimeEndpointBridge().from_endpoint_error(error)

    assert failure.reason == RUNTIME_STARTUP_FAILED
    assert failure.payload["module"] == "endpoint"
    assert failure.payload["kind"] == kind.value
