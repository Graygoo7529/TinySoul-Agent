"""Model-visible text owned by plugins.capabilities.resource.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Local model feedback. Used by plugins/capabilities/resource/actions.py:execute.
INVALID_CONVERSION_RESULT = "Resource conversion returned an invalid staged result."

# Local model feedback. Used by plugins/capabilities/resource/actions.py:execute.
CONVERSION_STAGING_FAILED = "Resource conversion staging could not be completed."

# Local model feedback. Used by plugins/capabilities/resource/actions.py:execute.
RESOURCE_CONVERSION_COULD_NOT_BE_COMPLETED = (
    "Resource conversion could not be completed."
)


# Local model feedback. Used by plugins/capabilities/resource/actions.py:_params.
def source_link_required(*, action_name: str) -> str:
    return f"{action_name} requires a non-empty 'source_link'."


# Local model feedback. Used by plugins/capabilities/resource/actions.py:_params.
def target_link_required(*, action_name: str) -> str:
    return f"{action_name} requires a non-empty 'target_link'."


# Local model feedback. Used by plugins/capabilities/resource/actions.py:_params.
RESOURCE_CONVERSION_OVERWRITE_MUST_BE_BOOLEAN = (
    "Resource conversion overwrite must be boolean."
)
