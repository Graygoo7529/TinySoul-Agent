# Workspace

Workspace（external file-system context module for query-loop, independent from State）

`Workspace` 定义于 `tinysoul.context.workspace`，`ResourceItem` 与 `ChangeLogItem` 与其同处一处。

## Workspace

（1）workspace_location：str # absolute path of the workspace directory, all relative resource_access paths are resolved against this location

（2）workspace_desc：str | null # optional semantic description of the workspace purpose

（3）resources：struct_list, what files and external resources currently exist or matter in the workspace
 - resource_name：str # file name in disk
 - resource_type：union
   - MARKDOWN
   - PY
   - PDF
   - DOCX
 - resource_access：str # workspace-relative path
 - resource_desc：struct
   - summary：str # neutral content summary of the resource, stable across loops
   - relevance：str # relationship between this resource and the current query / loop_target; query-specific, cleared at loop start
 - change_log：struct_list
   - turn：int # turn number where the operation occurred (1-based)
   - operation：union
     - READ
     - CREATED
     - EDITED
   - summary：str # semantic summary of the change
   - timestamp：datetime # operation timestamp (ISO-8601 when serialized)

workspace semantics(additional explanation)
- workspace is independent from State and is placed as a separate context block below CURRENT STATE in the LLM prompt
- resources provide both structural context (what exists) and semantic context (what it means for the current task)
- change_log serves as the audit trail for resource mutations across query-loop turns
- temp files with the temp_yymmdd_ prefix are identified by naming convention; temp_yymmdd_content.md is markdown, temp_yymmdd_script.py is py
- `resource_access` is the canonical workspace-local identifier for a resource
- `resource_name` is a display-friendly file name, typically the basename of `resource_access`



## Workspace_Action

Workspace_Action（command pattern, predefined built-in actions for workspace management）
- scan_workspace（detect and synchronize workspace resources with disk）
- read_markdown_file（read markdown file and update resource_desc via llm）
- create_markdown_file（create markdown file in disk and workspace via llm）
- edit_markdown_file（edit markdown file in disk and update in workspace via llm）
- delete_file（delete file from disk and workspace）


### scan_workspace

（1）action_name：scan_workspace # can scan pdf、py、docx，can not read now

（2）action_cluster：{"type": "INTERNAL", "domain": "WORKSPACE"}

（3）action_profile：
- action_intention：EXTERNAL_PROBING
- action_environment_effect：READ_ONLY
- action_mode：SINGLE_RUN
- llm_dependency：NONE

（4）action_contract：
- applicability：
  - mode：CONDITIONAL
  - conditions：["workspace.resources is empty", "workspace may be inconsistent with disk"]
- preconditions：["workspace_location must be a valid absolute path"]
- postconditions：
  - logical_state_effects：["Preserves `resource_desc` and `change_log` for resources whose `resource_access` still exists on disk", "Removes stale resources whose `resource_access` no longer exists on disk", "Adds new resources for newly discovered files on disk"]
  - physical_environment_effects：[]

（5）action_detail：
- parameter_schema：{
    "type": "object",
    "properties": {},
    "required": []
  }
- examples：[
    {}
  ]
- edge_case_handling：[
  ]


### read_markdown_file

（1）action_name：read_markdown_file

（2）action_cluster：{"type": "INTERNAL", "domain": "WORKSPACE"}

（3）action_profile：
- action_intention：EXTERNAL_PROBING
- action_environment_effect：READ_ONLY
- action_mode：SINGLE_RUN
- llm_dependency：REQUIRED

（4）action_contract：
- applicability：
  - mode：CONDITIONAL
  - conditions：["need to understand content of a workspace markdown file", "need to update resource_desc for an existing resource"]
- preconditions：["target_access must point to an existing markdown file in workspace", "file must be within workspace_location boundary"]
- postconditions：
  - logical_state_effects：["Updates resource_desc.summary and resource_desc.relevance for the target resource", "Appends READ entry to change_log"]
  - physical_environment_effects：[]

（5）action_detail：
- parameter_schema：{
    "type": "object",
    "properties": {
      "target_access": {
        "type": "string",
        "description": "Relative path of the markdown file in workspace"
      }
    },
    "required": ["target_access"]
  }
- examples：[
    {"target_access": "docs/design_notes.md"}
  ]
- edge_case_handling：[
    "File not found: return error without modifying workspace",
    "Non-markdown file: reject with error",
    "Path traversal outside workspace: reject with error"
  ]


### create_markdown_file

（1）action_name：create_markdown_file

（2）action_cluster：{"type": "INTERNAL", "domain": "WORKSPACE"}

（3）action_profile：
- action_intention：EXECUTION
- action_environment_effect：ADDITIVE
- action_mode：SINGLE_RUN
- llm_dependency：REQUIRED

（4）action_contract：
- applicability：
  - mode：CONDITIONAL
  - conditions：["need to create a new markdown document in workspace"]
- preconditions：["target_access must not already exist in workspace", "file path must be within workspace_location boundary", "must not conflict with existing target_access"]
- postconditions：
  - logical_state_effects：["Adds a new ResourceItem to workspace.resources", "Initializes resource_desc and change_log"]
  - physical_environment_effects：["Creates a new file on disk at the specified relative path"]

（5）action_detail：
- parameter_schema：{
    "type": "object",
    "properties": {
      "target_access": {
        "type": "string",
        "description": "Relative path for the new file"
      },
      "instruction": {
        "type": "string",
        "description": "Natural language instruction for what the file should contain"
      },
      "reference_accesses": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of workspace resource_access paths to attach as reference context"
      }
    },
    "required": ["target_access", "instruction"]
  }
- examples：[
    {"target_access": "notes/new_feature.md", "instruction": "Write a design doc for the new feature based on existing docs", "reference_accesses": ["docs/existing_arch.md"]}
  ]
- edge_case_handling：[
    "File already exists: reject with error, suggest edit_markdown_file instead",
    "Parent directory does not exist: auto-create directories",
    "Path traversal outside workspace: reject with error",
    "Missing reference resource: reject with error"
  ]


### edit_markdown_file

（1）action_name：edit_markdown_file

（2）action_cluster：{"type": "INTERNAL", "domain": "WORKSPACE"}

（3）action_profile：
- action_intention：EXECUTION
- action_environment_effect：MODIFYING
- action_mode：SINGLE_RUN
- llm_dependency：REQUIRED

（4）action_contract：
- applicability：
  - mode：CONDITIONAL
  - conditions：["need to modify an existing markdown file in workspace"]
- preconditions：["target_access must point to an existing markdown file in workspace", "file must be within workspace_location boundary"]
- postconditions：
  - logical_state_effects：["Updates resource_desc if content changed significantly", "Appends EDITED entry to change_log"]
  - physical_environment_effects：["Overwrites the file on disk with new content"]

（5）action_detail：
- parameter_schema：{
    "type": "object",
    "properties": {
      "target_access": {
        "type": "string",
        "description": "Relative path of the file to edit"
      },
      "instruction": {
        "type": "string",
        "description": "Natural language instruction for how to modify the file"
      },
      "reference_accesses": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of workspace resource_access paths to attach as reference context"
      }
    },
    "required": ["target_access", "instruction"]
  }
- examples：[
    {"target_access": "docs/design_notes.md", "instruction": "Add workspace section based on current state and action schema", "reference_accesses": ["docs/action-state-queryloop.md"]}
  ]
- edge_case_handling：[
    "File not found: reject with error",
    "Non-markdown file: reject with error",
    "Path traversal outside workspace: reject with error",
    "Missing reference resource: reject with error"
  ]


### delete_file

（1）action_name：delete_file

（2）action_cluster：{"type": "INTERNAL", "domain": "WORKSPACE"}

（3）action_profile：
- action_intention：EXECUTION
- action_environment_effect：DESTRUCTIVE
- action_mode：SINGLE_RUN
- llm_dependency：NONE

（4）action_contract：
- applicability：
  - mode：CONDITIONAL
  - conditions：["need to remove a file from workspace"]
- preconditions：["target_access must point to an existing file in workspace", "file must be within workspace_location boundary"]
- postconditions：
  - logical_state_effects：["Removes the corresponding ResourceItem from workspace.resources"]
  - physical_environment_effects：["Deletes the file from disk"]

（5）action_detail：
- parameter_schema：{
    "type": "object",
    "properties": {
      "target_access": {
        "type": "string",
        "description": "Relative path of the file to delete"
      }
    },
    "required": ["target_access"]
  }
- examples：[
    {"target_access": "temp_250415_content.md"}
  ]
- edge_case_handling：[
    "File not found: remove ResourceItem anyway and return success",
    "Path traversal outside workspace: reject with error"
  ]


## Workspace_Query_Loop_Integration

Workspace 在 Agent Query Loop 各阶段中的作用与位置。

### Prompt_Position

在 LLM Prompt 中，Workspace 作为独立上下文模块位于 CURRENT STATE 之后、TASK 指令之前。

Prompt 结构示例：
```
=== CURRENT STATE ===
{current_state_json}

=== WORKSPACE ===
{workspace_json}

...
```

workspace prompt semantics(additional explanation)
- workspace 与 current_state 之间没有嵌套关系，二者是并列的上下文块


### Step_Integration

- Step 1: choose action
  - use llm_call to select one action from available_actions based on query, target, current_state, workspace, action_meta_list (of available actions)
  - workspace 中的资源存在性、resource_desc 和 change_log 会影响 action 的适用性判断
  - 例如：若 workspace 中已存在相关 markdown 文件，LLM 可能选择 read_markdown_file 而非 create_markdown_file

- Step 2a: generate action arguments
  - use llm_call to generate action arguments for selected_action based on query, target, current_state, workspace, action_detail (of selected action)
  - 对于 create_markdown_file / edit_markdown_file，Step 2 仅生成参数：
    - target_access：目标文件路径
    - instruction：内容生成的自然语言指引
    - reference_accesses：需要读取并作为参考上下文的 workspace 资源路径列表（可选）
  - 完整的 content 不在 Step 2 中生成

- Step 2b: execute action（Step 2 的后续执行阶段）
  - execute selected action with generated arguments
  - 对于 create_markdown_file 和 edit_markdown_file，这两个 action 的 execute 函数内部具有较高的复杂度（llm_dependency = REQUIRED）
  - execute 函数会：
    1. 根据 action_input 中的 target_access 和 reference_accesses 读取 workspace 中对应文件的内容
    2. 对于 edit_markdown_file，将 target 文件的当前内容作为 current_content
    3. 对于 reference_accesses 中的资源，将其内容作为 reference_contents
    4. 通过 ContextProvider 获取通用上下文（user_query, loop_target, current_state, workspace），构造专属 prompt，结合 action 专属上下文（目标资源、参考资源、instruction、action 特殊提示词）
    5. 调用 llm 生成完整的 content（create_markdown_file 与 edit_markdown_file 均使用字段名 content）
    6. 将生成的内容写入磁盘，并更新 workspace 中的对应 ResourceItem（resource_desc, change_log）
    7. 返回本次 action 的结果（简洁摘要，执行成功/错误反馈）
  - 从 query_loop 的视角看，这仍然是一次普通的 action 执行，action result 为执行结果

- Step 3: update state
  - use llm_call to update runtime state based on query, target, current_state, workspace and new_action_records
  - workspace 本身的资源变更（resources 更新、change_log 追加）由 action 执行器负责
  - LLM 的 state-update 输出仅控制 State（todo_list, milestone_list, finished），不直接控制 workspace


## Workspace_Convention

（1）目录边界
- 所有文件操作（读、写、编辑、删除）必须限制在 workspace_location 目录内
- 禁止通过 ../ 或绝对路径跳出工作区

（2）临时文件命名规约
- 临时文件和临时脚本以 temp_yymmdd_ 为文件名开头
- 示例：temp_250415_content1.md, temp_250415_script1.py
- temp_yymmdd_content_filename 文件为 markdown 格式

## Workspace_Transfer

Workspace 可以作为 QueryLoop 的输入参数被传递到 QueryLoop 中。

- Input 字段：
  - workspace_location：str
  - workspace_desc：Optional[str]
  - resources：Optional[List[ResourceItem]]

- 初始化行为：
  - 若传入 workspace_location 但 resources 为空，QueryLoop 应在 Init 阶段触发 scan_workspace 进行自动初始化
  - 若传入完整的 workspace（含 resources），则直接使用，不再自动扫描


## Workspace_Invariants

workspace_location must be an absolute path
every resource_access must resolve within the workspace_location boundary
resource_access must be unique within workspace.resources
resource_name is non-unique and should not be used as the canonical identifier
change_log is append-only
file-system mutations must be reflected in workspace.resources within the same action execution

## Resource_Access_Resolution

resource_access is always interpreted as a path relative to workspace_location
resolving resource_access must normalize path separators and remove redundant . segments
any resolved path outside workspace_location must be rejected
absolute paths are not allowed as resource_access
