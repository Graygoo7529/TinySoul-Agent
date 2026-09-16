"""Script capability failures."""


class ScriptError(Exception):
    """Base class for Script capability failures."""


class ScriptContractError(ScriptError):
    """A caller supplied an invalid Script request."""


class ScriptPolicyError(ScriptError):
    """A script did not satisfy the configured execution policy."""
