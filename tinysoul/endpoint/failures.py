"""Endpoint failures used by Runtime bridge mapping."""

from __future__ import annotations

from enum import StrEnum


class EndpointFailureKind(StrEnum):
    CONFIGURATION_FAILED = "endpoint.configuration_failed"
    SERVER_FAILED = "endpoint.server_failed"
    INTERNAL_FAILURE = "endpoint.internal_failure"
