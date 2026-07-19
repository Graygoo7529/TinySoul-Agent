"""Deterministic admission policy for immediate Shell commands."""

from .errors import ShellContractError


class ShellPolicy:
    def __init__(self, *, max_command_chars: int) -> None:
        self._max_command_chars = max_command_chars

    def validate(self, command: str) -> None:
        if not isinstance(command, str) or not command.strip():
            raise ShellContractError("Shell command must be non-empty")
        if "\x00" in command:
            raise ShellContractError("Shell command cannot contain NUL")
        if len(command) > self._max_command_chars:
            raise ShellContractError(
                f"Shell command exceeds {self._max_command_chars} characters"
            )
