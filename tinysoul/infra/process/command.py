"""Explicit argv and Windows command-line contracts."""

from dataclasses import dataclass
import subprocess

from .errors import ProcessContractError


@dataclass(frozen=True)
class WindowsCommandLine:
    executable: str
    text: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value or "\x00" in value
            for value in (self.executable, self.text)
        ):
            raise ProcessContractError("Windows command line requires executable and text")


def cmd_command(executable: str, command: str) -> WindowsCommandLine:
    """Pass shell text verbatim through CMD's /S /C outer quotes."""
    return WindowsCommandLine(
        executable,
        f'{subprocess.list2cmdline([executable])} /D /Q /V:OFF /S /C "{command}"',
    )


def cmd_script(executable: str, script: str, args: tuple[str, ...]) -> WindowsCommandLine:
    """Quote batch arguments without pretending CMD uses C runtime escaping."""
    values = (script, *args)
    if any(
        any(char in value for char in ('"', "%", "\r", "\n", "\x00"))
        for value in values
    ):
        raise ProcessContractError(
            "CMD script paths and args cannot contain quotes, percent signs or newlines"
        )
    return cmd_command(executable, " ".join(f'"{value}"' for value in values))
