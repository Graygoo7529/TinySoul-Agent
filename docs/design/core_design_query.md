
# Action-State-QueryLoop

## Action
Action（command pattern, The following are predefined built-in actions）
- answer（finish query-loop）
- reasoning（reflection/planning/retrieve）
- ask_user（refine requirements / suspend loop）
- bash（run command）(future, BashExecutor 存在但未注册为默认 Action)
- INTERNAL_CALL（internal execution）
- calculate（math computation）
- average_dog_weight（knowledge retrieval）
- scan_workspace / read_file / create_markdown_file / edit_markdown_file / delete_file
- create_temporary_script / edit_temporary_script / register_temporary_script
- git（CLI, git subcommands）
- monitor（ONGOING, experimental）/ stop_ongoing_action



### Action_Meta
（1）action_name：str

（2）action_cluster：{type, domain}
- type: NATIVE | CLI | SCRIPT
- domain: MATH | WORKSPACE | MEMORY | KNOWLEDGE | VERSION_CONTROL | ...

示例：
- {"type": "NATIVE", "domain": "MATH"}：calculate
- {"type": "NATIVE", "domain": "WORKSPACE"}：scan_workspace, read_file
- {"type": "CLI", "domain": "VERSION_CONTROL"}：git
- {"type": "SCRIPT", "domain": "WORKSPACE"}：register_temporary_script

（3）action_profile（intrinsic traits and behavioral properties of the action）:
- action_intention：string enum
  - EXTERNAL_PROBING：Query directory structure / Read documentation / Fetch web page content / Download online files；
  - INTERNAL_REASONING：reflection（why not work）/ planning（what should do and how to do）/ ask_user（refine requirements）/ retrieve memory and knowledge；
  - EXECUTION：Execute the plan / Generate answer / Edit files / Run command
- action_environment_effect：string enum（描述性字段，当前无运行时强制）
  - READ_ONLY；
  - ADDITIVE
  - MODIFYING
  - DESTRUCTIVE
- action_mode：string enum
  - SINGLE_RUN：executes once and completes within a bounded run；
  - ONGOING：has an explicit start/stop lifecycle and may emit intermediate messages while running；running executions are tracked by `execution_id`
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
 - id: str # system-generated unique identifier (uuid4 short hex, e.g., a3f7b2c1)
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

 
（3）action_record_list：struct_list, what has been executed and what results were produced
 - action_name：str
 - action_target：str
 - action_input：dict
 - action_result：dict
 - execution_id：str # per-execution id used for correlation and ONGOING control
 - timestamp：datetime
 - turn：int # turn number where the action was executed (1-based)
 - read：bool # Unread by default
 
 action_record_list semantics(additional explanation)
 - single-run action：one execution usually produces one action record
 - ongoing action：multiple outputs may produce multiple action records
 - action_record_list is append-oriented and serves as runtime execution memory
 - when constructing `current_state` for LLM context:
   - the `action_record_list` is formatted at the top of `current_state`; recent records are shown in full detail and older ones are summarized
   - unread action records are peeked (not consumed) as a separate `new_action_records` block for Step 3

（4）ongoing_action_list：struct_list, which long-running action executions are still active
 - execution_id：str # stable id for this ONGOING execution, used by stop actions
 - action_name：str
 - turn：int # turn where the execution started
 - status：str # runtime status, e.g. running
 - started_at：datetime | null

ongoing_action_list semantics(additional explanation)
- ONGOING is tracked by execution, not by action_name; the same action_name may run multiple times concurrently
- `ONGOING_STARTED` adds an item by `execution_id`; `ONGOING_COMPLETED` removes the same `execution_id`
- explicit stop is modeled as a normal Action (e.g. `stop_ongoing_action`) that requests termination through the ContextProvider runtime control layer

（5）loop_error_list：struct_list, errors encountered during query loop execution
 - turn：int # turn number where the error occurred (1-based)
 - step：str # "choose_action" | "generate_parameters" | "execute_action" | "update_state"
 - error_type：str # e.g. "LLMResponseParseError" | "ActionExecutionError/ValueError"
 - message：str # error description
 - timestamp：datetime
 - auto_handled：bool # suppressed from feedback_error_list if True
 

## Agent_Query_Loop

- Input:
  - initial_query
  - target
  - available_actions
  - init_todo_list: Optional[List[TodoItem]]
  - workspace(detail:workspace.md)
  - behavior_drafts(future)

- Init:
  - init QueryLoop with Inputs
  - build loop-level system with:
    - external loop_system sources
    - builtin query_loop.system.md
  - expose loop-level system to internal LLM-dependent actions through `get_loop_level_system()`
  - internal LLM-dependent actions build system messages as:
    - loop-level system
    - action_execution_context.system.md
    - action-specific system
  - Action schema and State schema are injected into each step's user prompt via InputSpec.data rather than living in the system context

- Loop:
  - Step 1: choose action
    - use llm_call to select one action from available_actions based on query_events, target, current_state, workspace, action_meta_list (of available actions)
    - expected format: {"action_name": "<action_name>", "selection_reason": "<selection_reason>"}
    - extract action_name and action_target # here action_target is the LLM-provided selection reason
    - on error (LLM call failure or parse error): record error into state(loop_error_list) and continue to next turn

  - Step 2a: generate action arguments
    - use llm_call to generate action arguments for selected_action based on query_events, target, current_state, workspace, action_detail (of selected action)
    - expected format: JSON object conforming to parameter_schema
    - parse action arguments
    - on error (LLM call failure or parse error): record error into state(loop_error_list) and continue to next turn

  - Step 2b: execute action
    - execute selected action with generated arguments through the ContextProvider protocol
    - action input is validated by `validate_action_input()` before execution
    - record action result into state(action_record_list)
    - on error (Action execution failure): record error into state(loop_error_list) and continue to next turn

  - Step 3: update state
    - **peek unread action_records**: call `peek_new_action_records()` to read unread records without modifying their `read` flag
    - use llm_call to update runtime state based on query_events, target, current_state, workspace and new_action_records
    - current_state places action_record_list and feedback_error_list (derived from loop_error_list, auto-handled errors suppressed) at the top, followed by todo_list, milestone_list, and ongoing_action_list
    - expected format: JSON object
      ```json
      {
        "todo_operations": [
          {"operation": "add", "key": "<key>", "description": "<description>"},
          {"operation": "complete", "key": "<key>"},
          {"operation": "cancel", "key": "<key>"}
        ],
        "milestone_operation": "add" | "no-change",
        "milestone_param": "<description>" | null
      }
      ```
      - todo_operations: empty array [] means no TODO changes
      - milestone_operation: "add" to add a milestone, "no-change" for no update
      - milestone_param: required when milestone_operation is "add"; null otherwise
    - apply todo_list updates if any (each operation isolated by independent try/except)
    - apply milestone_list updates if any
    - **ack action_records**: call `ack_action_records()` to mark all peeked records as read after successful update
    - loop termination is handled by the `answer` action emitting `LOOP_COMPLETE` signal, not by an explicit `finished` flag in Step 3
    - on error (LLM call failure or parse error): record error into state(loop_error_list), skip ack so records remain unread for next turn, and continue

- unread action_records are **peeked** during update-state prompt construction, then **acked** only after the update is successfully applied. If Step 3 fails, records remain unread for the next turn.

Between Step2 and Step3，LLM-dependent actions（e.g. create_markdown_file, edit_markdown_file）receive runtime context through the ContextProvider protocol. The action's execute function uses the context_provider to access query_events, loop_target, current_state, and workspace, constructs its own prompt, reads referenced files, and invokes llm_call internally to generate content. (detail:workspace.md)

- Resume:
  - `resume(user_response)` continues execution after a previous `query_loop()` returned `status=SUSPENDED`
  - `query_loop()` and `resume()` both return `LoopOutcome`; callers inspect `status` to determine the outcome
  - if the loop is not in suspended state or no inquiry is found, `resume()` returns `LoopOutcome(status=ABORTED, error_type="ResumeStateError", ...)` instead of raising an exception
