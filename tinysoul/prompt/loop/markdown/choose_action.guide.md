STEP 1 - CHOOSE ACTION

Your task is to analyze the current situation and select the appropriate action(s) to take next.

IMPORTANT: You see ONLY action metadata (name, description, cluster, profile, contract). You do NOT see parameter_schema or examples yet. Parameter generation happens in Step 2a after an action is chosen.

You may select ONE action or MULTIPLE actions that can execute in parallel.
Use multiple actions ONLY when they are completely independent - no action's result is needed by another.

Selection Criteria:
1. Progresses toward the loop_target
2. Is appropriate given the current_state
3. Has satisfied preconditions (check state and constraints)
4. Provides maximum value for the current turn

When to use MULTIPLE actions:
- Multiple information-gathering actions with no dependencies (e.g., read two unrelated files)
- Multiple probes that don't affect each other's state
- NEVER parallelize actions where one produces data needed by another

When to use SINGLE action:
- Actions with sequential dependencies (one's output is another's input)
- State-modifying actions that might conflict (e.g., two edits to the same file)
- When uncertain about independence

Consider:
- Are there PENDING items in todo_list that need action?
- Are there ongoing actions that need monitoring?
- What is the logical next step toward completion?
- Which action's postcondition best advances the goal?

TERMINATION RULE (hard constraint):
When ALL of the following are true, you MUST select the `answer` action and NO other action:
- The loop_target has been achieved or the user's query has been fully addressed
- All PENDING todos have been completed or cancelled
- No ongoing actions require monitoring
- The required information is present in action_record_list and milestones

Do NOT select verification, probing, or scanning actions after the task is complete. The `answer` action is the ONLY valid terminator of the query loop.
