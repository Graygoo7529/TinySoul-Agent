STEP 2a - GENERATE PARAMETERS

Your task is to generate the exact JSON parameters required to execute the selected action.

This is the parameter-generation phase. The action was already chosen in Step 1. The `selection_reason` below explains why this action was selected - your parameters must align with that intent.

Parameter Generation Guide:
1. Strictly follow the parameter_schema
2. Are derived from the query_events and current context
3. Are complete and valid (all required fields included)
4. Use appropriate data types
5. Align with the selection_reason - the parameters should fulfill the specific intent described in the selection_reason

LIGHTWEIGHT PARAMETER CONTRACT:
- Action parameters are ROUTES, not PAYLOADS. Do NOT embed large file contents, long documents, or raw data directly into parameter fields (especially "instruction", "content", "script", "data").
- If the task involves existing file contents, use "reference_accesses" or "target_access" to reference workspace files by path. The action executor will read the files internally.
- If the task produces a long output, the action will write it to a workspace file; you do NOT need to include the full output in the parameters.
- "instruction" fields should be concise natural-language directions (1-3 sentences), NOT the full text to be written.
- Keep action_input small enough that it can be stored in action_record_list without bloating the state context for future turns.

For different action types:
- ask_user: Provide clear, contextual question
- workspace actions (create/edit/read markdown or script): Provide target_access, a brief instruction, and optional reference_accesses pointing to existing files. Never paste file contents into the instruction.
- Custom actions: Follow the parameter_schema exactly
