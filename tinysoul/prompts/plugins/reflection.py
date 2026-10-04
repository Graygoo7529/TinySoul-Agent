"""Model-visible text owned by plugins.reflection.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Tool description. Used by plugins/reflection/actions.py:build_reflection_action.
ANSWER_DESCRIPTION = (
    "Conclude this Reflection with a summary of changes, remaining work and "
    "limitations."
)

# Model instruction or presentation. Used by plugins/reflection/actions.py:build_reflection_action.
ANSWER_USE_WHEN = "The Reflection can conclude, including a bounded partial result."

# Model instruction or presentation. Used by plugins/reflection/actions.py:build_reflection_action.
ANSWER_AVOID_WHEN = "Work still needs to be executed within this Reflection."

# Model instruction or presentation. Used by plugins/reflection/home/task.py:run.
HOME_TASK = "Review and resolve every current runtime Home difference."


# Model task text or feedback. Used by plugins/reflection/home/task.py:run, plugins/reflection/memory/task.py:run.
def additional_instructions(*, instructions: str) -> str:
    return f"\nInstructions for this Reflection: {instructions}"


# Model task text or feedback. Used by plugins/reflection/memory/task.py:run.
def memory_task(*, target_day: str) -> str:
    return (
        "Maintain daily, entity, concept, fact, and note Memory for the target day "
        f"{target_day}. Search and inspect existing Memory before writing. "
        "If the target daily exists, read it first, then revise, reorganize and "
        "supplement it with available evidence. If it does not exist, create a "
        "complete daily. Write one complete document at a time; create redirect "
        "targets before retiring sources. Finish with core.answer."
    )


# Reflection Phase1/Phase2 guide. Used by plugins/reflection/turn/prompts.py:reflection_turn_guidance.
COMMON_GUIDANCE = (
    "This is an autonomous Reflection Turn.",
    "Use the supplied Background, Session, Workspace, and TurnTrace as context.",
    "Common domains remain available. Inspect evidence and act in small steps.",
    (
        "Use core.answer to conclude with a summary of changes, remaining "
        "work and limitations."
    ),
    (
        "The summary is a Reflection result, not a user response. Normal "
        "Reflection needs no approval."
    ),
)

# Reflection Phase1/Phase2 guide. Used by plugins/reflection/turn/prompts.py:reflection_turn_guidance.
HOME_REVIEW_GUIDE = (
    "Review every runtime Home difference against actual Home and the actual "
    "core rules."
)

# Reflection Phase1/Phase2 guide. Used by plugins/reflection/turn/prompts.py:reflection_turn_guidance.
HOME_DIFF_GUIDE = "Use home.diff; edit effective copies through home actions as needed."

# Reflection Phase1/Phase2 guide. Used by plugins/reflection/turn/prompts.py:reflection_turn_guidance.
HOME_REVIEW_DECISION_GUIDE = "Use home.review to accept or reject selected changes."

# Reflection Phase1/Phase2 guide. Used by plugins/reflection/turn/prompts.py:reflection_turn_guidance.
MEMORY_TARGET_DAY_GUIDE = "Distinguish the target day from the current execution day."

# Reflection Phase1/Phase2 guide. Used by plugins/reflection/turn/prompts.py:reflection_turn_guidance.
MEMORY_SOURCES_GUIDE = (
    "Use the fixed target-day Session and active Memory sources. Archived Workspace is "
    "read-only; current Workspace is the execution workbench."
)

# Reflection Phase1/Phase2 guide. Used by plugins/reflection/turn/prompts.py:reflection_turn_guidance.
MEMORY_WRITING_GUIDE = (
    "Search/inspect before writing. Write one document at a time and inspect "
    "the result."
)

# Reflection Phase1/Phase2 guide. Used by plugins/reflection/turn/prompts.py:reflection_turn_guidance.
MEMORY_REDIRECT_GUIDE = (
    "Create redirect targets before retiring source documents; committed writes remain "
    "if later work fails."
)
