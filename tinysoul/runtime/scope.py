"""Runtime scope and frame primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterator, Self


class RunLevel(StrEnum):
    """Runtime frame level."""

    PROGRAM = "program"
    TURN = "turn"
    CYCLE = "cycle"
    PHASE = "phase"
    MODULE = "module"


class CyclePhase(StrEnum):
    """Agent cycle phase identifiers shared across modules."""

    PHASE1 = "phase1"
    PHASE2 = "phase2"
    PHASE3 = "phase3"


@dataclass(frozen=True)
class RunFrame:
    """A single frame in the runtime scope stack."""

    level: RunLevel
    name: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("RunFrame.name must be non-empty")

    def __str__(self) -> str:
        return f"{self.level.value}:{self.name}"


@dataclass(frozen=True)
class RunScope:
    """An immutable stack of runtime frames."""

    frames: tuple[RunFrame, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        frames = tuple(self.frames)
        for frame in frames:
            if not isinstance(frame, RunFrame):
                raise TypeError("RunScope.frames must contain RunFrame values")
        object.__setattr__(self, "frames", frames)

    @classmethod
    def of(cls, *frames: RunFrame) -> Self:
        return cls(frames=frames)

    def current(self) -> RunFrame | None:
        if not self.frames:
            return None
        return self.frames[-1]

    def push(self, level: RunLevel, name: str) -> Self:
        return type(self)(frames=(*self.frames, RunFrame(level=level, name=name)))

    def nearest(self, level: RunLevel) -> RunFrame | None:
        for frame in reversed(self.frames):
            if frame.level is level:
                return frame
        return None

    def __iter__(self) -> Iterator[RunFrame]:
        return iter(self.frames)

    def __len__(self) -> int:
        return len(self.frames)

    def __str__(self) -> str:
        if not self.frames:
            return "<empty>"
        return " > ".join(str(frame) for frame in self.frames)
