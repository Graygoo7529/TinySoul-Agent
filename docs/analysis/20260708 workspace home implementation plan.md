# 20260708 workspace home implementation plan

## 状态

status: in_progress

本文记录 Workspace 与 Agent Home 后续能力的实施规划。目标是在既有模块边界上继续推进，不把 workspace 文件正文写入 Context 或普通 ActionResult，不让 AppBuilder 回到业务实现层，并保持 action-internal LLM task、Workspace 业务动作和 Agent Home HOW 挂载之间的职责边界清晰。

## 设计原则

- Workspace 继续作为 `workspace:` 链接的唯一语义归属方，负责路径边界、manifest、资源摘要、正文切片和后续写入能力。
- Agent Home 继续作为 `home:` 链接的唯一语义归属方，负责顶层背景、渐进资源、runtime home 副本、HOW/MEMORY 和每日沉淀。
- Context 只构造 MessageStack，不直接读取 workspace 或 home 文件。
- Workspace 正文只作为 action 内部临时 task prompt input 使用，不进入 WorkingContext、BackgroundContext 或普通 TurnTrace action result。
- 通用 `core.reason` / `core.answer` 可以通过 `reference_links` 读取 workspace 只读参考资料；这属于 read-only reference 能力，不表达 workspace 编辑目标。
- Workspace 编辑类 action 使用 `target_link` 表达实际操作对象，使用 `reference_links` 表达只读参考资料；目标与参考正文都在 Phase3 action 内部局部读取。
- `llm_action` 是 action 层共享的受控 LLM task 能力；Workspace LLM action 复用 `LLMActionTaskRunner`，但 workspace 目标解析、文件读写和 manifest 更新仍属于 Workspace 模块。
- Agent Home 原始目录保持只读，运行期写入落在 runtime home，最终由每日沉淀决定是否合并。
- `how_domain` / `how_action` 是 Agent Home 提供的局部自动 prompt mount：domain HOW 注入 Phase2，并可延续到 Phase3 action-internal LLM task；action HOW 只注入对应 action-internal LLM task，不作为普通可加载资源暴露。

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

### 2. Workspace 写入、patch、delete、rewrite

status: done

已增加 `workspace.write`、`workspace.patch`、`workspace.delete` 与 `workspace.rewrite`。这些 action 的成功结果只返回 link、summary、size、mtime、digest 等摘要，不返回正文；失败优先收敛为局部 ActionResult。

当前语义：

- `workspace.write` 接收 `target_link`、`instruction`、可选 `reference_links`、`overwrite` 和 `expected_digest`，在 action 内部调用 `LLMActionTaskRunner` 生成完整 UTF-8 文本，再写入或覆盖目标资源；
- `workspace.rewrite` 接收 `target_link`、`instruction`、可选 `reference_links` 和 `expected_digest`，在 action 内部加载目标与参考正文，调用 `LLMActionTaskRunner` 生成完整替换文本，再覆盖目标资源；
- `workspace.patch` 采用精确单点文本替换：`old_text` 必须非空且只出现一次，`new_text` 可为空，`expected_digest` 可用于防止陈旧编辑；
- `workspace.delete` 删除目标资源并同步移除 WorkingContext 中的资源摘要。

对应实现位置：

- `tinysoul/workspace/engine.py`：`write_text`、`patch_text`、`delete_resource`、manifest upsert/remove；
- `tinysoul/workspace/actions.py`：`WorkspaceWriteExecutor`、`WorkspacePatchExecutor`、`WorkspaceDeleteExecutor`、`WorkspaceRewriteExecutor`；
- `tinysoul/action/catalog/workspace/actions/`：`write.toml`、`rewrite.toml`、`patch.toml`、`delete.toml`；
- `tinysoul/app/builder.py`：通过 Workspace registrar 注册 workspace executors；
- `tests/workspace/test_workspace_engine.py`：Engine 副作用、action metadata payload、WorkingPatch signal、workspace LLM action prompt 和局部失败测试；
- `tests/action/test_catalog_loader.py`：内置 catalog 动作视图更新。

### 2.5 Workspace PromptBlock 与 llm_action 接入

status: done

已将 Workspace 文本引用接入 Context `PromptBlock` 与 `llm_action`。`LLMActionTaskRunner` 位于 `tinysoul/action/backends/llm_action.py`，集中处理 Phase3 自动 HOW、Context message stack 构造、`LLM_ACTION` task 调用、JSON object 输出和局部失败归一化。`core.reason` 与 `core.answer` 使用 PromptBlock-only `TaskPrompt` 协议：`guide_blocks`、`input_blocks`、`output_blocks` 均可切分为多条消息；它们只接受 `reference_links`，由 `PromptReferenceResolver.resolve_reference(link)` 解析为只读临时 `PromptBlock`。

Workspace 模块提供 `WorkspacePromptReferenceResolver`，支持把 `workspace:` 链接解析为 read-only reference block，也支持 workspace action 内部把 `target_link` 解析为 target block。Phase2/Phase3 边界不传递正文或行范围参数；需要更细粒度读取时由具体 workspace action 在内部决定。`core.reason` / `core.answer` 可通过 workspace `reference_links` 读取只读参考资料；workspace 编辑目标必须通过 Workspace action 的 `target_link` 表达。

对应实现位置：

- `tinysoul/action/backends/llm_action.py`：`LLMActionTaskRunner`、`ActionHow`、`ActionHowProvider`；
- `tinysoul/action/builtins/core/actions.py`：`core.reason`、`core.answer`、PromptBlock-only `TaskPrompt`、`reference_links` 与 registrar；
- `tinysoul/workspace/prompts.py`：`WorkspacePromptReferenceResolver` 与 Workspace PromptBlock 转换；
- `tinysoul/workspace/actions.py`：Workspace LLM action 内部 target/reference prompt 构造；
- `tinysoul/action/catalog/core/actions/reason.toml`：通用推理动作；
- `tinysoul/action/catalog/core/actions/answer.toml`：最终回答动作；
- `tinysoul/app/builder.py`：装配 `LLMActionTaskRunner`，注入 `HomeActionHowProvider`，并向 Action builtins core actions 注入 workspace reference resolver；
- `tests/action/test_llm_action.py`、`tests/workspace/test_workspace_engine.py`、`tests/home/test_home_engine.py`：任务输入切分、引用解析、workspace block、HOW 注入和 runtime copy trap 测试。

### 2.6 Action timeout frame 与 Workspace 写入 guard

status: done

Action timeout result 已具有稳定 frame 协议；Workspace LLM 写入 guard 已下沉到 `WorkspaceEngine.write_text`，write/rewrite 会把构造 prompt 时观察到的 target digest 作为最终写入 guard。

`ActionBatchRunner._timeout_result` 统一提供 `reason`、`cancel_requested`、`executor_started`、`executor_leaked` 和 `late_success` 字段，各 timeout 分支只覆盖实际差异。worker 在 deadline 后才启动与执行中协作取消仍是两种合法时序，但结果载荷结构保持稳定。

`workspace.write` / `workspace.rewrite` 在构造 prompt 时记录 target digest，LLM 返回后把显式 `expected_digest` 或该观察 digest 传给 `WorkspaceEngine.write_text`；Engine 在原子替换前完成 digest 检查，并在 reconciliation 失败时回滚文件。当前 catalog 将全部 Workspace action 配置为 serial，因此 Agent 内部 action 不并发修改 Workspace。外部进程仍可能在 digest 检查和原子替换之间修改文件；这是现有单进程个人项目边界下接受的残余风险，不宣称为跨进程 compare-and-swap。

### 3. Agent Home 检索与 runtime 写入

status: pending

增加 Home 顶层检索和 runtime home 写入能力：

- `home.top.search` 返回候选顶层链接、摘要和短片段；
- `home.resource.write` 与 `home.resource.patch` 写入 runtime home；
- 写入前若 runtime 副本缺失，继续走 `HOME_RUNTIME_COPY_REQUIRED` Trap。

### 4. Memory 与 HOW feedback

status: pending

增加 `home.memory.append` 与 HOW feedback 记录，写入 runtime home 的当日草稿：

- `runtime/home/this_day_memory.md`
- `runtime/home/how/<skill>/SKILL_MEMORY.md`
- `runtime/home/how_domain/<domain>/DOMAIN_MEMORY.md`
- `runtime/home/how_action/<domain>/<action>.memory.md` 或等价的 action HOW 使用记录文件

### 5. Daily settlement

status: pending

在检索、写入和反馈能力稳定后，设计 `AgentHomeSettlementEngine`，基于 TurnSummary、runtime home diff、HOW feedback 和 workspace archive summary 生成可审阅的合并结果。

## 下一阶段实施边界

第 2.6 阶段已完成。后续推进第 3 阶段时，继续保持原始 Agent Home 只读，写入落在 runtime home，副本缺失继续走 `HOME_RUNTIME_COPY_REQUIRED` Trap。

## 验收点

- `WorkspacePromptInput` 以 `WorkspaceTextSlice` 为核心；
- 前缀读取仍可生成临时 task input；
- 行范围读取可以读取长文件局部片段；
- 读取能力仍不暴露为模型侧 `workspace.read` action；
- `workspace.write`、`workspace.patch`、`workspace.delete`、`workspace.rewrite` 成功结果不携带文件正文；
- workspace 变更 action 通过 `context.workspace.sync` 全量同步版本化资源摘要；
- workspace 变更 action 的参数和文件失败收敛为局部 `ActionResult`；
- `core.reason` 支持 PromptBlock-only `TaskPrompt` 与 `reference_links`；
- `core.answer` 支持 PromptBlock-only `TaskPrompt` 与 `reference_links`；
- `core.reason` 和 `core.answer` 可通过 workspace `reference_links` 读取只读参考资料；
- Workspace LLM action 通过 `target_link` 和 `reference_links` 在 action 内部解析 workspace target/reference blocks；
- `how_domain` 可注入 Phase2 与 Phase3 action-internal LLM task；
- `how_action` 可注入对应 Phase3 action-internal LLM task；
- Action timeout result 具有稳定 frame_data 协议；
- Workspace LLM 写入类 action 的 digest guard 下沉到 WorkspaceEngine 写入边界；
- 现有 `workspace.scan` / `workspace.describe` 行为保持；
- `python -m pytest tests -q` 与基于当前环境 Python 的 `scripts/typecheck.ps1` 通过。
