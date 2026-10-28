"""Model-visible text owned by kernel.loop.

Consumers listed below decide visibility, role, data and failure semantics.
"""

# Phase TaskPrompt guide. Used by kernel/loop/prompts.py:phase1_task_prompt.
PHASE1_GUIDANCE = (
    "You are in TinySoul Phase1: understand the current state and choose action domains.",
    (
        "First, reconcile existing milestones and todos with authoritative ActionResults in Context. "
        "Update completed todos, record valuable facts to milestones (computed values, refs, decisions, "
        "failure causes), and remove stale entries. Milestones are factual registers, not todo mirrors."
    ),
    (
        "Then, consider: what does the current goal need? What evidence is missing? What actions would "
        "materially advance progress? Select action domains that address these needs."
    ),
    (
        "If the Turn is ready to deliver a result or request user input, select core for core.answer. "
        "Selecting core does not require all todos to be done; keep their status honest."
    ),
    (
        "If one approach has been blocked, reflect on the limiting condition before selecting domains. "
        "Consider different execution paths or capabilities rather than repeating the same attempt."
    ),
    (
        "For complex tasks, work in small steps across multiple Cycles: each Cycle should make bounded, "
        "verifiable progress—inspect one part, modify one section, test one change—rather than attempting "
        "everything at once. Small steps enable verification and adjustment."
    ),
    (
        "Phase1 only updates Context and selects action domains. Phase2 generates action calls for those "
        "domains; Phase3 executes accepted calls and returns results to the next Cycle."
    ),
    "The action domain selection is mandatory for this phase.",
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
    "You are in TinySoul Phase2: construct concrete actions for the selected domains.",
    (
        "Choose actions that materially advance the current goal: obtain missing evidence, "
        "resolve an uncertainty, perform necessary work, verify results, or produce the final answer."
    ),
    (
        "Use known refs when accessing existing resources. When constructing action parameters, "
        "use exact references from Context (workspace:path, memory:entity/name, etc.) rather than "
        "inventing refs for existing resources. For actions that create resources, choose a new "
        "target ref according to the tool definition."
    ),
    (
        "If a previous attempt failed, adjust the limiting condition: change parameters that were "
        "rejected, use different capabilities, or alter the execution path. Understand why it failed."
    ),
    (
        "For complex operations, break them into small, bounded steps: read one section first, then edit it; "
        "search for one pattern, inspect results, then search for the next; modify one file, verify it, "
        "then move to the next. Each action should produce verifiable results before continuing."
    ),
    "Only call actions that are useful for the current cycle.",
)

# Phase TaskPrompt output. Used by kernel/loop/prompts.py:phase2_task_prompt.
PHASE2_EXPECTED_OUTPUT = (
    "# Expected Output\nReturn one or more action tool calls from the current tool "
    "definitions, with valid arguments for the selected domains and this Cycle's intent."
)

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase1_task_prompt, kernel/loop/prompts.py:phase2_task_prompt.
PREVIOUS_FEEDBACK_HEADING = "Previous cycle feedback:\n"

# Model instruction. Used by kernel/loop/prompts.py:_turn_guide_blocks.
TURN_GUIDANCE_HEADING = "# Turn Guidance\n"
TURN_GUIDANCE_SCOPE = (
    "Apply this Turn guidance through the tools available in the current phase."
)

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase2_task_prompt, kernel/loop/prompts.py:phase1_task_prompt.
TASK_GUIDE_HEADING = "# Task Guide\n"

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase2_task_prompt.
DOMAIN_SKILL_HEADING = "# Domain Skill\n"

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase1_task_prompt.
TASK_INPUT_HEADING = "# Task Input\n"

# Model instruction or presentation. Used by kernel/loop/prompts.py:phase2_task_prompt.
def phase2_input(*, domains: tuple[str, ...], intent: str) -> str:
    text = "# Task Input\nSelected domains: " + ", ".join(domains)
    return text + f"\nCycle intent: {intent}" if intent else text


# Model instruction or presentation. Used by kernel/loop/phases/phase1.py:run.
NO_DOMAIN_SELECTED = "Phase1 did not select any action domain."

# Model instruction or presentation. Used by kernel/loop/phases/tasks.py:_task_result_feedback.
INVALID_PHASE_OUTPUT = "LLM task output did not satisfy the phase protocol."

# Model context feedback. Used by kernel/loop/phases/phase1.py.
def phase1_task_failure(*, feedback: str) -> str:
    return (
        "Phase1 did not complete; this response's Context controls were not applied. "
        f"Cause: {feedback} Select the needed action domains in Phase1; "
        "concrete action calls are generated in Phase2."
    )


# Model context feedback. Used by kernel/loop/phases/phase1.py.
def phase1_domain_failure(*, feedback: str) -> str:
    return (
        "Phase1 did not complete; this response's Context controls were not applied. "
        f"Cause: {feedback} Call select_action_domains with the domains needed for "
        "this Cycle; use the available Context controls when needed."
    )


# Model context feedback. Used by kernel/loop/phases/phase2.py.
def phase2_task_failure(*, feedback: str, domains: tuple[str, ...]) -> str:
    return (
        "Phase2 did not complete; no Action from this response was accepted or "
        f"executed. Cause: {feedback} Selected domains: {', '.join(domains)}. "
        "In the next Cycle, select the domains needed for the intended actions "
        "and use their current tool definitions in Phase2."
    )


# Model context feedback. Used by kernel/loop/phases/phase2.py.
PHASE2_SCOPE_NOT_AVAILABLE = (
    "Phase2 could not prepare an Action scope; no Action from this response was executed."
)


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
