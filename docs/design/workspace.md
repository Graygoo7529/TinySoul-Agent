# Workspace 设计

## 状态

本文描述 Workspace 模块的当前设计。代码已包含独立 Workspace 模块，并完成 `workspace:` 链接解析、workspace 根目录配置、manifest reconciliation、类型化资源访问、WorkspaceSnapshot 全量同步、文件变更 action 和 Runtime bridge 接入。

当前实现覆盖 Workspace 的完整磁盘 reconciliation、显式 business day、Turn 启动语境投影、类型化资源发现、语义描述、扫描诊断、显式有界文本读取、确定性字面量搜索、明确多 Link 分析、内部临时 task prompt 输入、bounded document read、可回滚 bundle mutation、文件变更、可恢复 Trash 和日终归档。`workspace.delete` 是活动日内逻辑删除；Trash 在日切时与 Workspace 分别进入统一时间戳归档，新日 active API 不追踪旧日 Trash。

## 定位

Workspace 模块负责 TinySoul 当日工作区的资源管理，是 `workspace:` 链接的唯一语义归属方。

Workspace 不维护语境状态，不解释外部输入命令，也不读取 Agent Home。`WorkspaceEngine` 不直接执行模型调用；需要 LLM 的 workspace action executor 在 ActionExecutor 语义内构造 `TaskPrompt`，并通过 action 层共享 `LLMActionTaskRunner` 调用模型。Workspace 通过 context 信号同步资源摘要，并通过自身门面处理 workspace 链接解析、路径边界、资源扫描、manifest 更新和文件读写。

## 设计目标

1. `workspace:` 链接有唯一解析和校验入口，避免路径规则散落在 app、action 或具体工具函数中。
2. WorkingContext 只保存 workspace 资源句柄和摘要，不保存文件正文、图片字节或长内容。
3. workspace 文件内容只在具体 action 执行期读取；隐式或无界整文件读取禁止，显式有界 inspection 可以把片段作为当前 Turn 的 foldable ActionResult overlay，action-internal LLM 仍只使用临时 task prompt。
4. `workspace.scan` 保持现有外部行为，但扫描规则、摘要格式和 WorkingContext patch 构造迁入 Workspace 模块。
5. workspace 根目录、忽略规则、manifest 损坏、路径越界和读写失败有清楚的失败语义。
6. App 只负责装配 Workspace 门面，不再直接扫描目录或解释 `workspace:` 链接。

## 边界

Workspace 的核心职责：

- 管理当日 workspace 根目录；
- 解析和规范化 `workspace:` 链接；
- 校验文件路径是否位于 workspace 根目录内；
- 扫描资源并维护 manifest；
- 生成 WorkingContext 可消费的资源摘要；
- 为 action 模块提供 workspace action 的 native handler 或 executor；
- 在需要时读取、写入或删除 workspace 文件；
- 在日级生命周期中归档 workspace。

当前实现已经承担扫描、manifest、链接解析、单资源摘要刷新、扫描跳过诊断、有界读取、PromptBlock 解析、workspace actions、active day 初始化/校验，以及完整 reconcile 后把 workspace/trash 移入跨模块 pending archive；调度仍不属于 Workspace。

Workspace 不负责：

- 把文件正文写入 BackgroundContext、WorkingContext 或 Session canonical trace；
- 决定 Phase1/Phase2 的行动策略；
- 维护 Agent Home 的 WHAT/WHY/HOW 或 Memory 模块的 MEMORY；
- 解析终端、HTTP、WebSocket 等外部输入；
- 直接修改 Context 内存状态。

跨模块协作只通过四类边界完成：workspace link、action 调用、context signal、builder 注入。

## 链接语义

`workspace:` 链接表示工作区内资源句柄，格式为：

```text
workspace:<relative-posix-path>
```

链接规则：

- 路径必须是相对路径；
- 路径分隔符使用 `/`；
- 不允许空路径、绝对路径、盘符、反斜杠、`.` 段或 `..` 段；
- 解析后的真实路径必须位于 workspace 根目录内；
- 符号链接若指向根目录外，应按越界处理；
- 链接只表达资源位置，不承诺资源当前一定存在。

Workspace 模块应提供 `WorkspaceLink` 或等价值对象，在 `__post_init__` 中完成格式校验。模块内部不应使用裸字符串拼接构造路径。

## 资源模型

Workspace manifest 记录资源摘要，而不是资源内容。一个资源记录至少表达：

- `link`：`workspace:` 资源链接；
- `path`：workspace 内相对路径；
- `kind`：`text`、`image`、`document` 或 `binary`；
- `summary`：给 WorkingContext 和模型看的短摘要；
- `size`：字节大小；
- `mtime_ns`：纳秒精度修改时间，用于扫描缓存与提交复核；
- `digest`：内容摘要，用于变更检测和 description 绑定；
- `description` / `described_digest`：可选语义描述及其绑定的内容摘要。
- `retention`：`ephemeral`、`turn`、`day` 或 `persistent`；
- `owner_turn_id`：产生该资源的 Turn，可用于生命周期回收和审计。

投影到 Context 时只提交轻量信息。当前 WorkingContext 已有 `WorkspaceResource(link, summary)`，Workspace 模块可以先投影为这两个字段；后续如需 size、kind、mtime，应先扩展 Context 的资源摘要协议，而不是把完整 manifest 塞进 trace。模型 MessageStack 先渲染 TurnTrace、再渲染 Working，因此该资源投影是交互历史之后的当前状态；Working 消息的 `as_of_trace` 只标记同次组装边界，不改变 Workspace revision 的所有权。

## Manifest

Manifest 是 workspace 的当前资源索引和轻量语义描述层。磁盘是内容事实源；Manifest 只在完整 reconciliation 后原子提交；WorkingContext workspace 段是相同 revision 的 Turn 内投影，并在模型输入中位于可能引用旧 Workspace revision 的 TurnTrace 之后。它用于：

- 避免每次 Phase 都扫描全目录；
- 识别资源新增、修改、删除；
- 为 WorkingContext 提供稳定摘要；
- 支持日终归档和调试。

Manifest 读写属于 Workspace 模块。Manifest 文件应放在 workspace 根目录的框架子目录中，或放在 runtime 元数据目录中；无论采用哪种位置，都不应暴露为普通 `workspace:` 资源，避免模型误把框架索引当作用户资源。

Manifest 损坏属于 Workspace 模块边界失败。启动或装配阶段会主动加载并校验 manifest，损坏时映射为 Workspace 启动失败；运行期损坏同样显式失败，不静默重建。Manifest revision 只在资源事实或有效语义描述发生变化时递增，无变化 reconciliation 保持 revision。

Manifest schema 当前为 v3，新增 ISO business day；读取 v1/v2 时迁移为未标记 legacy state，由 Program 日协调器按 active Session day 认领。磁盘、Manifest 与 WorkingContext 的一致性通过“磁盘事实 -> 完整 reconciliation -> Manifest 原子提交 -> 版本化全量 Context snapshot”建立。任何需要缩减 Workspace 语境的行为必须先改变 active Workspace/Manifest，不能只在 Context 中隐藏仍然 active 的资源。

## Trash 与压力回收

Trash 固定位于 active Workspace root 内部的 `.tinysoul/trash`，由 module-owned ignore 规则排除在资源 Manifest 和 `workspace:` 链接之外。删除采用 prepare-record、原子移动 content、reconciliation、COMMITTED marker 的顺序；启动时发现未提交移动会恢复到原路径。Restore 在目标不存在时反向移动，重新 reconciliation，并恢复原 retention 与 owner 元数据。活动日 Trash 保留记录、原因、day、来源 Turn 和原资源摘要，因而是可恢复删除而不是物理销毁。

语境压力恢复只选择 `ephemeral` 和 `turn` 资源，按 retention、mtime、link 确定性排序；`day`、`persistent` 以及当前 action payload 标记的 target/reference links 不会被自动清理。批量移动中途失败必须反向 restore 已移动项。资源移入 Trash 后必须把新 Manifest 全量同步给 Context；Context 拒绝同步时协调器尝试逐项 restore。Workspace 不自行决定何时触发压力恢复，Loop 只负责跨模块编排，实际资源规则仍归 Workspace 所有。

Trash 是 active Workspace 的内部暂存区，不是第二份资源 Manifest。Trash record 必须基于移动瞬间实际磁盘内容；只有当前 digest 与 Manifest digest 一致时才能继承 description 和 lifecycle 元数据。active miss 只对 `context_pressure` 等框架暂存原因抛出 `workspace.trash_restore_required`。用户显式执行 delete 不触发自动恢复。日切时 Trash 先移到 pending archive 的独立 `trash/`，随后再移动剩余 Workspace root；崩溃发生在两次移动之间时，重复 `archive_day` 根据 source/target 存在性继续。归档后旧 Trash 不再由 list/restore 暴露。

资源分类使用 Workspace 自有的显式扩展名/MIME 映射，稳定分为 `text`、`image`、`document`、`binary`。text 以有界 UTF-8 文本进入 Prompt；image 在 Workspace 单文件限制与 Context 总图片字节预算内以 `ImagePart` 进入 Prompt，并在构造 ImagePart 前校验 PNG/JPEG/GIF/WebP 内容签名，扩展名与内容不符时显式失败；document 必须先由显式转换 action 生成 Markdown 等可读资源；binary 当前只提供元数据。确定性 summary 始终存在，可选 description 由 `workspace.describe` 生成并通过 `described_digest` 绑定当前内容，digest 变化时 reconciliation 自动清除旧 description。

## 目录与生命周期

Workspace 具有当日属性。当前运行结构为：

```text
runtime/
  session/
  workspace/
  home/
archive/
  <timezone-timestamp>/
    transition.json
    session/
    workspace/
    home/
    trash/
```

Workspace 模块只管理 `runtime/workspace` 或配置传入的 workspace root。日切时旧 Workspace 与 active Trash 被移出 runtime，分别进入统一时间戳归档的 `workspace/`、`trash/`；新日 runtime Workspace 从空 Manifest 开始。日终归档由 workspace 门面提供归档能力，但跨模块调度不属于 Workspace 自身。Home/Memory Maintenance 都不通过 active Trash API 追踪或恢复旧日 Trash，Home runtime 也不参与 Workspace 的日切事务。

当前实现默认使用 `runtime/workspace` 作为 workspace root。Manifest 与 Trash 路径固定为 module-owned `.tinysoul/workspace_manifest.json`、`.tinysoul/trash`，不再允许配置到 active root 外；`configs/workspace.toml` 配置 root、通用读取/扫描上限、忽略规则，以及嵌套的确定性搜索和分析预算。Workspace 模块解析配置并拒绝嵌套未知键；Action Catalog 不复制这些业务预算。AppBuilder 只传递 section tree并构建门面。

## Action 接入

Workspace action 继续走 action 模块的既有机制：TOML 描述模型可见工具和框架配置，Workspace 模块提供后端 handler。

当前已实现的 `workspace.scan` 行为：

1. 扫描 workspace 根目录；
2. 应用忽略规则和数量限制；
3. 更新 manifest；
4. 发出带 Manifest revision 的 `context.workspace.sync` 全量快照（空快照也发出）；
5. 返回 compact JSON payload，包含资源数量、链接摘要、跳过数量、跳过原因计数和是否达到扫描上限。

当前 inspection action 具有三种不同职责：

- `workspace.read` 接受一个明确 UTF-8 text Link、1-based 闭区间、可选 cursor/字符上限/expected digest。Engine 以固定字符块扫描指定行范围，调用方上限只能收紧 Workspace 的 `max_read_chars`；结果包含请求和实际位置、正文、截断原因、续读 cursor/position 与 EOF 事实。显式范围偶然覆盖很短的完整文件是允许的，禁止的是隐式或无界整文件读取。
- `workspace.search_text` 接受单行字面量 query 和显式 file/directory/workspace scope，不接受 regex。目录 prefix 是选择器而不是新的 Link 类型；候选按 Link、命中按行号稳定排序，重叠上下文合并为片段。scan budget 决定 `coverage.complete`，result budget 决定 fragments、额外 line hints 与 `truncated`，二者不能混为一个标记；不区分大小写匹配使用 Unicode casefold，但长行裁剪和列位置始终映射回原文字符坐标，片段必须保留实际来源 match span。
- `workspace.analyze` 只接受 Phase2 已选择的非空、去重 text `reference_links` 和有界 intent，不接受目录或 Workspace scope，也不在 Phase3 重新选择资源。每个 reference 必须完整进入一次 action-internal LLM task；任一单文件、Link 数量或合计 source 超出 analysis budget 时，不调用 LLM，而是返回带 Link/digest/size 诊断的局部失败。成功输出只含有界 answer、经过 executor 验证的 source ids 映射和 coverage，不携带原始正文，不修改 Workspace 或发布 snapshot。

`workspace.read` 与 `workspace.search_text` 的成功结果使用 Catalog 声明的 foldable trace mode：正文只存在于当前 Turn visible overlay；canonical trace 删除正文但保留 Link、digest、范围/hints 和 coverage，Context pressure 可移除 overlay，Session 无论是否发生压缩都只持久化 compact locator。Workspace 资源可变且按日归档，compact locator 不承诺跨日恢复原片段。`workspace.analyze` 返回的是有界整理结论，使用 standard trace；原始 references 只存在于 action-internal prompt。

当前已实现的 `workspace.describe` 行为：

1. 解析并校验一个可直接读取的 text/image `target_link`；
2. 在 action 内部把资源局部挂载为 TextPart/ImagePart，并调用 LLM 生成简短 description；
3. 提交前重新执行 reconciliation 和 digest 校验，把 description 绑定当前 digest；
4. 原子更新 Manifest revision，并发出完全一致的 `context.workspace.sync`；
5. 返回 compact 元数据，不返回文件正文或图片字节。

reconciliation 达到文件数量上限或出现非内部资源读取失败时状态为 incomplete：保留旧 Manifest，不发布全量 Context snapshot。变更 action 在这种情况下回滚磁盘修改；显式 `workspace.scan` 返回局部失败和诊断。

普通正文临时输入由 `WorkspaceEngine.prepare_task_input` 提供。write/rewrite 使用更强的 `prepare_edit_sources`：Engine 在一次锁内读取 target 与全部显式 references，生成正文块及 `WorkspaceEditReadSet`，其中每个 `WorkspaceResourceVersion` 明确记录 Link、present/absent state、digest、size 和 kind。target 不得与 reference 重复，references 必须唯一；prompt builder 只消费这次实际读取的 `WorkspaceEditSources`，不再二次 inspect/read 或另行构造 provenance。`WorkspaceEngine.read_text_slice` 继续服务模块内部前缀/行读取；公开 inspection 使用具有 digest、闭区间和 cursor 结果语义的 `read_text_range`。`WorkspacePromptReferenceResolver` 负责普通 `workspace:` reference 到 Context `PromptBlock` 的转换；`WorkspaceAnalysisPromptBuilder` 组合 intent、完整 references 和 grounded JSON 输出协议。Phase2/Phase3 边界只传递 Link、明确 inspection scope/range 和 intent，不传递正文。除 foldable read/search 的有界 visible overlay 外，调用方不得把正文作为普通 ActionResult payload 或 WorkingContext 资源摘要保存。

本地 Resource conversion 使用两个更窄的 Workspace 门面：`read_document` 只完整读取已登记的 document resource，并同时校验配置字节上限、实际大小和 digest；`write_bundle` 在同一 Engine 锁内预检全部 write/delete Link、覆盖和 digest 条件，再写入文件并只做一次完整 reconciliation。bundle 中任一写入、删除、reconciliation 或最终 Manifest 保存失败时恢复操作前字节与 Manifest；成功返回的所有 record 属于同一个 revision。该语义仍服从单进程单写者边界，不宣称断电事务或跨进程 CAS。

当前已实现的变更类 action：

- `workspace.write`：接收 `target_link`、`instruction` 和可选 `reference_links`/`overwrite`/`expected_digest`，在 action 内部生成完整文本并写入或覆盖资源；
- `workspace.patch`：基于 `old_text` 到 `new_text` 的精确单点替换修改资源，可用 `expected_digest` 防止陈旧编辑；
- `workspace.delete`：把资源移入可恢复 Trash；
- `workspace.restore`：按 Trash ref 恢复原资源及生命周期元数据；
- `workspace.trash.list`：列出 Trash ref、原链接、摘要、原因和来源 Turn，不返回文件正文；
- `workspace.rewrite`：接收 `target_link`、`instruction` 和可选 `reference_links`，在 action 内部加载目标与参考正文，调用 LLM 生成完整替换文本并写回目标资源；

这些 action 使用 `target_link` 参数表达实际变更对象。小幅确定性修改由 `workspace.patch` 执行；完整文本生成由 write/rewrite 的 action-internal LLM task 完成。`workspace.write`、`workspace.rewrite` 与 `workspace.analyze` 都显式使用 90 秒 action deadline，使 prompt 构造、模型请求、模型链内有界重试/切换、结果解释和 Workspace 提交共享同一个取消边界；普通 Workspace action 继续继承 domain 的 30 秒默认值。该 action 级 deadline 只扩大嵌套 LLM 工作的正常运行窗口，不增加 LLM 重试次数，也不改变失败分层：deadline 到期仍收敛为局部 ActionResult，且 cancellation contract 阻止 action-internal LLM 在超时后继续重试或提交。

`workspace.write/rewrite` 的 action-internal task 使用纯文本回答作为完整 UTF-8 工件，不再要求 `{"text": ...}` JSON wrapper。Catalog 为两者声明动作级 `max_output_tokens=16384` generation budget 与 `max_output_chars=50000` artifact acceptance bound；provider 明确报告输出上限、其它未完成状态，或完整文本超过 artifact bound 时，executor 返回带 scope/disposition 的局部失败且不写入文件、不发布 Workspace snapshot。LLM 在锁外执行，完成后 `commit_edit_text` 在一次锁内验证完整 read set：target 必须仍是相同 digest 或仍不存在，每个 reference 必须仍 present 且 digest 相同；任一变化返回稳定 `source_changed` failure，不提交生成文本。全部通过后才写入、完整 reconcile 并发布一次同 revision snapshot。成功 ActionResult 只返回资源版本/provenance 元数据，不返回正文。

每个成功 action 最终执行完整 reconciliation，以原子 Manifest 作为磁盘投影，再发布同 revision、同资源全集的 `context.workspace.sync`；成功结果只返回元数据，不返回正文。执行失败优先收敛为 ActionResult，且不发布同步信号；RuntimeException 由 Action runner 原样传播到 Module/Trap。

## Context 接入

WorkspaceEngine 不依赖 Context 类型。`workspace/projection.py` 是 Workspace 拥有的 Context 集成边界，统一把 Manifest records 转成 WorkspaceSnapshot，并供 action executor 与 Turn preparation 共用。Turn 开始时先完整 reconcile 并提交 snapshot，使首个 Phase1 已能看到资源摘要；Context 以 revision 检查顺序和冲突后整体替换 Workspace 段。

`WorkspaceReconciler` 专门负责磁盘发现、旧 digest/description/lifecycle 复用、完整性判定、候选状态复核和 Manifest 原子提交。`WorkspaceEngine` 负责资源操作、Trash/restore 与变更回滚，并以进程内可重入锁串行化同一 Engine 实例上的 inspect/read/task-input、write、patch、trash、restore、description 和 reconciliation。

`WorkspaceEngine` 同时是 committed Manifest transition 的 Observation owner。initialize、公开 reconcile、write、bundle、patch、description、trash 和 restore 只在最终成功提交后各发布一次 normal `workspace.changed`；内部 reconciliation、回滚和中间 Manifest 不发布。事件包含 previous/current revision，以及 created/updated/removed/all affected links，可同时覆盖 Endpoint/UI mutation、Agent Workspace action、Capability bundle 和外部磁盘变更。发布经注入的 `ObservationEmitter` 进入 App `ObservationRouter`，sink 失败不能改变已经提交的 Workspace 结果。

Workspace 的明确一致性等级是“单进程单写者、Engine 实例内线性化”。没有外部文件写入者时，同一 Engine 的公开读写按锁获取顺序观察完整操作；数据文件原子替换和 Manifest 原子替换各自不会暴露半写文件。二者不是一个跨文件系统事务：内容提交后 Manifest 提交失败时，Engine 尝试用操作前字节回滚；Trash/restore 使用 prepare、原子移动、reconcile、commit marker，并由启动 reconciliation 修复未完成移动。

Workspace 不提供跨进程锁、文件系统快照或外部 writer 的强一致性。`expected_digest` 是基于操作前实际字节计算的乐观前置条件，而不是锁住外部写入者的 CAS；write/patch/description 会读取真实字节校验，因而即使外部修改刻意保持 size/mtime，也不会仅依赖缓存摘要接受旧 expected digest，但外部进程仍可能在校验后再次写入。普通 read 也不保证在外部并发写入下正文与返回元数据来自同一快照。普通 Reconciler scan 使用 size/mtime 复用既有 digest，并在提交前复核候选状态；Workspace-owned single/bundle mutation 明确把已写 Link 交给 Reconciler 强制重算 digest，因此即使原子替换后的 size 与 `mtime_ns` 恰好都未变化，成功结果和 Manifest 仍绑定新字节。外部写入若同时伪造相同 size/mtime，可能到后续强制读取或元数据变化时才被发现。因此支持的强语义要求 active Workspace 只有 TinySoul 一个 writer；无法约束外部写入时，一致性是 best-effort 并应由调用环境额外协调。

桌面 Endpoint 也复用同一 Engine 实例，不把 active Workspace 暴露给前端文件 API。UI mutation 额外提交 Manifest `expected_revision`，Engine 在同一可重入锁内先校验 revision，再执行原有 resource digest guard 和 mutation；trash 同样要求 digest，restore 要求 revision。Endpoint 在 Daily active-day lease 内调用这些门面，避免请求落入归档与新日初始化之间。Endpoint 不重复发布 Workspace event，只在自身 mutation 成功后通过 Gateway 协调活跃 Turn 的 Context snapshot。

WorkingContext 与 BackgroundContext 不保存文件正文。Action 结果也不应默认把正文渲染为 tool result message；需要给模型继续处理的正文，优先在 action 内部进行分析、转化为临时 task prompt，或通过显式有界 read/search 返回。read/search 完整 payload 只作为当前 Turn visible overlay，compact payload 才是 canonical trace 和 Session 输入；analyze 的 references 只进入内部 prompt，ActionResult 只保存结论与来源。

## Infra 依赖

Workspace 可以复用 infra 的基础文件能力，但 infra 不应了解 `workspace:` 业务语义。适合放入 infra 的能力包括：

- 安全相对路径解析；
- 根目录边界检查；
- 文本和二进制读写；
- JSON/TOML 稳定序列化；
- 原子写入；
- 文件摘要计算。

忽略规则、manifest 字段、resource summary 和 `workspace:` 链接仍属于 Workspace。

## 失败与 Runtime 桥接

Workspace 失败分三层：

1. 局部 action result：链接不存在、文件过大、编码失败、写入失败、参数不符合 workspace 规则；
2. 模块边界异常：workspace root 不可用、manifest 无法解释、路径沙箱不变量破坏、模块调用契约错误；
3. Runtime 语义异常：启动阶段配置失败映射为 `runtime.startup_failed`，运行期不可继续失败默认映射为 `runtime.turn_end`。

Workspace 应定义自己的 `WorkspaceFailureKind`，并通过 `tinysoul/runtime/bridge/` 下的专门 bridge 转换为 Runtime 通用原因。Runtime payload 只携带模块名、失败类型、资源链接、路径摘要和错误类型，不携带文件内容或 traceback。Workspace 配置错误应由 workspace bridge 映射为 `runtime.startup_failed`，而不是落入 infra 或 app 的兜底失败。

## 组装入口

当前目录：

```text
tinysoul/workspace/
  __init__.py
  engine.py
  config.py
  links.py
  manifest.py
  reconcile.py
  resources.py
  projection.py
  actions.py
  prompts.py
  search.py
  text.py
  errors.py
  failures.py
```

`WorkspaceEngine` 是资源管理门面，除资源操作外提供 active day 初始化/校验和 `archive_day(workspace_target, trash_target)`。`WorkspaceReconciler` 维护磁盘发现与 Manifest 提交事务；`projection.py` 只接受与 Turn 相同 business day 的 Manifest；`WorkspaceEngineBuilder` 负责接收已解析设置、校验 module-owned 路径、主动验证 manifest 并装配 store。Loop coordinator 只调用这些门面，不理解 Workspace 内部资源路径。

AppBuilder 的目标职责是：

1. 构建 `WorkspaceEngine`；
2. 调用 Workspace 提供的 registrar 把 workspace handler/executor 注册到 `ActionEngineBuilder`；
3. 不直接调用 `os.walk`，不构造 `WorkspaceResource`，不解释 `workspace:`。

## 测试与验收

验收点：

- `workspace.scan`、`workspace.read`、`workspace.search_text`、`workspace.analyze`、`workspace.describe`、`workspace.write`、`workspace.patch`、`workspace.delete` 和 `workspace.rewrite` 行为测试位于 `tests/workspace/`；
- AppBuilder 不包含 workspace 扫描闭包；
- `workspace:` 链接解析和越界防护有单元测试；
- manifest 完整 reconciliation、incomplete 不提交、无变化 revision 稳定和 description digest 失效有单元测试；
- Turn preparation 在首个 Phase 前投影完整 Manifest；
- text/image/document/binary 分类、ImagePart 内容签名校验、图片预算和 document conversion_required 有单元测试；
- Engine 内部有界文本前缀读取、公开 range/cursor 读取、确定性 file/directory/workspace 字面量搜索、`WorkspacePromptInput` 和 workspace link 到 PromptBlock 的局部解析都有边界测试；read/search 正文只进入 foldable visible overlay，TurnSummary/Session 只保存 compact locator；
- `workspace.analyze` 覆盖完整 reference budget、超限不调用 LLM、虚构 source id 拒绝、standard result 不携带 reference 正文和无 Workspace mutation；
- Workspace 配置错误经 workspace bridge 映射，并保留 `module = workspace`；
- write/patch/delete/rewrite action 使用 `target_link` 表达变更目标；write/rewrite 在 action 内部调用 LLM 生成完整文本，patch 确定性应用 Phase2 生成的小幅替换参数；执行失败应收敛为 `ActionResult`，成功结果不携带文件正文；
- workspace 配置错误和 manifest 不变量错误经 Runtime bridge 映射；
- Context 测试继续证明 WorkingContext 只保存链接和摘要。

Document conversion action 已由 Resource capability 提供；日终 workspace/trash 归档与 partial resume 已有故障测试。
