# Workspace 渐进披露与动作收敛后端执行计划

- 日期：2026-11-27
- 状态：`ready`（维护者已确认全仓 Context 段预算统一为 tokens、不保留旧版兼容、先实施 Workspace 后端；已完成全链路代码审计修订）
- 核对基线：`712abf02`
- 关联计划：
  - [Workspace 契约同步与界面精简前端执行计划](20261127%20Workspace契约同步与界面精简前端执行计划.md)
  - [Context 统一预算与 Session 多级压缩后端执行计划](20261127%20Context统一预算与Session多级压缩后端执行计划.md)
- 依据：
  - [AGENTS.md](../../AGENTS.md)
  - [Workspace 设计](../design/workspace.md)
  - [Context 设计](../design/context.md)
  - [Action 设计](../design/action.md)
  - [引用设计](../design/references.md)
  - [Endpoint Workspace 协议](../endpoint/workspace.md)

---

## 0. 确认结论与核心设计决策

本计划基于与维护者对齐的设计结论制定，消除 Workspace 早期设计与演进叠加留下的无界上下文投影、冗余动作、失真人工元数据及脆弱行号编辑语义，使 Workspace 回归“当日文件事实 + 纯派生索引 + 有界渐进披露 + 正交读写动作”的清晰边界。

| 已确认决策 | 目标语义与实施约束 |
| --- | --- |
| `WorkspaceSegment` 段内 Token 水位折叠 | 全仓常驻 Context 段预算统一采用 `tokens`（在 P1 先落地纯 `infra` 层的 `tinysoul/infra/tokens.py` 确定性估算器）；段内每次 `prepare` 按 `max_context_tokens = 3000`、`default_expand_depth = 3` 做无状态确定性树折叠（低优派生目录默认折叠，超水位子目录折叠为带子项计数的目录摘要并通过 `workspace.inspect` 按需展开，不丢弃资源入口）；不接入全局 `SegmentCapability.RECLAIM` 动态改预算，保持 100% 无状态纯投影并避免 `State` 顺位先于 `TurnTrace` 被削减 |
| 统一“一切皆文档”目录披露与磁盘上限解耦 | 目录摘要展示直接/子树资源统计而非无意义的 `0 bytes`；`workspace.inspect` 统一承担文件正文、子目录及根 `workspace:` 的有界分页披露（结果经 `TurnTrace` 单轮保护后可折叠，不反向把 `WorkspaceSegment` 变成有状态展开表）；磁盘扫描上限 `max_files` 放宽至 `5000` 并补充常见派生忽略目录 |
| 彻底移除 `tag` 与 `description` | 从 `WorkspaceManifest`（升级为 `schema_version = 5`）、`WorkspaceResourceRecord`、`WORKSPACE_SEARCH_FILTERS`、Action Catalog、Endpoint 路由与 Schema 中完整移除 `tags` 与 `description`；`manifest` 回归 100% 确定性磁盘派生索引，消除覆写后描述腐烂与提示词虚假承诺 |
| 读写动作正交收敛（19 → 11） | 移除 `list`、`read`、`insert`、`tag`、`describe`、`analyze`、`trash_list`；`write` 更名为 `workspace.create`（默认新建，保留 `overwrite: bool = false`，收紧内联上限 `max_create_chars = 12288`） |
| `workspace.edit` 锚点插入与清晰报错 | 单项支持 `position: "replace" \| "before" \| "after" = "replace"`，允许以简短语义锚点插入新内容而无需重复抄写 `old_text`；支持行尾空白归一化匹配，并明确区分“0 处匹配”与“匹配多处（附行号）”局部反馈 |
| `workspace.compose` 融入“Phase2 定位 + Phase3 生成” | 复用 `disclosure.fragment_range` 原生支持的 `#heading` 与 `#Lstart-Lend` 片段语法；Phase2 通过 `target_ref`（整文件或带 `#fragment`）与 `mode: "replace" \| "before" \| "after"` 完成确定性定位，Executor 提取切片与只读衔接上下文，Phase3 内嵌 LLM 以 `AnswerFormat.TEXT` 纯文本直出新内容并精确拼回 |
| Trash 精简与按原路径恢复闭环 | 移除 `workspace.trash_list` 及残留未消费接口；`workspace.restore` 支持传入原路径 `ref`（恢复当日 Trash 中该路径最近一次删除项）或精确 `trash_ref` |

进度检查项：

- [ ] P1：`infra/tokens.py` 纯文本估算基座、配置模型、配置目录描述符与纯派生 Manifest Schema v5 重构
- [ ] P2：`WorkspaceSegment` 无状态渐进式树折叠投影与根 `workspace:` 披露支持
- [ ] P3：`edit` 锚点语义、`create`、`restore` 原路径恢复与 `compose` 片段定位生成实现
- [ ] P4：Action Catalog、模型用途绑定、固定提示词、Home Skills 与 Endpoint 契约同步
- [ ] P5：设计/协议文档同步、测试迁移补齐及完整本地门禁（Full + `ty check`）验收

---

## 1. 目标与改动预览

| 切面 | 当前状态 | 改进后目标语义 |
| --- | --- | --- |
| `WorkspaceSegment` 上下文投影 | 平铺输出 `manifest.resources` 全量条目，无预算约束；目录显示 `Directory, 0 bytes` | 每次 `prepare` 按 `max_context_tokens = 3000` 与 `default_expand_depth = 3` 输出无状态紧凑树视图；派生目录（`jobs`、`mcp`、`connections`、`*.assets`）默认折叠；目录显示真实子项统计，不接入全局 `RECLAIM` 动态改预算 |
| 磁盘发现上限与索引协议 | `max_files = 100`，`WorkspaceManifest` schema v4 含手工 `description` 与 `tags`，`move`/`restore` 需预写中间元数据防丢失 | `max_files = 5000`，`ignore_dirs` 增补 `.venv`、`node_modules`；Manifest 升至 schema v5，仅保留 8 个确定性磁盘字段；移除中间元数据预写与 `tags` 搜索过滤字段 |
| 发现与读取动作 | 同时存在 `search`、`inspect`、`list`、`read`、`trash_list` 5 个枚举/读取动作 | 仅保留 `workspace.search` 与 `workspace.inspect`（支持文本范围/章节、子目录及根 `workspace:` 分页），与 Home/Memory/Context 完全统一 |
| 创建、生成与局部修改动作 | `write`（32k 字面量）与 `compose` 边界重叠；`insert(after_line)` 易受行号漂移影响；`edit` 报错笼统且插入需重复原文 | `workspace.create` 负责确定性短文本新建/显式覆盖（`12288` 字符）；`workspace.edit` 支持 `position` 锚点替换/前后插入与精确行号诊断；`workspace.append` 负责尾部追加；`workspace.compose` 支持整文件撰写及 `#fragment` 片段改写/插入 |
| 内嵌 LLM 分析与元数据动作 | `analyze`、`describe`、`tag` 占用工具面与模型用途绑定，存在全量 Context 重复发送、JSON 输出脆弱及生命周期语义失真 | 移除 `workspace.analyze`、`workspace.describe`、`workspace.tag` 及其 `ModelUseDescriptor`、Executor、Prompt 与配置节 |
| Gateway Endpoint 契约 | 暴露 `PUT /v2/workspace/tags`、`POST /v2/workspace/insert`，`restore` 仅接受 `trash_ref`，记录含 `tags`/`description` | 移除 `/tags` 与 `/insert` 路由；`/edit` 支持可选 `position`；`/restore` 支持 `trash_ref` 或原 `ref`；Manifest/Record 响应同步为无 `tags`/`description` 的 schema v5 |

边界声明：

- 本计划严格限定在后端代码、配置资产、测试与文档范围（`tinysoul/`、`tests/`、`docs/`、`AGENTS.md`），**不修改 `visualization/` 目录下的任何文件**。
- 不引入文件内容哈希 CAS、read-set 或跨进程文件锁；不改变日切 Archive 物理目录迁移协议；不改变 `capabilities/resource` 的两个文档转换动作语义。
- 不为已废弃的 `schema_version = 4`、`tags`、`description`、`workspace.write`/`read`/`list`/`insert`/`analyze`/`describe`/`trash_list` 保留兼容别名或双轨分支。

---

## 2. 已核实的现状与问题依据

### 2.1 `WorkspaceSegment` 无界渲染与段内固定水位取舍核实

1. `tinysoul/plugins/workspace/projection.py:106-174` 中，`WorkspaceSegment` 注册为 `SegmentDescriptor("workspace", "workspace", SegmentSlot.WORKING, 20)`（默认 `SegmentShape.STATE`，`capabilities=frozenset()`），每次 `render()` 将 `manifest.resources` 全量拼接输出，无任何字符或深度预算。
2. 核查段内水位折叠与全局压力回收（`TurnSegments.reclaim` `tinysoul/kernel/context/segments/collection.py:238-257`）的关系：
   - 在每次 `prepare()` 已按 `max_context_tokens = 3000`（约 9k～10.5k 字符，不足默认 262k 窗口的 1.2%）完成树折叠后，`WorkspaceSegment` 天然有界，不会成为全局窗口压力源；
   - `TurnSegments.reclaim` 的回收顺序固定为 `STATE → HEAP → STACK → MAP`。若让 `WorkspaceSegment`（`STATE`）接入 `RECLAIM` 动态缩减预算，在长对话因 `TurnTrace`（`STACK`）膨胀触发窗口压力时，系统会先削减当前正在使用的工作区目录，而非先折叠过期的 `TurnTrace`；
   - 因此明确采用**仅在 `prepare()` 执行段内固定水位树折叠、不声明 `SegmentCapability.RECLAIM`、不维护可变本轮预算**的纯无状态方案。
3. 磁盘扫描耦合问题：`tinysoul/plugins/workspace/config.py:21` 默认 `max_files = 100`；一旦工作区目录与文件总数达到 100（如 PDF 拆图或多次脚本产物），`reconcile()` 返回 `limit_reached=True, complete=False`，导致 `WorkspaceTurnPreparationHandler.prepare`（`projection.py:373-385`）直接抛出 `WorkspaceFailureKind.IO_FAILED` 阻断新 Turn 启动。

### 2.2 根引用 `workspace:` 与引用解析边界核实

1. `tinysoul/plugins/workspace/refs.py:43-45` 强制要求 `WorkspaceRef.relative_path` 非空，这对保护 `create`、`edit`、`delete`、`move` 不误操作工作区根目录是必要的安全不变量。
2. 但只读披露与引用解析入口尚未放行 `"workspace:"`：
   - `WorkspaceEngine.inspect`（`engine.py:314-380`）内部调用 `self.stat(resource)` -> `self.path_for(resource)` -> `WorkspaceRef.parse`，传入 `"workspace:"` 会报契约错误；
   - `WorkspaceExecutor` 执行 `workspace.inspect` 后会将 `origin_refs=(ref,)` 写入 `ActionTraceProjection`（`operations.py:103`），随后 `ContextEngine._current_search_facts` 与 `Session` 反链检查会经 `ReferenceResolver.resolve` 调用 `WorkspaceEngine.canonical_reference`（`engine.py:640-650`）。若不让 `canonical_reference` 同步识别无片段的 `"workspace:"`，根 `inspect` 将在反链检索时触发 `ReferenceError`。

### 2.3 元数据、搜索过滤与动作冗余核实

1. **手工元数据失真与耦合**：
   - `description` 初始恒为 `""`，仅由 `workspace.describe` 写入，但在 `reconcile.py:180` 按路径无条件继承，文件经覆写或编辑后描述立即陈旧；
   - `tag.toml` 与 `DOMAIN.md:7` 声称 `pinned` 可跨日保留，与 `AGENTS.md:72` 实际生命周期矛盾；
   - `tinysoul/plugins/workspace/engine.py:90-97, 740-745, 770` 中，`WORKSPACE_SEARCH_FILTERS` 注册了 `AttributeField("tags", AttributeKind.TEXT_SET)`，且非文本资源搜索摘要读取了 `record.description`。清理 `tags` 与 `description` 时必须同步收敛此处。
2. **编辑与恢复痛点**：
   - `mutations.py:183-189` 中 `edit_text` 对“未找到”和“匹配多处”抛出同一无 `feedback` 的 `WorkspaceContractError`，模型只收到笼统的 `INVALID_WORKSPACE_REQUEST`；
   - `operations.py:313-427` 中 `workspace.compose` 仅支持整文件读取与覆写，缺少复用 `fragment_range`（`tinysoul/kernel/retrieval/disclosure.py:616-654`）做章节/行区间局部生成的能力；
   - `mutations.py:269-289` 中 `restore_resource` 仅接受 `trash:workspace/<32hex>`，移除 `trash_list` 后需支持按原 `workspace:<path>` 定位最近删除项。
3. **残留方法、归档视图与配置引用**：
   - `WorkspaceArchiveView`（`engine.py:120-168, 548`）与 `ArchivedWorkspaceSegment`（`projection.py:208, 242`）仍直接引用 `max_read_chars` 与 `item.context_summary`，`WorkspaceReader.read_text` / `prepare_task_input`（`reader.py:95, 268`）默认回退 `max_read_chars`，移除 `context_summary` 与重命名 `max_inspect_chars` 时必须同步收敛；
   - `WorkspaceChangeOperation`（`events.py:35-49`、`engine.py:946-952`）中，`WRITE` 仍服务于底层 `write_text`（供 `workspace.create`、`workspace.compose` 与 Endpoint `PUT /v2/workspace/resource` 共用），应保留 `WRITE` 并仅移除无消费者的 `DESCRIBE`、`INSERT`、`TAG`；
   - `WorkspacePlugin.model_uses`（`plugin.py:130-136`）、`assets/{standard,development}/configs/action/routing.toml:16-25`、`infra/config/catalog/context.toml:315-406`、`prompts/README.md:19` 仍持有 `describe`、`analyze`、`max_read_chars` 及 `workspace.analysis.*` 定义，需整体对齐。

---

## 3. 详细改进设计

### 3.1 Token 估算基座前置与配置模型重构（`infra/tokens.py` & `WorkspaceSettings`）

1. **前置落地纯基础设施 `tinysoul/infra/tokens.py`（与后续 Context 计划共用）**：
   - 严格遵守 `tests/test_architecture.py:145`（`infra` 仅允许依赖 `infra`，严禁导入 `tinysoul.llm`）：提供无外部重依赖的确定性纯函数 `estimate_text_tokens(text: str) -> int`（ASCII 按 `3.5 chars/token`、非 ASCII 按 `1.0 char/token` 上取整）与 `estimate_json_tokens(value: JsonValue) -> int`；
   - 注：Workspace 后端阶段仅由 `WorkspaceSegment` 消费 `estimate_text_tokens`，暂不改动 `llm/execution/context_window.py`（留待 Context 后端 C1 切换），确保本计划独立实施与测试验证边界完全自洽。
2. **`WorkspaceSettings` 常量与字段调整（`tinysoul/plugins/workspace/config.py`）**：
   - `DEFAULT_MAX_FILES = 5000`（原 `100`）；
   - `DEFAULT_IGNORE_DIRS` 在现有列表基础上增补 `".venv"`、`"node_modules"`，避免在工作区内执行环境/包管理命令时扫描数万第三方依赖文件；
   - `DEFAULT_MAX_CONTEXT_TOKENS = 3000`（`WorkspaceSegment` 默认常驻 Token 预算，要求 `>= 128`，全仓统一使用 `tokens` 表述段预算）；
   - `DEFAULT_EXPAND_DEPTH = 3`（默认树展开深度，要求 `>= 1`；1 表示仅根目录直接子项，3 表示默认展开至 `dir/subdir/file`）；
   - `DEFAULT_MAX_INSPECT_CHARS = 8192`（单页读取切片边界仍用字符，替换原 `max_read_chars`，对齐 `session.max_inspect_chars`、`memory.inspect.max_page_chars`、`context.max_trace_inspect_chars`，要求 `>= MIN_CONTINUATION_PAGE_CHARS`）；
   - `DEFAULT_MAX_CREATE_CHARS = 12288`（约束 `workspace.create` 内联字面量文本长度，要求 `0 < max_create_chars <= max_write_chars`）；
   - `DEFAULT_MAX_WRITE_CHARS = 65536`（原 `32768`，约束单文件完整可编辑文本、`compose` 最终落盘文本及 Endpoint 全文写入上限）。
3. **`WorkspaceComposeSettings` 替代 `WorkspaceAnalysisSettings`**：
   - 移除 `workspace.analysis` 配置子树与 `WorkspaceAnalysisSettings`；
   - 新增 `WorkspaceComposeSettings`（对应配置节 `[workspace.compose]`）：
     - `max_instruction_chars: int = 4096`
     - `max_reference_refs: int = 8`
     - `max_reference_chars: int = 32768`（单个参考文本资源读取上限）
4. **同步配置文件与配置元数据目录**：
   - 更新 `tinysoul/assets/standard/configs/workspace.toml` 与 `tinysoul/assets/development/configs/workspace.toml`；
   - 更新 `tinysoul/infra/config/catalog/context.toml` 中 `surface = "workspace"` 的字段定义：移除 `workspace.max_read_chars` 与 `workspace.analysis.*`，新增 `workspace.max_context_tokens`、`workspace.default_expand_depth`、`workspace.max_inspect_chars`、`workspace.max_create_chars` 及 `workspace.compose.*`（组名 `workspace.compose`）。

### 3.2 纯派生 Manifest Schema v5 与存储简化

1. **`WorkspaceResourceRecord` 与 `WorkspaceManifest`（`storage/manifest.py`）**：
   - 删除 `WorkspaceTag` 枚举；
   - `WorkspaceResourceRecord` 精简为 8 个纯确定性磁盘字段：`ref`、`relative_path`、`kind`、`media_type`、`suffix`、`summary`、`size`、`mtime_ns`；删除 `description`、`tags` 字段及 `context_summary` 属性；
   - `WorkspaceManifest.schema_version` 升级为 `5`（严格校验 `schema_version == 5` 与 8 字段集合，不保留 v4 兼容分支）。
2. **磁盘扫描与目录表示（`storage/reconcile.py`）**：
   - `inspect_record(self, path: Path)` 移除 `previous` 参数；
   - 对目录资源统一生成确定性记录：`size = 0`、`summary = "Directory"`（消除不同操作系统目录 `st_size` 差异与 `Directory, 0 bytes` 噪声）；对文件资源保持 `f"{label}, {stat.st_size} bytes"`。
3. **变更与移动简化（`storage/mutations.py`、`storage/trash.py`）**：
   - 删除 `tag()`、`set_description()`、`_metadata()`、`insert_text()`；
   - 简化 `_relocate()`：移除移动前向 `manifest` 预写目标元数据的中间落盘步骤，直接创建父目录、`os.replace(source, target)` 并调用 `self._index_after(committed)` 重建确定性索引；
   - `WorkspaceTrashItem` 保留 `trash_id`、`original`、`descendants`、`trashed_at`、`day` 五元组结构（供前端展示回收目录内子项数量），其中 `original` 与 `descendants` 自动使用精简后的 8 字段 `WorkspaceResourceRecord`。
4. **搜索过滤同步（`engine.py`）**：
   - `WORKSPACE_SEARCH_FILTERS` 收敛为 `file_type`、`day`、`kind` 三项（移除 `tags`）；
   - `retrieval_corpus` 中非文本资源的元数据候选文本直接使用 `record.relative_path`（原为 `record.description or record.relative_path`）。

### 3.3 `WorkspaceSegment` 无状态渐进式树折叠投影

修改 `tinysoul/plugins/workspace/projection.py` 与 `tinysoul/prompts/plugins/workspace.py`：

1. **目录树构建与派生目录分级**：
   - 从 `WorkspaceManifest.resources` 构建内存树，统计每个目录的直接子目录数、直接文件数及子树总文件数、子树最大 `mtime_ns`；
   - 定义低优派生目录判定规则：顶层 `workspace:jobs`、`workspace:mcp`、`workspace:connections`，以及任意层级名称以 `.assets` 结尾的目录。此类目录在 `WorkspaceSegment` 中**默认保持折叠**，仅展示一行目录聚合摘要，不自动展开内部明细。
2. **有界广度优先（BFS）树折叠算法（纯函数无状态投影）**：
   - 输入：`manifest`、`max_tokens`（`settings.max_context_tokens = 3000`）、`max_depth`（`settings.default_expand_depth = 3`），使用 `infra.tokens.estimate_text_tokens` 计量渲染文本；
   - 第 1 步（根层基线）：收集深度为 1 的所有条目（普通目录与文件优先于低优派生目录，同类按名称稳定排序；若仅根层条目渲染已超 `max_tokens`，按子树/文件 `mtime_ns` 降序保留最近活跃项，并在末尾追加根折叠提示行 `... (+N more root items folded; use workspace.inspect on "workspace:" to browse)`）；
   - 第 2 步（逐层按水位展开）：对深度 `d = 1 .. max_depth - 1` 的非低优非空目录，按子树最新 `mtime_ns` 降序尝试展开其直接子项；若展开该目录后总渲染估算 token 数 `<= max_tokens`，则采纳展开（深度 `< max_depth - 1` 的子目录进入下一层候选），否则保持折叠为目录摘要（有结构压缩而非丢弃路径）；
   - **渲染格式（模型可读文本）**：
     - 空目录：`- workspace:output (Directory, empty)`
     - 已展开目录：记为 `- workspace:src (Directory: 2 dirs, 4 files)`，其已展开子项按稳定路径序紧随其后；
     - 未展开（因深度触顶、低优目录或水位受限而折叠）的非空目录：`- workspace:jobs (Directory: 4 dirs, 12 files, collapsed; inspect to expand)`
     - 文件：`- workspace:src/main.py (Python text, 2480 bytes)`
3. **段契约保持简洁无状态**：
   - `workspace_segment_registration` 维持 `SegmentDescriptor("workspace", "workspace", SegmentSlot.WORKING, 20)`（默认 `SegmentShape.STATE`，不声明 `SegmentCapability.RECLAIM`）；
   - `WorkspaceSegment` 不持有可变预算状态，每次 `prepare()` 同一 `manifest` 产出完全确定的折叠树快照。

### 3.4 根引用 `workspace:` 的只读披露与引用解析

1. **保持写边界安全**：`WorkspaceRef`（`refs.py`）维持 `relative_path` 非空校验不变，所有写操作（`create`、`edit`、`append`、`mkdir`、`move`、`trash`、`write_bundle`）自然拒绝 `"workspace:"`。
2. **`WorkspaceEngine.inspect` 支持 `"workspace:"`**：
   - 当 `resource == "workspace:"` 时：若携带 `#fragment` 则抛出 `WorkspaceContractError`（目录不支持文本片段）；否则扫描工作区根目录直接子项（过滤内部目录、忽略目录与重定向链接），为子目录附上直接子项统计摘要，构造 `DisclosurePage("workspace:", "children", title="Workspace", ...)` 并绑定 `{"day": day}` 生成分页与 `continuation`。
   - 对普通子目录 `workspace:<dir>` 的 `inspect` 同步改进：子项中的目录同样展示子项计数摘要，而非 `Directory, 0 bytes`。
3. **身份解析与搜索范围兼容**：
   - `WorkspaceEngine.canonical_reference`（`engine.py:640`）：当 `resource == "workspace:"` 且 `fragment == ""` 时，合法返回 `ResourceTarget("workspace:", "", source_day or ...)`；携带非空 `fragment` 时仍抛 `ReferenceError`；
   - `WorkspaceEngine.retrieval_corpus`（`engine.py:674`）：当 `ResourceScope` 传入 `ref="workspace:"`（`DIRECTORY` scope）时，等价归一化为全工作区根范围 `locator = ""`，避免模型对根调 `search` 时报错。

### 3.5 模型侧 Actions 重构与语义升级

#### 3.5.1 `workspace.create`（替换 `workspace.write`）
- 参数：`target_ref: str`、`text: str`、`overwrite: bool = False`。
- 校验：在 Executor 入口先校验 `len(text) <= workspace.max_create_chars`（默认 `12288`）。若超出 `max_create_chars`，返回明确局部失败（`reason="create_chars_exceeded"`），提示模型改用 `workspace.compose` 生成长文档或用脚本写入大文件；随后委托 `workspace.write_text(target_ref, text, overwrite=overwrite)`。

#### 3.5.2 `workspace.edit`（锚点位置语义与精确诊断）
- 数据类型（`storage/mutations.py`）：
  - 新增 `WorkspaceEditPosition(StrEnum)`：`REPLACE = "replace"`、`BEFORE = "before"`、`AFTER = "after"`；
  - `WorkspaceTextEdit(old_text: str, new_text: str, position: WorkspaceEditPosition = WorkspaceEditPosition.REPLACE)`；当 `position` 为 `BEFORE` 或 `AFTER` 时，要求 `new_text` 非空。
- 匹配与替换规则：
  - 读取文件时将 `\r\n` 统一规范化为 `\n`（对 `old_text` / `new_text` 同步规范化 `\r\n` -> `\n`）；
  - 先尝试精确子串查找；若精确匹配为 0 处，再尝试“逐行去除行尾空白（trailing spaces/tabs）”的唯一性回退匹配（仅当归一化后全文件恰好唯一匹配 1 段完整行区间时采纳）；
  - **诊断反馈**：
    - 0 处匹配：抛出携带明确 `feedback` 的 `WorkspaceContractError`（指明第 `i` 个 edit 的 `old_text` 未在目标文件中找到，建议先 `workspace.inspect` 核对原文）；
    - 多处匹配（`count >= 2`）：计算前最多 5 处匹配的起始 1-based 行号（如 `lines 18, 64, 112`），在 `feedback` 中明确告知匹配次数与行号，引导补充上下文行消除歧义；
  - **位置合成**：
    - `REPLACE`：用 `new_text` 替换匹配区间；
    - `BEFORE`：在匹配区间起始位置插入 `new_text`（若 `old_text` 以行首开始且 `new_text` 未以 `\n` 结尾，按原文原样拼接或由调用方控制？为避免隐式篡改行内锚点，只有当 `new_text` 不含尾部 `\n` 且匹配位于整行边界、同时插入后会产生粘连时，保持语义明确：遵循确定性原则，在文档与提示中明确说明 `BEFORE`/`AFTER` 在锚点前后拼接，若按行插入请保留换行，或在整行锚点缺少换行时自动补齐单个 `\n`——此处采用**“若锚点位于行首（`BEFORE`）且 `new_text` 非 `\n` 结尾则补 `\n`；若锚点位于行尾不含 `\n`（`AFTER`）且 `new_text` 非 `\n` 开头则补 `\n`”**的防粘连规则，若是行内子串替换仍用 `REPLACE`，兼顾自然与低错率）。

#### 3.5.3 `workspace.compose`（整篇生成 + `#fragment` 片段定位生成）
- 参数：
  - `target_ref: str`（支持 `workspace:path/to/file.md` 或带定位片段 `workspace:path/to/file.md#heading-slug` / `workspace:path/to/file.md#L20-L60`）
  - `instruction: str`（必填，受 `compose.max_instruction_chars` 约束）
  - `references: list[str] = []`（可选只读参考资源，受 `compose.max_reference_refs` 与 `compose.max_reference_chars` 约束；整文件生成时禁止包含同一 `target_ref` 文件，带 `#fragment` 局部生成时禁止传入完全相同的 `target_ref` 片段但允许引用同文件的其他 `#heading` / `#Lstart-Lend` 片段）
  - `mode: "replace" | "before" | "after" = "replace"`（片段定位模式；无 `#fragment` 时仅接受默认的 `"replace"`，传入 `"before"`/`"after"` 返回局部错误引导添加 `#fragment` 或改用 `workspace.append`）
  - `overwrite: bool = False`（仅对**无 `#fragment` 且目标文件已存在**时要求 `overwrite=True`；带 `#fragment` 时本身即表示对已有文件的显式局部改写，无需额外传 `overwrite=True`）
- 执行流程：
  1. 解析 `resource_ref, sep, fragment = target_ref.partition("#")`，校验 `WorkspaceRef.parse(resource_ref)`；
  2. **整文件分支（`not sep`）**：维持现有清晰行为——若文件已存在且 `not overwrite` 则拒绝；若存在且 `overwrite` 则完整读入（超 `max_write_chars` 在调模型前局部失败）；调用 `workspace.compose.generate`（`AnswerFormat.TEXT`），原子写入完整输出；
  3. **片段定位分支（`bool(sep)`）**：
     - 要求 `fragment` 非空且目标文件已存在、为可编辑 UTF-8 文本（超 `max_write_chars` 提前失败）；
     - 调用 `disclosure.fragment_range(full_text, unquote(fragment))` 解析出精确的 1-based `(first_line, last_line)`（片段不存在或越界时捕获 `SearchFailure` 转为可修正局部失败）；
     - 切分 `lines = full_text.splitlines(keepends=True)` 为 `prefix`（`[:first_line-1]`）、`target_span`（`[first_line-1:last_line]`）、`suffix`（`[last_line:]`）；
     - 构造局部 `TaskPrompt`：附带 `prefix` 尾部最多 1200 字符作为只读上文（`# Preceding Context (read-only)`）、`target_span`（`# Target Span`）、`suffix` 头部最多 1200 字符作为只读下文（`# Following Context (read-only)`），在输出约束中明确要求**只输出新片段正文，严禁重复只读上下文**，并受剩余可写字符预算 `max_write_chars - len(kept_parts)` 约束；
     - Phase3 内嵌 LLM 返回纯文本 `generated` 后，规范化段间换行边界（确保非空行块拼接不粘连在同一行），按 `mode` 合成 `prefix + generated + suffix`（`replace`）、`prefix + generated + target_span + suffix`（`before`）或 `prefix + target_span + generated + suffix`（`after`），校验总长 `<= max_write_chars` 后原子落盘；
     - 成功返回 payload 在标准记录字段外附加 `"mode": mode`、`"fragment": unquote(fragment)`、`"target_range": {"start_line": first_line, "end_line": last_line}`、`"generated_chars": len(generated)`。

#### 3.5.4 `workspace.restore`（支持按原路径或 `trash_ref` 恢复）
- 参数：`ref: str | None = None`、`trash_ref: str | None = None`（要求恰提供其一，同时提供或均缺省返回局部参数错误）。
- 存储查找（`WorkspaceTrashStore` / `WorkspaceMutations.restore_resource`）：
  - 若提供 `trash_ref`（`trash:workspace/<id>`）：按现有逻辑精确加载对应回收项；
  - 若提供 `ref`（`workspace:<relative-path>`）：经 `WorkspaceRef.parse(ref)` 规范化后，在当前活动日 `trash_store.list()`（本身已按 `(trashed_at, trash_id)` 倒序排列）中选取 `item.original.ref == canonical_ref` 的**最新一条**进行恢复；若未找到匹配项，返回明确局部反馈 `"No trashed Workspace resource matches <ref> today."`。

### 3.6 Gateway Endpoint、SDK 服务与死代码清理

1. **`tinysoul/plugins/workspace/` 内部清理**：
   - 删除 `tinysoul/plugins/workspace/actions/analysis.py`（`WorkspaceAnalyzeExecutor`）；
   - `prompts.py`：删除 `WorkspaceAnalysisPromptBuilder`，保留并精简服务于 `compose` 的 `WorkspacePromptReferenceResolver`（单参考读取上限改用 `settings.compose.max_reference_chars`）；
   - `inspection/models.py` & `inspection/reader.py`：删除仅服务于 `analyze` 与 `workspace.read` 的 `WorkspaceAnalysis*` 类型、`prepare_analysis_references`、`WorkspaceTextRangeResult`、`WorkspaceReader.read_text_range`（保留 `inspection/text.py` 的底层 `read_text_range` 函数供 `browse_text` 继续分页读取）；将 `WorkspaceReader.read_text` 与 `prepare_task_input` 的默认上限从 `max_read_chars` 切换为 `max_inspect_chars`；
   - `engine.py`、`projection.py`、`events.py`、`services.py`、`__init__.py`：移除 `WorkspaceTag`、`tag`、`set_description`、`insert_text`、`read_text_range`、`prepare_analysis_references`；`WorkspaceChangeOperation` 保留底层 `WRITE`（服务 `write_text`），移除 `INSERT`、`TAG`、`DESCRIBE`；`WorkspaceArchiveView` 将 `max_read_chars` 更名为 `max_inspect_chars`，`ArchivedWorkspaceSegment` 将 `item.context_summary` 切换为 `item.summary`。
2. **`tinysoul/gateway/endpoint/` 契约同步**：
   - `http/routes/workspace.py`：删除 `PUT /v2/workspace/tags` 与 `POST /v2/workspace/insert`；
   - `http/schemas/workspace.py`：删除 `WorkspaceTagRequest`、`WorkspaceInsertRequest`；`WorkspaceEdit` 增加 `position: WorkspaceEditPosition = WorkspaceEditPosition.REPLACE`；`WorkspaceRestoreRequest` 调整为可选 `trash_ref: str | None = None` 与 `ref: str | None = None`（模型校验恰提供其一）；
   - `engine/workspace.py`：删除 `tag()` 与 `insert()`，更新 `restore()` 支持 `trash_ref` 或 `ref`。

### 3.7 模型用途绑定、固定文案、Catalog 与文档同步

1. **模型用途绑定**：
   - `WorkspacePlugin.model_uses`（`plugin.py:114-136`）移除 `workspace.describe.generate` 与 `workspace.analyze.generate`，仅保留 `workspace.search.select`、`workspace.search.rerank`、`workspace.compose.generate`；
   - `assets/{standard,development}/configs/action/routing.toml` 同步移除上述两条 `[[action.models.bindings]]`。
2. **Action Catalog 与 Home Skills**：
   - `assets/common/configs/action/catalog/workspace/actions/`：删除 `list.toml`、`read.toml`、`insert.toml`、`tag.toml`、`describe.toml`、`analyze.toml`、`trash_list.toml`、`write.toml`；新建 `create.toml`；更新 `domain.toml`、`inspect.toml`、`edit.toml`、`append.toml`、`compose.toml`、`mkdir.toml`、`restore.toml` 中的参数 schema 与边界说明（消除所有指向已删除动作的文案）；
   - `assets/common/home/agent/`：更新 `context/working.md`、`skills_domain/workspace/DOMAIN.md`，以及 `skills_action/workspace/` 下的动作指导文档（移除已删动作技能文档，更新 `compose.md`、`edit.md`、`append.md`，补充 `create.md` 如需要或保持轻量）。
3. **固定提示词与设计/接口文档**：
   - `tinysoul/prompts/plugins/workspace.py` & `tinysoul/prompts/README.md`：移除 `ANALYSIS_*`、`DESCRIBE_*`、`INSERT_*`、`LISTING_INCOMPLETE` 等无消费者常量与函数，新增 `edit` 匹配诊断、`create` 超限引导、`compose` 片段定位引导与树目录渲染纯函数；
   - 同步更新 `AGENTS.md`（移除 `pinned/tmp/important` 标签描述与过时说明，对齐当前 Workspace 语义）、`docs/design/workspace.md`、`docs/design/action.md`、`docs/design/capabilities/resource.md`、`docs/endpoint/workspace.md`。

---

## 4. 分阶段实施步骤与文件清单

| 阶段 | 核心工作 | 主要涉及文件 |
| --- | --- | --- |
| **P1：Token 基座、配置与存储** | 新增纯 `infra` 层 `tinysoul/infra/tokens.py`；更新 `WorkspaceSettings` / `WorkspaceComposeSettings` 及配置目录；升级 `WorkspaceManifest` 至 schema v5，移除 `tags`/`description` 及冗余迁移逻辑 | `tinysoul/infra/tokens.py`<br>`tinysoul/plugins/workspace/config.py`<br>`tinysoul/plugins/workspace/storage/{manifest,reconcile,mutations,trash}.py`<br>`tinysoul/infra/config/catalog/context.toml`<br>`tinysoul/assets/{standard,development}/configs/workspace.toml` |
| **P2：渐进披露与根引用** | 实现 `WorkspaceSegment` 无状态 Token 水位树折叠投影及 `ArchivedWorkspaceSegment` 同步；支持根 `"workspace:"` 的 `inspect`、`canonical_reference` 与 `search` 目录范围；更新 `WORKSPACE_SEARCH_FILTERS` | `tinysoul/plugins/workspace/projection.py`<br>`tinysoul/plugins/workspace/engine.py`<br>`tinysoul/prompts/plugins/workspace.py` |
| **P3：动作重构与服务收敛** | 实现 `create`、锚点 `edit`、片段 `compose`、原路径 `restore`；删除 `analysis.py` 及 7 个废弃动作分支与 `WorkspaceService`/`Reader`/`Events` 死方法与死枚举 | `tinysoul/plugins/workspace/actions/{__init__,operations}.py`（删除 `analysis.py`）<br>`tinysoul/plugins/workspace/{events,prompts,services,plugin,__init__}.py`<br>`tinysoul/plugins/workspace/inspection/{models,reader}.py` |
| **P4：资产与 Endpoint 同步** | 更新 Action Catalog `.toml`、`routing.toml`、Home `DOMAIN.md` / `working.md` / `skills_action`；同步 Endpoint 路由与 Schema | `tinysoul/assets/common/configs/action/catalog/workspace/**`<br>`tinysoul/assets/{standard,development}/configs/action/routing.toml`<br>`tinysoul/assets/common/home/**`<br>`tinysoul/gateway/endpoint/{engine/workspace.py,http/routes/workspace.py,http/schemas/workspace.py}` |
| **P5：文档、测试与门禁** | 同步设计文档、`prompts/README.md` 与 Endpoint 文档；迁移跨模块测试中的 `workspace.list`/`read`/`write`/`analyze` 假动作名，重写/新增 `tokens` 与 Workspace 单测及集成测试，跑通 Full + `ty check` | `AGENTS.md`、`tinysoul/prompts/README.md`、`docs/design/{workspace,action}.md`、`docs/design/capabilities/resource.md`、`docs/endpoint/workspace.md`<br>`tests/infra/test_tokens.py`、`tests/plugins/workspace/**`、`tests/gateway/endpoint/**`、`tests/agent/**`、`tests/kernel/**`、`tests/support/**` |

---

## 5. 测试与验证方案

1. **Workspace Owner 单元测试（`tests/plugins/workspace/`）**：
   - Manifest Schema v5：验证 8 字段序列化/反序列化，拒绝旧 v4 或含 `tags`/`description` 的未知字段；验证目录 `size=0, summary="Directory"`；验证 `max_files=5000` 及 `.venv`/`node_modules` 忽略规则；
   - `WorkspaceSegment` 渐进树折叠投影：验证层级 `<= 3` 展开、超深目录折叠、`jobs`/`mcp`/`connections`/`*.assets` 默认折叠、超 `max_context_tokens` 水位时按 `mtime_ns` 优先展开最近活跃子树并将其余子目录折叠为带计数摘要、根级超水位提示及同一 `manifest` 确定性渲染；
   - `inspect` 与根引用：验证 `inspect("workspace:")` 分页及 `continuation`、子目录计数摘要、`canonical_reference("workspace:")` 解析；
   - `create` / `edit` / `compose` / `restore`：
     - `create` 默认拒绝覆盖、`overwrite=True` 允许覆盖、超 `max_create_chars` 返回可修正失败；
     - `edit` 的 `replace`/`before`/`after` 三种位置语义、行尾空白归一化匹配、0 处匹配反馈、多处匹配行号反馈、多步批处理原子性（后项失败不落盘前项）；
     - `compose` 整文件创建/覆写、`#heading` 与 `#Lstart-Lend` 的 `replace`/`before`/`after` 局部生成与拼接边界、片段不存在时的局部失败；
     - `restore` 按原 `ref` 恢复最新删除项、多次删除同路径选最近项、按 `trash_ref` 精确恢复、参数互斥校验。
2. **跨模块与资产验收测试**：
   - 更新 `tests/support/actions.py`、`tests/support/model_uses.py` 及 `tests/kernel/`、`tests/agent/` 中引用旧动作名（如把测试桩 `workspace.list`/`workspace.read` 迁至 `workspace.inspect`/`workspace.create`）；
   - 验证正式 `standard` / `development` 配置模板加载、Action Catalog 编译、`ModelUseRegistry` 绑定完整性及 `infra/config/catalog` 字段覆盖一致性；
   - 更新 `tests/gateway/endpoint/` Workspace 路由测试，验证 `/tags` 与 `/insert` 已移除、`/edit` `position` 与 `/restore` `ref` 契约生效。
3. **完成门禁命令**：
   ```powershell
   uv run --locked --extra dev python scripts/test.py --suite full
   uv run --locked --extra dev ty check
   ```

---

## 6. 执行计划合理性与可行性分析

对照 `AGENTS.md` 核心定义与设计原则逐项核验：

1. **概念与所有权一致性（合理）**：
   - `WorkspaceSegment` 保持 `STATE` 形状与 100% 无状态纯投影：在 `prepare()` 按自身 `max_context_tokens = 3000` 水位做树结构折叠（保留折叠目录引用与子项计数，绝不静默丢弃入口），目录按需展开走统一的 `workspace.inspect` → `TurnTrace` 可折叠结果，既不引入第二套“Working 展开状态机”，也避免了介入全局 `RECLAIM` 导致 `State` 先于旧 `TurnTrace` 被削减的顺位倒挂，并提前铺好 `infra/tokens.py` 供后续 Context 计划无缝复用。
2. **模型认知与动作正交性（合理）**：
   - Workspace 从 19 个动作收敛为 11 个，消除了 `list` vs `inspect` vs `search`、`read` vs `inspect`、`write` vs `compose`、`insert` vs `edit` 四组历史重叠；
   - “短文本字面量用 `create`、锚点精确改/插用 `edit`、尾部追加用 `append`、整篇或 `#fragment` 章节长文用 `compose`”完全覆盖所有文本生产场景，且避开了 Phase2 大 JSON 转义失败与无 CAS 下的行号漂移问题。
3. **无死抽象与数据完整性风险排查（可行）**：
   - **关键风险规避**：在核查 `mutations.py:127, 204, 240, 285` 时确认，所有写操作完成后均依赖 `manifest` 包含刚提交的目标记录。本方案通过将 `max_files` 放宽 50 倍至 `5000` 并忽略 `.venv`/`node_modules`，同时保持 `reconcile` 在 `< max_files` 范围内的完整索引不变量，避免了“静默截断 manifest 导致新建末尾文件 `StopIteration`”的隐患；
   - **跨模块影响可控**：全仓 `git grep` 已定位全部引用旧动作名、旧配置键与 `WorkspaceTag` 的测试桩和配置文件（共约 25 个后端生产/资源文件与相应测试文件），无跨插件隐式耦合，按 P1→P5 顺序推进可平滑落地并通过全部门禁。
