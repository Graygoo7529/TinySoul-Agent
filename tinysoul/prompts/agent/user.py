"""User Turn guidance injected by agent.user.builder into both decision phases."""

USER_TURN_GUIDANCE = (
    "Continue the current user request using the available Context and actions.",
    (
        "Explore before deciding: check Context for relevant knowledge, history and evidence; "
        "use inspect/search to recall details; investigate anomalies causally."
    ),
    (
        "Work in small, iterative steps: explore content in bounded chunks (one file, one section); "
        "modify files in small, verifiable changes; complete complex tasks across multiple Cycles, "
        "each making bounded progress. Verify each step before continuing."
    ),
    (
        "When one approach is blocked, try different parameters, capabilities or execution paths "
        "rather than repeating the same attempt. Reflect on progress and adjust strategy."
    ),
    (
        "When continued progress depends on consequential human judgment, user-held information, "
        "permission, a choice among feasible routes, or evidence insufficient for responsible "
        "completion, call core.ask to pause and wait for user reply, or core.answer to conclude "
        "this Turn with a focused question or request for direction."
    ),
    "Finish only by calling core.answer with the response intended for the user.",
)
