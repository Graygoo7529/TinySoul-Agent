"""Bounded delegation failures at the external Agent boundary."""

from enum import StrEnum


class SubagentFailure(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "unavailable"
    BUSY = "busy"
    PROTOCOL = "protocol_failure"
    CONFIGURATION_FAILED = "configuration_failed"
    EXECUTION_CLOSE_FAILED = "execution_close_failed"


class SubagentRequestError(Exception):
    def __init__(self, reason: SubagentFailure, message: str) -> None:
        super().__init__(message)
        self.reason = reason
