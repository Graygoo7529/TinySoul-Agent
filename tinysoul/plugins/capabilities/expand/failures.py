"""Finite external request failures, distinct from owner contract failures."""

from enum import StrEnum


class ExpandFailureKind(StrEnum):
    CONFIGURATION_FAILED = "expand.configuration_failed"
    EXECUTION_CLOSE_FAILED = "expand.execution_close_failed"


class ExpandFailure(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "unavailable"
    SCHEMA = "unsupported_schema"
    ARGUMENTS = "invalid_arguments"
    REMOTE = "remote_failure"
    RESULT_UNKNOWN = "result_unknown"
    INPUT_REQUIRED = "input_required"
    CAPACITY = "capacity"
    SELECTION = "invalid_selection"


class ExpandRequestError(Exception):
    def __init__(self, reason: ExpandFailure, message: str) -> None:
        super().__init__(message)
        self.reason = reason
