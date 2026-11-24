"""Web failures requiring Runtime coordination at the assembly boundary."""

from enum import StrEnum


class WebFailureKind(StrEnum):
    CONFIGURATION_FAILED = "web.configuration_failed"
