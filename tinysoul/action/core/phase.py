"""Action cycle phase identifiers."""

from __future__ import annotations

from enum import StrEnum


class ActionCyclePhase(StrEnum):
    """Agent cycle phases that action module results can refer to."""

    PHASE1 = "phase1"
    PHASE2 = "phase2"
    PHASE3 = "phase3"
