"""Model-visible text owned by kernel.loop.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Phase TaskPrompt guide. Used by kernel/loop/prompts.py:phase1_task_prompt.
PHASE1_GUIDANCE = (
    "You are in TinySoul Phase1.",
    (
        "Before selecting action domains, reconcile existing WorkingContext "
        "milestones and todos with authoritative ActionResults already "
        "visible in the current Context."
    ),
    (
        "When real task state changed, call the relevant set/remove milestone"
        " or todo control tools in this same Phase1 response; do not leave "
        "completed work pending or in_progress, and do not mark a failed or "
        "merely attempted action done."
    ),
    (
        "Treat milestones as concise factual register entries that remain "
        "useful for later cycles. Record valuable completed work, attempts, "
        "failures, blocked conditions, concrete links, versions, values, "
        "decisions, or digests with their status made explicit. Do not use a "
        "milestone as a todo mirror or describe an attempt as completed work."
    ),
    (
        "Useful milestone examples: a computed value such as an average, a "
        "workspace document Link with its current section and digest, an "
        "authoritative URL used for the task, or a write attempt that failed "
        "at a known boundary and was changed to a patch workflow."
    ),
    (
        "Selecting core does not require every current-goal todo to be done "
        "or cancelled. When core.answer requests user input, unresolved todos"
        " may remain pending or in_progress; keep their status honest."
    ),
    "The action domain selection is mandatory for this phase.",
    (
        "Phase1 does not complete the Turn or produce final user output. It "
        "only updates Context and selects action domains."
    ),
)

# Phase TaskPrompt output. Used by kernel/loop/prompts.py:phase1_task_prompt.
PHASE1_EXPECTED_OUTPUT = (
    "# Expected Output\nCall select_action_domains with at least one valid domain. Call "
    "the relevant set/remove milestone or todo control tools in the same response "
    "whenever existing task state needs reconciliation; other context control tools "
    "remain optional. The domain selection call must be present before this phase can "
    "complete."
)

# Phase TaskPrompt guide. Used by kernel/loop/prompts.py:phase2_task_prompt.
PHASE2_GUIDANCE = (
    "You are in TinySoul Phase2.",
    "Generate concrete action tool calls for the selected domains.",
    "Only call actions that are useful for the current cycle.",
)

# Phase TaskPrompt output. Used by kernel/loop/prompts.py:phase2_task_prompt.
PHASE2_EXPECTED_OUTPUT = (
    "# Expected Output\nReturn one or more action tool calls with valid arguments."
)

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase1_task_prompt, kernel/loop/prompts.py:phase2_task_prompt.
PREVIOUS_FEEDBACK_HEADING = "Previous attempt feedback:\n"

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase2_task_prompt, kernel/loop/prompts.py:phase1_task_prompt.
TASK_GUIDE_HEADING = "# Task Guide\n"

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase2_task_prompt.
DOMAIN_SKILL_HEADING = "# Domain Skill\n"

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase1_task_prompt.
TASK_INPUT_HEADING = "# Task Input\n"

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase2_task_prompt.
SELECTED_DOMAINS_HEADING = "# Task Input\nSelected domains: "

# Model instruction or presentation. Used by kernel/loop/phases/phase1.py:run.
NO_DOMAIN_SELECTED = "Phase1 did not select any action domain."

# Model instruction or presentation. Used by kernel/loop/phases/tasks.py:_task_result_feedback.
INVALID_PHASE_OUTPUT = "LLM task output did not satisfy the phase protocol."


# Model context presentation or local feedback. Used by kernel/loop/turn.py:run.
def previous_cycle_failure(*, phase: str, reason: str) -> str:
    return f"Previous cycle {phase} failure ({reason}): "


# Model context presentation or local feedback. Used by kernel/loop/turn.py:run.
ACTIVE_JOBS_BLOCK_COMPLETION = "Resolve the active Jobs before completing this Turn."

# Model context presentation or local feedback. Used by kernel/loop/turn.py:run.
ENVIRONMENT_SOURCE_UNAVAILABLE = (
    "The selected environment source is unavailable; choose another action or"
    " ask the user."
)
# Local model feedback. Used by kernel/loop/phases/phase3.py:run.
CONFLICTING_CONTROL_INTENTS = (
    "Choose one answer, question or wait intent per Cycle; no actions were executed."
)
