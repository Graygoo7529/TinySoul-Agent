
# Action-State-QueryLoop

## Action
Action（command pattern, The following are predefined built-in actions）
- answer（finish query-loop）
- reasoning（reflection/planning/retrieve）
- ask_user（refine requirements）
- bash（run command）
- defined_tool（function-call）
<!--- register_new_action-->
<!--- temporally_registered_actions-->
<!--memory-->
<!--subagent-->


### Action_Meta
（1）action_name：str

（2）action_cluster：<domain, topic>
- predefined-basic
- predefined-file
- predefined-system
- predefined-memory
- feishu-table
- feishu-doc

（3）action_profile（intrinsic traits and behavioral properties of the action）:
<!--- action_form(discrete、continuous、hybrid)-->
<!--- action_uncertainty(deterministic、stochastic), -->
- action_type：union
  - 0-function-call：basic actions；
  - 1-cli-command：bash cli tool；
  - 2-persistent-script：persistent-scripts；
  - 3-temporary-script：temporary scripts；
- action_intention：union
  - 0-external-probing：Query directory structure / Read documentation / Fetch web page content / Download online files；
  - 1-internal-reasoning：reflection（why not work）/ planning（what should do and how to do）/ ask_user（refine requirements）/ retrieve memory and knowledge；
  - 2-execution：Execute the plan / Generate answer / Edit files / Run command
- action_environment_effect：union
  - 0-read-only；
  - 1-additive
  - 2-modifying
  - 3-destructive
- action_mode：union
  - 0-single-run：executes once and completes within a bounded run；
  - 1-ongoing：has an explicit start/stop lifecycle and may emit intermediate messages while running
- llm_dependency: union
  - 0-none
  - 1-optional
  - 2-required


（4）action_contract(selection, execution, and state-transition constraints of the action):
- applicability: struct
  - mode: union
    - 0-always_consider: this action should always be considered as a candidate during planning
    - 1-conditional: this action should be considered only when specific conditions are met
  - conditions: str_list # used when mode = conditional 
- preconditions: str_list # state dependencies required before execution
- postconditions: struct # what happens after taking this action
  - logical_state_effects: str_list # resulting updates to state
  - physical_environment_effects: str_list # resulting physical effects on files, processes, external systems, or runtime environment


### Action_Detail
 - parameter_schema: json_schema
 - examples: str_list
 - edge_case_handling: str_list
 
 
 


 ## State
 State（kept in query_loop, runtime state for action tracking）
 
（1）todo_list：struct_list, what remains to be done
 - description：str
 - status：union
   - 0-pending
   - 1-done
   - 2-cancelled
 - created_at：datetime
 - completed_at：datetime | null
 

 （2）milestone_list：str_list, what important progress has been achieved  
 - important completed transaction descriptions
 - key progress checkpoints
 - achieved intermediate goals

 
 （3）action_record_list：struct_list, what has been executed and what results were produced; newly added action records have read == false
 - action_name：str
 - action_target：str
 - action_input：str # JSON string
 - action_result：str
 - timestamp：datetime
 - read：bool # Unread by default
 
 action_record_list semantics(additional explanation)
 - single-run action：one execution usually produces one action record
 - ongoing action：multiple outputs may produce multiple action records
 - action_record_list is append-oriented and serves as runtime execution memory
 - when constructing `current_state` for LLM context:
   - the full `action_record_list` may be summarized as compact lines of `(action_name, action_target, action_input, action_result)`
   - unread action records may be provided with more detailed information as the latest execution delta

 （4）ongoing_action_list：str_list, which long-running actions are still active  
 - running action names for actions with `action_mode = ongoing`

 （5）workspace: struct, current workspace (future)
 - workspace_desc: str
 - directory_structure: str # JSON string
 - workspace_location: absolute path
 
 （6）resource_map：struct_list what resources currently exist or matter in the workspace / environment (future)
 - resource_type：union
   - 0-markdown
   - 1-doc
   - 2-url
   - 3-temporary-script
   - 4-temporary-draft
   - 5-other
 - resource_name：str
 - resource_desc：str
 - resource_location：str, relative to workspace or web url

resource_map semantics(additional explanation)
 - `resource_desc` provides a short semantic summary of the resource
 - `resource_location` stores the concrete location, such as a workspace-relative path, URL
 

## Agent_Query_Loop

- Input:
  - query
  - target
  - available_actions
  - init_todo_list
  - workspace(future)
  - resource_map(future)
  - behavior_drafts(future)

- Init:
  - init QueryLoop with Inputs
  - build system context with:
    - basic_system
    - query_loop_system
    - Action schema
    - State schema

- Loop:
  - Step 1: choose action
    - use llm_call to select one action from available_actions based on query, target, current_state, action_meta_list (of available actions)
    - expected format: [ACTION_SELECT]<action_name>:<selection_reason>
    - extract action_name and action_target # here action_target is the LLM-provided selection reason

  - Step 2: take action
    - use llm_call to generate action arguments for selected_action based on query, target, current_state, action_detail (of selected action)
    - expected format: JSON object
    - parse action arguments
    - execute selected action with generated arguments
    - record action result into state(action_record_list)

  - Step 3: update state
    - use llm_call to update runtime state based on query, target, and current_state # current_state used in this step already includes the latest appended action_record, and unread action_records are consumed when building the update-state prompt and then marked as read (future: ensure unread action_records are consumed only during update-state prompt construction)
    - expected format:
      - [TODO_LIST]<operation>(<parameter>)
      - [MILESTONE]<operation>(<parameter>)
      - [FINISHED]<yes/no> (future: remove explicit finished flag and let a dedicated answer action terminate the loop)
    - apply todo_list updates if any
    - apply milestone_list updates if any
    - stop loop if finished == yes (future: remove explicit finished flag and let a dedicated answer action terminate the loop)

- unread action_records are consumed when building the update-state prompt and are then marked as read
