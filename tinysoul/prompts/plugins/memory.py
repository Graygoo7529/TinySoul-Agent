"""Model-visible text owned by plugins.memory.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Tool description. Used by plugins/memory/background.py:catalog.
CURRENT_MEMORY_DESCRIPTION = "Explicit working memory for the current Business Day."


# Tool description. Used by plugins/memory/background.py:catalog.
def latest_daily_description(*, link: str) -> str:
    return f"Nearest earlier daily Memory: {link}."


# Tool description. Used by plugins/memory/background.py:catalog.
def target_memory_description(*, target_day: str) -> str:
    return f"Fixed target-day Memory for {target_day}."


# Tool description. Used by plugins/memory/background.py:catalog.
def prior_daily_description(*, link: str) -> str:
    return f"Nearest daily before target: {link}."


# Model context presentation or local feedback. Used by plugins/memory/background.py:catalog.
CURRENT_MEMORY = "Current memory"

# Model context presentation or local feedback. Used by plugins/memory/background.py:catalog.
TARGET_MEMORY = "Target memory"

# Model context presentation or local feedback. Used by plugins/memory/background.py:catalog.
LATEST_DAILY_MEMORY = "Latest daily memory"
# Local model feedback. Used by plugins/memory/actions/active.py:execute.
MEMORY_MEMORIZE_REQUIRES_OPERATIONS = "memory.memorize requires operations"

# Local model feedback. Used by plugins/memory/actions/active.py:execute.
INVALID_INSPECT_REQUEST = "Inspect requires a known ref and valid content page options"

# Local model feedback. Used by plugins/memory/actions/write.py:write.
MEMORY_WRITE_REQUIRES_NON_EMPTY_MARKDOWN = "Memory write requires non-empty Markdown."

# Local model feedback. Used by plugins/memory/actions/write.py:write.
MEMORY_WRITE_REJECTED = (
    "Memory write rejected: check the Link, Markdown schema, existing references and "
    "redirect chain."
)

# Local model feedback. Used by plugins/memory/actions/write.py:execute.
MEMORY_ACTION_IS_NOT_AVAILABLE_IN_THIS_REFLECTION = (
    "Memory action is not available in this Reflection."
)

# Local model feedback. Used by plugins/memory/engine.py:search_corpus.
INVALID_MEMORY_SCOPE = "Memory scope must be all or one persistent document kind"
