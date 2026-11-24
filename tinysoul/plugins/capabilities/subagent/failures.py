"""Bounded delegation failures at the external Agent boundary."""

from enum import StrEnum


class SubagentFailureKind(StrEnum):
    CONFIGURATION_FAILED = "subagent.configuration_failed"
    EXECUTION_CLOSE_FAILED = "subagent.execution_close_failed"


class SubagentFailure(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "unavailable"
    BUSY = "busy"


class SubagentRequestError(Exception):
    def __init__(self, reason: SubagentFailure, message: str) -> None:
        super().__init__(message)
        self.reason = reason
