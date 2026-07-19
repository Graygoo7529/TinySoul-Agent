"""Immediate Shell capability failures."""


class ShellError(Exception):
    """Base class for Shell capability failures."""


class ShellContractError(ShellError):
    """A Shell command or working directory is invalid."""
