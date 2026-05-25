
# Action-State-QueryLoop

## Action
Action（command pattern, The following are predefined built-in actions）
- answer（finish query-loop）(future)
- reasoning（reflection/planning/retrieve）(future)
- ask_user（refine requirements）(future)
- bash（run command）(future)
- INTERNAL_CALL（internal execution）
<!--- register_new_action-->
<!--- temporally_registered_actions-->
<!--memory-->
<!--subagent-->


### Action_Meta
（1）action_name：str

（2）action_cluster：{type, domain}
- type: INTERNAL | CLI | SCRIPT
- domain: MATH | WORKSPACE | MEMORY | KNOWLEDGE | VERSION_CONTROL | ...

示例：
- {"type": "INTERNAL", "domain": "MATH"}：calculate
- {"type": "INTERNAL", "domain": "WORKSPACE"}：scan_workspace, read_markdown_file
- {"type": "CLI", "domain": "VERSION_CONTROL"}：git
- {"type": "SCRIPT", "domain": "WORKSPACE"}：register_temporary_script

（3）action_profile（intrinsic traits and behavioral properties of the action）:
<!--- action_form(discrete、continuous、hybrid)-->
<!--- action_uncertainty(deterministic、stochastic), -->
- action_intention：string enum
  - EXTERNAL_PROBING：Query directory structure / Read documentation / Fetch web page content / Download online files；
  - INTERNAL_REASONING：reflection（why not work）/ planning（what should do and how to do）/ ask_user（refine requirements）/ retrieve memory and knowledge；
  - EXECUTION：Execute the plan / Generate answer / Edit files / Run command
- action_environment_effect：string enum
  - READ_ONLY；
  - ADDITIVE
  - MODIFYING
  - DESTRUCTIVE
- action_mode：string enum
  - SINGLE_RUN：executes once and completes within a bounded run；
  - ONGOING：has an explicit start/stop lifecycle and may emit intermediate messages while running
- llm_dependency: string enum
  - NONE
  - OPTIONAL
  - REQUIRED


（4）action_contract(selection, execution, and state-transition constraints of the action):
- applicability: struct
  - mode: string enum
    - ALWAYS_CONSIDER: this action should always be considered as a candidate during planning
    - CONDITIONAL: this action should be considered only when specific conditions are met
  - conditions: str_list # used when mode = conditional 
- preconditions: str_list # state dependencies required before execution
- postconditions: struct # what happens after taking this action
  - logical_state_effects: str_list # resulting updates to state
  - physical_environment_effects: str_list # resulting physical effects on files, processes, external systems, or runtime environment


### Action_Detail
 - parameter_schema: json_schema
 - examples: list[dict]
 - edge_case_handling: str_list
 
 
 


 ## State
 State（defined in `state/` module, independent from loop, runtime state for action tracking）
 
（1）todo_list：struct_list, what remains to be done
 - id: str # system-generated unique identifier (timestamp-based, e.g., verify-22161052)
 - semantic_key: str # normalized lowercase snake_case key from LLM input (e.g., verify_result)
 - display_key: str # system-generated readable identifier with sequence number (e.g., verify_result-1, verify_result-2)
 - description：str
 - status：union
   - PENDING
   - DONE
   - CANCELLED
 - created_at：datetime
 - completed_at：datetime | null

todo_list semantics(additional explanation)
- semantic_key normalization: LLM input is normalized to lowercase snake_case (spaces and hyphens become underscores)
- display_key generation: assigned sequentially per semantic_key (first -> key-1, second -> key-2)
- key exposure to LLM: the "key" field exposed in current_state is semantic_key when unique across ALL history; display_key when semantic_key has been reused 2+ times (regardless of status)
- matching rules for complete/cancel:
  1. Exact match on display_key
  2. Exact match on semantic_key — only if exactly one PENDING todo matches
  3. If multiple PENDING todos share the same semantic_key, raise TodoAmbiguityError (feedback to LLM)
- all tasks (including DONE/CANCELLED) participate in conflict detection to avoid key collisions between historical and current tasks
 

（2）milestone_list：str_list, what important progress has been achieved  
 - important completed transaction descriptions
 - key progress checkpoints
 - achieved intermediate goals

 
（3）action_record_list：struct_list, what has been executed and what results were produced; newly added action records have read == false
 - action_name：str
 - action_target：str
 - action_input：dict
 - action_result：dict
 - timestamp：datetime
 - turn：int # turn number where the action was executed (1-based)
 - read：bool # Unread by default
 
 action_record_list semantics(additional explanation)
 - single-run action：one execution usually produces one action record
 - ongoing action：multiple outputs may produce multiple action records
 - action_record_list is append-oriented and serves as runtime execution memory
 - when constructing `current_state` for LLM context:
   - the full `action_record_list` is formatted as a static boundary at the top of `current_state`
   - unread action records are consumed explicitly and provided as a separate `new_action_records` block for Step 3

（4）ongoing_action_list：str_list, which long-running actions are still active  
 - running action names for actions with `action_mode = ongoing`

（5）loop_error_list：struct_list, errors encountered during query loop execution
 - turn：int # turn number where the error occurred (1-based)
 - step：str # "choose_action" | "take_action" | "update_state"
 - error_type：str # "LLMError" | "ValueError"
 - message：str # error description
 - timestamp：datetime
 

## Agent_Query_Loop

- Input:
  - query
  - target
  - available_actions
  - init_todo_list: Optional[List[TodoItem]]
  - workspace(detail:workspace.md)
  - behavior_drafts(future)

- Init:
  - init QueryLoop with Inputs
  - build system context with:
    - basic_system
    - query_loop_system
  - Action schema and State schema are injected into each step's user prompt via InputSpec.data rather than living in the system context

- Loop:
  - Step 1: choose action
    - use llm_call to select one action from available_actions based on query, target, current_state, workspace, action_meta_list (of available actions)
    - expected format: {"action_name": "<action_name>", "selection_reason": "<selection_reason>"}
    - extract action_name and action_target # here action_target is the LLM-provided selection reason
    - on error (LLM call failure or parse error): record error into state(loop_error_list) and continue to next turn

  - Step 2: generate action arguments and then take action
    - use llm_call to generate action arguments for selected_action based on query, target, current_state, workspace, action_detail (of selected action)
    - expected format: JSON object
    - parse action arguments
    - execute selected action with generated arguments through the ContextProvider protocol
    - record action result into state(action_record_list)
    - on error (LLM call failure or parse error): record error into state(loop_error_list) and continue to next turn

  - Step 3: update state
    - use llm_call to update runtime state based on query, target, current_state, workspace and new_action_records
    - current_state places action_record_list, loop_error_list at the top (static boundary), followed by current_turn, todo_list, milestone_list, and ongoing_action_list
    - unread action_records are consumed explicitly before building the update-state prompt and are then marked as read (implemented)
    - expected format: JSON object
      ```json
      {
        "todo_operations": [
          {"operation": "add", "key": "<key>", "description": "<description>"},
          {"operation": "complete", "key": "<key>"},
          {"operation": "cancel", "key": "<key>"}
        ],
        "milestone_operation": "add" | "no-change",
        "milestone_param": "<description>" | null,
        "finished": true | false
      }
      ```
      - todo_operations: empty array [] means no TODO changes
      - milestone_operation: "add" to add a milestone, "no-change" for no update
      - milestone_param: required when milestone_operation is "add"; null otherwise
      - finished: true if target achieved, false otherwise
      (future: remove explicit finished flag and let a dedicated answer action terminate the loop)
    - apply todo_list updates if any
    - apply milestone_list updates if any
    - stop loop if finished == yes (future: remove explicit finished flag and let a dedicated answer action terminate the loop)
    - on error (LLM call failure or parse error): record error into state(loop_error_list), reset updates to safe defaults (finished=no), and continue

- unread action_records are consumed explicitly during update-state prompt construction and are then marked as read

Between Step2 and Step3，LLM-dependent actions（e.g. create_markdown_file, edit_markdown_file）receive runtime context through the ContextProvider protocol. The action's execute function uses the context_provider to access user_query, loop_target, current_state, and workspace, constructs its own prompt, reads referenced files, and invokes llm_call internally to generate content. (detail:workspace.md)
