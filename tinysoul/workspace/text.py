"""Bounded streaming text primitives for Workspace inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_READ_CHUNK_CHARS = 4096


@dataclass(frozen=True)
class WorkspaceTextPosition:
    """One 1-based character position in normalized UTF-8 text."""

    line: int
    column: int


@dataclass(frozen=True)
class WorkspaceTextRangeRead:
    """One bounded page from a requested inclusive line range."""

    text: str
    cursor: int
    next_cursor: int | None
    actual_start: WorkspaceTextPosition | None
    actual_end: WorkspaceTextPosition | None
    next_position: WorkspaceTextPosition | None
    truncated: bool
    eof_reached: bool
    cursor_valid: bool


def read_text_range(
    path: Path,
    *,
    start_line: int,
    end_line: int,
    cursor: int,
    max_chars: int,
    encoding: str = "utf-8",
) -> WorkspaceTextRangeRead:
    """Read a bounded cursor page from a 1-based inclusive line range."""

    line = 1
    column = 1
    range_offset = 0
    parts: list[str] = []
    used_chars = 0
    actual_start: WorkspaceTextPosition | None = None
    actual_end: WorkspaceTextPosition | None = None
    next_position: WorkspaceTextPosition | None = None
    truncated = False
    eof_reached = False
    range_ended = False

    with path.open("r", encoding=encoding, newline=None) as handle:
        while True:
            chunk = handle.read(_READ_CHUNK_CHARS)
            if not chunk:
                eof_reached = True
                break
            for character in chunk:
                if line > end_line:
                    range_ended = True
                    break
                if line >= start_line:
                    if range_offset < cursor:
                        range_offset += 1
                    elif used_chars >= max_chars:
                        truncated = True
                        next_position = WorkspaceTextPosition(line, column)
                        break
                    else:
                        position = WorkspaceTextPosition(line, column)
                        if actual_start is None:
                            actual_start = position
                        actual_end = position
                        parts.append(character)
                        used_chars += 1
                        range_offset += 1
                if character == "\n":
                    line += 1
                    column = 1
                else:
                    column += 1
            if truncated or range_ended:
                break

    cursor_valid = truncated or cursor <= range_offset
    return WorkspaceTextRangeRead(
        text="".join(parts),
        cursor=cursor,
        next_cursor=(range_offset if truncated else None),
        actual_start=actual_start,
        actual_end=actual_end,
        next_position=next_position,
        truncated=truncated,
        eof_reached=eof_reached,
        cursor_valid=cursor_valid,
    )
