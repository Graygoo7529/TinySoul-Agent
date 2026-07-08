# 20260708 workspace home implementation plan

## 状态

status: in_progress

本文记录 Workspace 与 Agent Home 后续能力的实施规划。目标是在既有模块边界上继续推进，不把 workspace 文件正文写入 Context 或普通 ActionResult，不让 AppBuilder 回到业务实现层。

## 设计原则

- Workspace 继续作为 `workspace:` 链接的唯一语义归属方，负责路径边界、manifest、资源摘要、正文切片和后续写入能力。
- Agent Home 继续作为 `home:` 链接的唯一语义归属方，负责顶层背景、渐进资源、runtime home 副本、HOW/MEMORY 和每日沉淀。
- Context 只构造 MessageStack，不直接读取 workspace 或 home 文件。
- Workspace 正文只作为临时 task prompt input 或 action 内部输入使用，不进入 WorkingContext、BackgroundContext 或普通 TurnTrace action result。
- Agent Home 原始目录保持只读，运行期写入落在 runtime home，最终由每日沉淀决定是否合并。

## 分期规划

### 1. Workspace 正文切片与临时输入

status: done

`WorkspacePromptInput` 已改为承载 `WorkspaceTextSlice`，能够表达正文来源、范围、截断状态、大小和 digest；`WorkspaceEngine.read_text_slice` 已支持按行读取长文件局部片段，`WorkspaceEngine.prepare_task_input` 继续支持前缀读取并生成 `prefix:<limit>` slice。本阶段未新增模型可见 `workspace.read` action。

对应实现位置：

- `tinysoul/infra/filesystem.py`：`read_text_line_slice`；
- `tinysoul/workspace/engine.py`：`WorkspaceTextSlice`、`WorkspacePromptInput.slices`、`WorkspaceEngine.read_text_slice`；
- `tests/workspace/test_workspace_engine.py`：前缀 task input、行范围读取、字符截断和参数契约测试。

本阶段实施：

- 增加 `WorkspaceTextSlice`，表达一个 workspace 文本片段；
- 将 `WorkspacePromptInput` 从 `WorkspaceTextRead` 集合调整为 slice 集合；
- 保留 `render()` 作为临时文本渲染能力，但语义改为渲染 slices；
- 增加按行读取能力，支持长文件局部读取；
- 不新增模型可见 `workspace.read` action。

### 2. Workspace 写入、patch、delete

status: done

已增加 `workspace.write`、`workspace.patch`、`workspace.delete`。这些 action 的成功结果只返回 link、summary、size、mtime、digest 等摘要，不返回正文；失败优先收敛为局部 ActionResult。`workspace.patch` 当前采用精确单点文本替换：`old_text` 必须非空且只出现一次，`new_text` 可为空，`expected_digest` 可用于防止陈旧编辑。

对应实现位置：

- `tinysoul/workspace/engine.py`：`write_text`、`patch_text`、`delete_resource`、manifest upsert/remove；
- `tinysoul/workspace/actions.py`：`WorkspaceWriteExecutor`、`WorkspacePatchExecutor`、`WorkspaceDeleteExecutor`；
- `tinysoul/action/builtin/workspace/actions/`：`write.toml`、`patch.toml`、`delete.toml`；
- `tinysoul/app/builder.py`：Workspace write/patch/delete executor 注册；
- `tests/workspace/test_workspace_engine.py`：Engine 副作用、action metadata payload、WorkingPatch signal 和局部失败测试；
- `tests/action/test_catalog_loader.py`：内置 catalog 动作视图更新。

### 2.5 Workspace PromptBlock 与 llm_step 接入

status: done

已将 Workspace 文本引用接入 Context `PromptBlock` 与 `llm_step`。`llm_step.context_task` 的主要任务输入语义改为可切分的 `task_inputs` 与 `references`，旧 `task_input` 仅作为兼容入口转换为一个 PromptBlock。Workspace 模块提供 `WorkspacePromptReferenceResolver` 解析 `workspace.text` 引用，未指定行范围时使用前缀读取，指定 `start_line` 或 `max_lines` 时使用行范围切片。内置 `core.reason` 使用 `llm_step.context_task`，可作为通用只读推理动作消费 workspace references。

对应实现位置：

- `tinysoul/action/backends/llm_step.py`：可切分 `task_inputs`、`references` 与 `PromptReferenceResolver`；
- `tinysoul/action/backends/llm_step_registration.py`：`llm_step` action registrar；
- `tinysoul/workspace/prompts.py`：`WorkspacePromptReferenceResolver` 与 Workspace PromptBlock 转换；
- `tinysoul/action/builtin/core/actions/reason.toml`：通用只读推理动作；
- `tinysoul/app/builder.py`：向 `llm_step` 注入 workspace reference resolver；
- `tests/action/test_llm_step.py`、`tests/workspace/test_workspace_engine.py`：任务输入切分、引用解析和 workspace block 测试。

### 3. Agent Home 检索与 runtime 写入

status: pending

增加 Home 顶层检索和 runtime home 写入能力：

- `home.top.search` 返回候选顶层链接、摘要和短片段；
- `home.resource.write` 与 `home.resource.patch` 写入 runtime home；
- 写入前若 runtime 副本缺失，继续走 `HOME_RUNTIME_COPY_REQUIRED` Trap。

### 4. Memory 与 HOW feedback

status: pending

增加 `home.memory.append` 与 `home.how.record_feedback`，写入 runtime home 的当日草稿：

- `runtime/home/this_day_memory.md`
- `runtime/home/how/<skill>/SKILL_MEMORY.md`
- `runtime/home/how_action/<domain>/DOMAIN_MEMORY.md`

### 5. Daily settlement

status: pending

在检索、写入和反馈能力稳定后，设计 `AgentHomeSettlementEngine`，基于 TurnSummary、runtime home diff、HOW feedback 和 workspace archive summary 生成可审阅的合并结果。

## 下一阶段实施边界

下一阶段推进第 3 阶段：Agent Home 顶层检索与 runtime home 写入。实现时继续保持原始 Agent Home 只读，写入落在 runtime home，副本缺失继续走 `HOME_RUNTIME_COPY_REQUIRED` Trap。

## 验收点

- `WorkspacePromptInput` 以 `WorkspaceTextSlice` 为核心；
- 前缀读取仍可生成临时 task input；
- 行范围读取可以读取长文件局部片段；
- 读取能力仍不暴露为模型侧 `workspace.read` action；
- `workspace.write`、`workspace.patch`、`workspace.delete` 成功结果不携带文件正文；
- workspace 变更 action 通过 `context.working.patch` 同步资源摘要或资源移除；
- workspace 变更 action 的参数和文件失败收敛为局部 `ActionResult`；
- `llm_step.context_task` 支持可切分 `task_inputs` 与 `references`；
- `workspace.text` references 可解析为 Context `PromptBlock`；
- `core.reason` 可通过 workspace references 执行通用只读推理；
- 现有 `workspace.scan` / `workspace.describe` 行为保持；
- `python -m pytest tests -q` 与 `python -m ty check` 通过。
