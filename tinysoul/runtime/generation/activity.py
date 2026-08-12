"""Runtime Generation activity and activation states."""

from __future__ import annotations

from enum import StrEnum


class RuntimeActivity(StrEnum):
    IDLE = "idle"
    USER_TURN = "user_turn"
    MAINTENANCE_TURN = "maintenance_turn"
    DAILY_TRANSITION = "daily_transition"
    CONFIG_ACTIVATION = "config_activation"


class RuntimeActivationState(StrEnum):
    ACTIVE = "active"
    PREPARING = "preparing"
    FAILED = "failed"

