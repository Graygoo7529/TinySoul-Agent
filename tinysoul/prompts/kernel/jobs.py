"""Model-visible text owned by kernel.jobs.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Local model feedback. Used by kernel/jobs/actions.py:execute.
PROVIDE_AN_ACTIVE_JOB_IDENTITY = "Provide an active Job identity."

# Local model feedback. Used by kernel/jobs/registry.py:_owned, kernel/jobs/actions.py:execute.
JOB_IS_NOT_AVAILABLE_IN_THIS_TURN = (
    "Job is not available in this Turn. Use a job_id from the current Turn."
)

# Local model feedback. Used by kernel/jobs/registry.py:backend.
JOB_CAPABILITY_MISMATCH = (
    "This Job belongs to a different capability. "
    "Use the controls for that Job's capability."
)


# Local model feedback. Used by kernel/jobs/registry.py:start.
def live_job_capacity_reached(*, limit: int) -> str:
    return (
        f"This Turn has reached its limit of {limit} live Jobs. "
        "Wait for a Job to finish or stop one before starting another."
    )


# Local model feedback. Used by kernel/jobs/registry.py:start.
def retained_job_capacity_reached(*, capacity: int) -> str:
    return (
        f"Job result capacity ({capacity}) is full. "
        "Finish this Turn before starting more Jobs."
    )

# Local model feedback. Used by kernel/jobs/actions.py:check.
WAIT_FOR_OR_STOP_THE_ACTIVE_JOB_BEFORE_ANSWERING = (
    "Wait for or stop the active Job before answering."
)
