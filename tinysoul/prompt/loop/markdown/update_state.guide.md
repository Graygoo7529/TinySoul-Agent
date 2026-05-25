STEP 3 - UPDATE STATE

Your task is to evaluate the effects of recently executed actions and update the system state accordingly.

The `new_action_records` block below contains ONLY the action results from the current turn (since the last state update). Use these to assess progress.

Evaluate:
1. NEW ACTION RECORDS: Review the results of newly executed actions
   - Did the action succeed? What was the result?
   - Does the result indicate progress toward the target?
   - Are there side effects to consider?

2. TODO LIST: You may perform 0-2 TODO operations in a single update.
   You can mix add and complete/cancel freely.
   Each item in todo_operations must be a JSON object with an "operation" field and a "key" field.
   - {"operation": "add", "key": "<semantic_key>", "description": "<description>"} - Add a new subtask
   - {"operation": "complete", "key": "<key>"} - Mark the todo with the given key as done
   - {"operation": "cancel", "key": "<key>"} - Mark the todo with the given key as cancelled

3. MILESTONE LIST: Archive significant outcomes and discovered facts.
   Do not merely state that a task is finished; capture the valuable
   information the finished task produced.
   - add(<description>): A concise record of progress with concrete results.
   - no-change: No meaningful new outcome to archive.

Note on todo keys:
The todo_list exposes a key for each todo. If a semantic key has never been
reused across the entire history, it appears as-is (e.g., verify). Once a
semantic key has been used for 2+ todos (regardless of status), all todos
with that key are shown with a numbered suffix (e.g., verify-1, verify-2).
Use the exact key shown in the todo_list for complete/cancel operations.
