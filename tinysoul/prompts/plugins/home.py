"""Model-visible text owned by plugins.home.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Local model feedback. Used by plugins/home/actions/content.py:execute.
INVALID_INSPECT_REQUEST = "Inspect requires a known ref and valid page options"

# Local model feedback. Used by plugins/home/actions/content.py:execute.
RESOURCE_WRITE_INPUT_REQUIRED = (
    "home.resource.write requires non-empty 'link' and string 'text'."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
INVALID_RESOURCE_WRITE_PRECONDITIONS = (
    "home.resource.write overwrite/expected_digest parameters are invalid."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
RESOURCE_WRITE_REJECTED = (
    "Home resource write request rejected; check the Link and current content."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
HOME_RESOURCE_PATCH_PARAMETERS_ARE_INVALID = (
    "home.resource.patch parameters are invalid."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
RESOURCE_PATCH_REJECTED = (
    "Home resource patch request rejected; check the Link and current content."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
HOME_RESOURCE_DELETE_PARAMETERS_ARE_INVALID = (
    "home.resource.delete parameters are invalid."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
RESOURCE_DELETE_REJECTED = (
    "Home resource delete request rejected; check the Link and current content."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
TOP_WRITE_INPUT_REQUIRED = "home.top.write requires non-empty 'link' and string 'text'."

# Local model feedback. Used by plugins/home/actions/content.py:execute.
INVALID_TOP_WRITE_PRECONDITIONS = "home.top.write precondition parameters are invalid."

# Local model feedback. Used by plugins/home/actions/content.py:execute.
TOP_WRITE_REJECTED = (
    "Home top write request rejected; check the Link and current content."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
HOME_TOP_PATCH_PARAMETERS_ARE_INVALID = "home.top.patch parameters are invalid."

# Local model feedback. Used by plugins/home/actions/content.py:execute.
TOP_PATCH_REJECTED = (
    "Home top patch request rejected; check the Link and current content."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
HOME_TOP_DELETE_PARAMETERS_ARE_INVALID = "home.top.delete parameters are invalid."

# Local model feedback. Used by plugins/home/actions/content.py:execute.
TOP_DELETE_REJECTED = (
    "Home top delete request rejected; check the Link and current content."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
PROMPT_MOUNT_WRITE_INPUT_REQUIRED = (
    "home.prompt_mount.write requires non-empty 'link' and string 'text'."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
INVALID_PROMPT_MOUNT_WRITE_PRECONDITIONS = (
    "home.prompt_mount.write precondition parameters are invalid."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
PROMPT_MOUNT_WRITE_REJECTED = (
    "Home prompt mount write request rejected; check the Link and current content."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
HOME_PROMPT_MOUNT_PATCH_PARAMETERS_ARE_INVALID = (
    "home.prompt_mount.patch parameters are invalid."
)

# Local model feedback. Used by plugins/home/actions/content.py:execute.
PROMPT_MOUNT_PATCH_REJECTED = (
    "Home prompt mount patch request rejected; check the Link and current content."
)

# Local model feedback. Used by plugins/home/actions/review.py:execute.
UNKNOWN_HOME_REVIEW_ACTION = "Unknown Home review action"

# Local model feedback. Used by plugins/home/actions/review.py:_review.
PATHS_MUST_CONTAIN_HOME_LINKS = "paths must contain Home Links"

# Local model feedback. Used by plugins/home/actions/review.py:_review.
SELECT_HOME_LINKS_AND_ACCEPT_OR_REJECT = "Select Home Links and accept or reject"

# Local model feedback. Used by plugins/home/actions/review.py:_review.
INVALID_REVIEW_REQUEST = "Home review request is invalid; inspect the current diff"

# Local model feedback. Used by plugins/home/engine.py:search_corpus.
HOME_SCOPE_MUST_BE_ALL_AGENT_OR_SKILLS = "Home scope must be all, agent or skills"

# Local model feedback. Used by plugins/home/engine.py:search_corpus.
HOME_REF_IS_UNAVAILABLE_IN_THIS_VIEW = "Home ref is unavailable in this view"

# Local model feedback. Used by plugins/home/engine.py:search_corpus.
HOME_DISCOVERY_ACCEPTS_TEXT_QUERY_ONLY = "Home discovery accepts text query only"

# Local model feedback. Used by plugins/home/engine.py:search_corpus.
NON_TEXT_HOME_RESOURCE_HAS_NO_TEXT_FRAGMENT = (
    "Non-text Home resource has no text fragment"
)
