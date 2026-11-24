"""Resource failures requiring Runtime coordination at the assembly boundary."""

from enum import StrEnum


class ResourceFailureKind(StrEnum):
    CONFIGURATION_FAILED = "resource.configuration_failed"
