"""Model-visible text owned by kernel.jobs.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Local model feedback. Used by kernel/jobs/actions.py:execute.
PROVIDE_AN_ACTIVE_JOB_IDENTITY = "Provide an active Job identity."

# Local model feedback. Used by kernel/jobs/actions.py:execute.
WAIT_TIMEOUT_MUST_BE_POSITIVE = "Wait timeout must be positive."

# Local model feedback. Used by kernel/jobs/actions.py:execute.
JOB_IS_NOT_AVAILABLE_IN_THIS_TURN = "Job is not available in this Turn."

# Local model feedback. Used by kernel/jobs/actions.py:check.
WAIT_FOR_OR_STOP_THE_ACTIVE_JOB_BEFORE_ANSWERING = (
    "Wait for or stop the active Job before answering."
)
