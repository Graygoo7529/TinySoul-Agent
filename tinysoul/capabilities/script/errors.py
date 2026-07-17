"""Script capability failures."""


class ScriptError(Exception):
    """Base class for Script capability failures."""


class ScriptContractError(ScriptError):
    """A caller supplied an invalid Script request."""


class ScriptPolicyError(ScriptError):
    """A script did not satisfy the configured execution policy."""


class ScriptStateError(ScriptError):
    """A supervised job operation is invalid for its current state."""


class ScriptExecutionError(ScriptError):
    """A script could not be staged or executed."""
