"""Model-visible text owned by kernel.context.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Tool description. Used by kernel/context/control/tools.py:_set_milestone_spec.
SET_MILESTONE_DESCRIPTION = "Set or replace one WorkingContext milestone."


# Tool description. Used by kernel/context/control/tools.py:_remove_milestone_spec.
REMOVE_MILESTONE_DESCRIPTION = "Remove one existing WorkingContext milestone."

# Tool description. Used by kernel/context/control/tools.py:_set_todo_spec.
SET_TODO_DESCRIPTION = "Set or replace one WorkingContext todo."


# Tool description. Used by kernel/context/control/tools.py:_remove_todo_spec.
REMOVE_TODO_DESCRIPTION = "Remove one existing WorkingContext todo."

# Tool description. Used by kernel/context/control/tools.py:_load_background_spec.
LOAD_BACKGROUND_DESCRIPTION = (
    "Load one or more top-level content refs already exposed in the current context "
    "into the background context."
)

# Tool description. Used by kernel/context/control/tools.py:_load_background_spec.
BACKGROUND_REF_DESCRIPTION = (
    "An effective top-level content ref already exposed in the current context."
)

# Tool description. Used by kernel/context/control/tools.py:_evict_background_spec.
EVICT_BACKGROUND_DESCRIPTION = (
    "Evict loaded top-level content entries from the background context."
)

# Model instruction or presentation. Used by kernel/context/builtin/working.py:_apply_patch_to_projection.
EMPTY_WORKING_PATCH = "Working patch contains no operations"


# Model task text or feedback. Used by kernel/context/builtin/working.py:_operation_problem.
def duplicate_set_key(*, label: str, duplicate: str) -> str:
    return f"Working patch contains duplicate {label} set key: {duplicate}"


# Model task text or feedback. Used by kernel/context/builtin/working.py:_operation_problem.
def duplicate_remove_key(*, label: str, duplicate: str) -> str:
    return f"Working patch contains duplicate {label} remove key: {duplicate}"


# Model task text or feedback. Used by kernel/context/builtin/working.py:_operation_problem.
def conflicting_patch_key(*, label: str, key: str) -> str:
    return f"Working patch cannot set and remove the same {label}: {key}"


# Model task text or feedback. Used by kernel/context/builtin/working.py:_apply_patch_to_projection.
def unknown_milestone(*, key: str) -> str:
    return f"Unknown milestone key: {key}"


# Model task text or feedback. Used by kernel/context/builtin/working.py:_apply_patch_to_projection.
def unknown_todo(*, key: str) -> str:
    return f"Unknown todo key: {key}"


# Model tool parameter description. Used by kernel/context/control/tools.py:_set_milestone_spec.
STABLE_MILESTONE_KEY = "Stable milestone key."

# Model tool parameter description. Used by kernel/context/control/tools.py:_set_milestone_spec.
MILESTONE_CONTENT = "Milestone content."

# Model tool parameter description. Used by kernel/context/control/tools.py:_set_todo_spec.
STABLE_TODO_KEY = "Stable todo key."

# Model tool parameter description. Used by kernel/context/control/tools.py:_set_todo_spec.
TODO_CONTENT = "Todo content."

# Model tool parameter description. Used by kernel/context/control/tools.py:_set_todo_spec.
TODO_STATUS = "Todo status."

# Model tool parameter description. Used by kernel/context/control/tools.py:_load_background_spec.
TOP_LEVEL_CONTENT_REFS_TO_LOAD_TOGETHER = "Top-level content refs to load together."

# Model tool parameter description. Used by kernel/context/control/tools.py:_evict_background_spec.
LOADED_TOP_LEVEL_CONTENT_REFS_TO_EVICT = "Loaded top-level content refs to evict."

# Model tool parameter description. Used by kernel/context/control/tools.py:_remove_working_spec.
EXISTING_ITEM_KEY = "Existing item key."


# Model context presentation or local feedback. Used by kernel/context/background.py:_check_patch_against_loaded.
def duplicate_background_load(*, duplicate: str) -> str:
    return f"Background patch contains duplicate load ref: {duplicate}"


# Model context presentation or local feedback. Used by kernel/context/background.py:_check_patch_against_loaded.
def duplicate_background_eviction(*, duplicate: str) -> str:
    return f"Background patch contains duplicate evict ref: {duplicate}"


# Model context presentation or local feedback. Used by kernel/context/background.py:_check_patch_against_loaded.
def conflicting_background_ref(*, ref: str) -> str:
    return f"Background patch cannot load and evict the same ref: {ref}"


# Model context presentation or local feedback. Used by kernel/context/background.py:_check_patch_against_loaded.
BACKGROUND_PATCH_CONTAINS_NO_REFS = "Background patch contains no refs"


# Model context presentation or local feedback. Used by kernel/context/background.py:_check_patch_against_loaded.
def unknown_background_ref(*, ref: str) -> str:
    return f"Unknown loadable background ref: {ref}"


# Model context presentation or local feedback. Used by kernel/context/background.py:_check_patch_against_loaded.
def background_not_loaded(*, ref: str) -> str:
    return f"Background ref is not loaded: {ref}"


# Model context presentation or local feedback. Used by kernel/context/background.py:_check_patch_against_loaded.
def background_not_evictable(*, ref: str) -> str:
    return f"Background ref is not evictable: {ref}"


# Local model feedback. Used by kernel/context/actions.py:execute.
CORE_CONTEXT_INSPECT_REQUIRES_A_NON_EMPTY_REF = (
    "core.context.inspect requires a non-empty ref"
)

# Local model feedback. Used by kernel/context/actions.py:execute.
INVALID_INSPECT_CONTINUATION = (
    "core.context.inspect continuation must be a non-empty opaque string"
)

# Local model feedback. Used by kernel/context/actions.py:execute, kernel/context/engine.py:inspect.
QUERY_MUST_BE_NON_EMPTY_TEXT = "Query must be non-empty text"

# Local model feedback. Used by kernel/context/builtin/trace.py:resolve_reference, kernel/context/builtin/trace.py:_node_for_ref.
TRACE_REF_DOES_NOT_BELONG_TO_THE_ACTIVE_TURN = (
    "Trace ref does not belong to the active Turn"
)

# Local model feedback. Used by kernel/context/builtin/trace.py:resolve_reference, kernel/context/builtin/trace.py:entries_for_ref.
UNKNOWN_TRACE_ENTRY = "Unknown trace entry"

# Local model feedback. Used by kernel/context/builtin/trace.py:resolve_reference.
UNKNOWN_TRACE_ACTION = "Unknown trace action"

# Local model feedback. Used by kernel/context/builtin/trace.py:leaf_entries.
INSPECT_LEAF_REQUIRED = "Context inspect requires a leaf ref for interaction content"

# Local model feedback. Used by kernel/context/builtin/trace.py:_node_for_ref.
UNKNOWN_CONTEXT_TRACE_REF = "Unknown Context trace ref"


# Local model feedback. Used by kernel/context/control/tools.py:normalize.
def duplicate_control_call(*, call_id: str) -> str:
    return f"Duplicate control tool call id: {call_id}"


# Local model feedback. Used by kernel/context/control/tools.py:normalize.
EXPECTED_A_CONTROL_TOOL_CALL = "Expected a control tool call."


# Local model feedback. Used by kernel/context/control/tools.py:_normalize_one.
def unknown_control_tool(*, name: str) -> str:
    return f"Unknown context control tool: {name}"


# Local model feedback. Used by kernel/context/control/tools.py:_normalize_background.
def refs_required(*, name: str) -> str:
    return f"{name} requires at least one ref."


# Local model feedback. Used by kernel/context/control/tools.py:_arg_str.
def nonempty_string_required(*, name: str) -> str:
    return f"Argument must be a non-empty string: {name}"


# Local model feedback. Used by kernel/context/control/tools.py:_arg_str_list.
def string_list_required(*, name: str) -> str:
    return f"Argument must be a string list: {name}"


# Local model feedback. Used by kernel/context/control/tools.py:_arg_str_list.
def nonempty_strings_required(*, name: str) -> str:
    return f"Argument must contain non-empty strings: {name}"


# Local model feedback. Used by kernel/context/control/tools.py:_arg_todo_status.
TODO_STATUS_MUST_BE_A_STRING = "Todo status must be a string"


# Local model feedback. Used by kernel/context/control/tools.py:_arg_todo_status.
def unknown_todo_status(*, raw: str) -> str:
    return f"Unknown todo status: {raw}"


# Local model feedback. Used by kernel/context/control/tools.py:_working_operation_patch.
def unexpected_control_arguments(*, name: str, expected_arguments: str) -> str:
    return f"{name} requires exactly: {expected_arguments}"


# Local model feedback. Used by kernel/context/engine.py:installed_segment.
UNKNOWN_INSTALLED_SEGMENT = "Unknown installed segment"

# Local model feedback. Used by kernel/context/search.py:disclosure_corpus.
CONTEXT_SCOPE_MUST_BE_TRACE_SESSION_OR_ALL = (
    "Context scope must be trace, session or all"
)

# Local model feedback. Used by kernel/context/search.py:disclosure_corpus.
CONTEXT_DISCOVERY_REQUIRES_A_TEXT_QUERY = "Context discovery requires a text query"

# Local model feedback. Used by kernel/context/segments/collection.py:resolve_reference, kernel/context/segments/collection.py:inspect.
NO_CONTEXT_SEGMENT_OWNS_THIS_REFERENCE = "No Context segment owns this reference"

# Local model feedback. Used by kernel/context/segments/collection.py:search_entries.
SEED_REFS_OUTSIDE_SCOPE = "Seed refs are outside the requested Context source scope"

# Local model feedback. Used by kernel/context/segments/collection.py:inspect.
INSPECT_QUERY_UNSUPPORTED = (
    "This owner supports navigation but not query; inspect without query"
)


def background_catalog(owner: str, entries: tuple[tuple[str, str, str], ...]) -> str:
    """Consumer: kernel/context/background.py."""
    return f"Available {owner} context\n" + "\n".join(
        f"- {title}: {description} ({ref})" for title, description, ref in entries
    )


def background_content(ref: str, content: str) -> str:
    return f"Reference: {ref}\n\n{content}"


def trace_directory(ref: str, entries: tuple[tuple[str, str], ...]) -> str:
    """Consumer: kernel/context/builtin/trace.py."""
    return (
        f"Earlier events in this Turn ({ref}). Inspect a reference to recall details.\n"
        + "\n".join(f"- {clue} ({target})" for target, clue in entries)
    )
