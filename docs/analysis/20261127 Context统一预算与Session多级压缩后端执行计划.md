# Context 统一预算与 Session 多级压缩后端执行计划

- 日期：2026-11-27
- 状态：`ready`（维护者已确认全仓 Context 段预算 100% 统一为 tokens、不兼容旧版存储、在 Workspace 后端完成后实施；已完成架构守卫与 Cycle 时序审计细化）
- 核对基线：`712abf02`
- 关联计划：
  - [Context 统一预算与 Session 多级压缩前端执行计划](20261127%20Context统一预算与Session多级压缩前端执行计划.md)
  - [Workspace 渐进披露与动作收敛后端执行计划](20261127%20Workspace渐进披露与动作收敛后端执行计划.md)
- 依据：
  - [AGENTS.md](../../AGENTS.md)
  - [Context 设计](../design/context.md)
  - [Session 设计](../design/session.md)
  - [Agent Home 设计](../design/agent_home.md)
  - [LLM 设计](../design/llm.md)
  - [Endpoint Inspection 协议](../endpoint/inspection.md)

---

## 0. 核心设计目标与决策矩阵

本计划建立统一的 **Token 级段预算、双水位滞回冰山自压缩与全局阈值协同压缩架构**，并重构 `Session`（线性历史多级语义冰山 + `SessionMap` 轻量图结构），解决当前 `TurnTrace` 与 `Home Heap` 缺乏自身预算、全局 `RECLAIM` 顺位倒挂、UTF-8 字节估算虚高 3～4 倍，以及 `Session` 压缩“砍结论留工具流水账”和边重复膨胀等结构性问题。

| 设计维度 | 目标语义与架构约束 |
| --- | --- |
| 统一计量标尺（`tokens` vs `chars`） | 新增无外部重依赖的 `tinysoul/infra/tokens.py` 确定性分词估算器，供 `llm`、`kernel/context` 与各插件段共用；**所有常驻 Context 段的预算配置与监控统一使用 `tokens`**，单次文件/分页读写边界（如 `max_write_chars`、`max_inspect_chars`）继续使用 `chars`/`bytes` |
| 段预算双模式（`fixed` / `pool_share`） | 每个受管段声明 `SegmentBudgetPolicy`：支持固定上限 `fixed(max_tokens)`，或按可用弹性池分配 `pool_share(share, min_tokens, max_tokens?)`，其中 `Pool = 有效参考窗口 × trigger_ratio - 预留开销 - 固定基线占用` |
| 预期比例自压缩（`target_ratio`） | 段占用超过 `effective_max_tokens` 时，触发段自身的冰山无损压缩算法向 `target_tokens = effective_max_tokens × target_ratio` 收敛（尽力而为），留出增长缓冲带以避免每轮临界抖动打碎供应商 Prompt Cache |
| 全局阈值协同压缩与豁免（`global_reclaim`） | 仅大头弹性段（`trace`、`session`、`home` 动态加载区）设 `global_reclaim = True`；小而关键的状态/基线段（`identity`、`inputs`、`home` 基线、`memory`、`plan`、`workspace`、`jobs`、`connections`）设 `global_reclaim = False`（仍保留各自的段内自压缩或上限校验）；全局触发时按权重同步向各自预期目标压缩 |
| `Home` 基线与动态 Heap 分离核算 | `Home` 的技能目录（`skill_catalog`）与受保护默认项（`default_refs`）归入不可逐出基线，不计入 `Home` 动态加载预算；仅通过 `core.background` 动态加载的可逐出 `home:top/...` 参与动态预算与 LRU 压缩，且当批次刚请求加载的条目受当轮保护 |
| 清理 `Memory` 空壳 `SELECT/RECLAIM` | `MEMORY_SEGMENT` 移除名不副实的 `HEAP` `SELECT` 与 `RECLAIM` 声明，回归受保护 `STATE` 基线段（由写入端文档上限自然约束） |
| `Session` 四级语义冰山与动作分级 | 按“对话主干（`input/ask/reply/output`）> 显式推理结论与里程碑（`core.reason` 结果 + `milestones`）> 变更/执行动作意图与结果摘要（不内联写入正文）> 纯探索读取足迹（`inspect/search`）”分级投影，实现 `L0 → L1 → L2 → L3` 四级可追溯压缩 |
| `SessionMap` 图结构 v2 与去重协同 | `map.json` 升至 `version = 2`：`thread` 节点通过 `turn_refs` 直接声明成员轮次，移除冗余的 `SemanticRelation.COVERS` 边；`SemanticEdge.body` 改为可选短说明（`<= 240` 字符）；渲染时节点与边分离单次输出，消除双端重复渲染 |

进度检查项：

- [ ] C1：`llm/protocol/tokens.py` 协议消息估算（复用先行落地的 `infra/tokens.py`）与 `llm/execution/context_window.py` 对齐
- [ ] C2：`kernel/context` 段预算协议（`SegmentBudgetPolicy`）、段级自压缩调度与全局协同压力回收重构
- [ ] C3：`TurnTrace`、`Home`（基线/动态分离 + LRU）、`Memory`（去空壳）、`Plan`/`Jobs`/`Connections` 段内冰山自压缩实现
- [ ] C4：`Session` 动作语义分级、L0–L3 四级线性历史冰山与 `SessionMap` v2 重构
- [ ] C5：Context Overview 契约扩展（支持前端 Delta 风格窗口分解与跳转）、配置目录、文档与全量测试门禁验收

---

## 1. 已核实的现状问题与代码依据

### 1.1 Token 估算失真与配置单位割裂

1. `tinysoul/llm/execution/context_window.py:110-140, 243-244` 中，`ConservativeRequestTokenEstimator._text_size` 直接以 **`len(value.encode("utf-8"))`（UTF-8 字节数）充当 token 数**：
   - 纯英文/代码场景下 1 token 约占 3.5～4 字节，当前算法**高估约 3.5～4 倍**；
   - 中文场景下 1 个汉字占 3 个 UTF-8 字节（实际分词器约 0.6～1.0 token/字），当前算法**高估约 3 倍**（仅约 7 万汉字就会虚报为 21 万 tokens，提前误触发 262k 窗口的 80% 阈值）。
2. 同时，`context.max_window_tokens` 用 `tokens` 配置，而 `session.max_background_chars`、`context.trace_chunk_chars`、`home.max_skill_catalog_chars` 全用 `chars` 配置，用户在 Context 设置页难以直观换算各段占总窗口的真实比例。

### 1.2 段自预算缺失、全局 `RECLAIM` 顺位倒挂与空壳声明

1. **核心动态段缺乏自身高水位**：
   - `TurnTraceHeap`（`tinysoul/kernel/context/builtin/trace.py:541-584`）在日常 Cycle 追加时从不调用 `fold_overlays()` 或 `compact()`，导致几十轮前已读完的 `inspect` 8k 页面一直常驻热区，直到撞上全局窗口阈值；
   - `HeapSegment`（`tinysoul/kernel/context/background.py:195-215, 346-383`）在 Phase1 动态 `load_refs` 时无任何段上限检查，且逐出顺序按字典插入顺序而非最近使用（LRU）。
2. **全局回收顺序不合理**：`TurnSegments.reclaim`（`tinysoul/kernel/context/segments/collection.py:238-257`）按 `STATE → HEAP → STACK → MAP` 线性扣减，直到凑够 `required_chars` 即停止——导致 `Home Heap` 先被整篇清空，而后才轮到 `TurnTrace` 折叠旧临时页。
3. **空壳能力声明**：`MEMORY_SEGMENT`（`tinysoul/plugins/memory/background.py:75-80, 196-203`）声明了 `{SELECT, RECLAIM}`，但内部 `evictable_default_refs = ()` 且无可动态加载项，`reclaim()` 恒返回 0。
4. **小增长段缺乏收口保护**：`PlanSegment`（`working.py`）在长任务中 `DONE`/`CANCELLED` todos 无限堆积；`JobsSegment`（`jobs/segment.py`）已完成任务完整快照持续堆积。

### 1.3 `Session` 历史压缩倒置与 `SessionMap` 图膨胀

1. **主次倒置（`tinysoul/plugins/session/views/background.py:85-159`）**：
   - L0 未压缩态通过 `_action_fields`（第 290–300 行）将历史轮次中 `workspace.write`/`edit` 等动作请求里的完整文件正文 `text`/`new_text` 原样输出到 Session Background；
   - 超预算进入 `_compact_turn` 时，将最重要的 `user.input` 与 `agent.output` 截断为 **240 字符**（第 130–134 行），却为每条中间 `agent.action` 保留 `400 + 400 = 800` 字符（第 149–157 行），且将 `core.reason` 的大段 `guide_blocks` 请求模板与普通动作混同处理；
   - 再超预算折叠时（第 99–105 行），整轮仅保留 `first_input[:120]`，完全丢弃了 `SessionTurnRecord` 中已保存的 `output`、`working.milestones` 与 `resource_refs`。
2. **`SessionMap` 结构冗余（`annotations/models.py:152-210`、`views/navigation.py:58-69`、`views/inspection.py:715-723`）**：
   - `thread` 归属必须额外创建多条 `relation="covers"` 的 `SemanticEdge`（每条强制要求非空 `body <= 4000` 与 `source_refs`），否则 `_unclassified()` 仍视该轮为未归类；
   - `annotation_navigation` 在每条边的源节点和目标节点下各嵌入一次完整边对象，造成双倍渲染。

---

## 2. 详细改进设计

### 2.1 统一确定性 Token 估算分层（`infra/tokens.py` + `llm/protocol/tokens.py`）

严格遵循 `tests/test_architecture.py:145-150` 的模块依赖方向约束（`infra` 仅允许导入 `infra`，`llm` 允许导入 `infra/llm`，`kernel` 与 `plugins` 允许导入 `infra/llm`）：

1. **纯基础设施标尺（`tinysoul/infra/tokens.py`，在先行的 Workspace 计划 P1 已落地）**：
   - 对字符串区分 ASCII 字符（`ord(ch) < 128`，按 `3.5 chars ≈ 1 token` 上取整）与非 ASCII 字符（中日韩及符号 `ord(ch) >= 128`，按 `1.0 char ≈ 1 token` 计）：
     `estimate_text_tokens(text) = ceil(ascii_count / 3.5 + non_ascii_count)`；
   - `estimate_json_tokens(value: JsonValue) -> int`：避免重复序列化大对象，对基础标量/容器递归累加键值 token 与结构分隔符开销；
   - `estimate_image_tokens(byte_length: int) -> int`：按 `max(85, byte_length // 750)` 估算视觉 token（内联图像同时继续受 `context.max_image_bytes` 字节硬上限独立约束）。
2. **协议消息与工具作用域估算（`tinysoul/llm/protocol/tokens.py`）**：
   - 基于 `infra.tokens` 封装针对 `Message`、`ToolCall`、`ToolScope` 的 `estimate_message_tokens(message)`、`estimate_messages_tokens(messages)` 与 `estimate_tool_scope_tokens(tool_scope)`，供 `llm`、`kernel/context` 与 `plugins` 共用，绝不在 `infra` 中反向导入 `llm.protocol`。
3. **`LLM` 窗口预检统一标尺**：
   - `tinysoul/llm/execution/context_window.py` 的 `ConservativeRequestTokenEstimator` 改为直接调用 `llm.protocol.tokens`；
   - 供应商 API 真实分词超限返回 `ProviderErrorKind.CONTEXT_LIMIT` 时，`task.py:511` 的 `provider_reported_limit=True` 兜底路径保持不变。

### 2.2 Context 段预算模型与双层压缩调度（`tinysoul/kernel/context/`）

#### 2.2.1 协议与数据结构

在 `tinysoul/kernel/context/segments/protocol.py` 中升级压缩协议（替代原无目标语义的 `ReclaimableSegment`）：

```python
class BudgetMode(StrEnum):
    FIXED = "fixed"
    POOL_SHARE = "pool_share"
    EXEMPT_UNBOUNDED = "exempt_unbounded"  # 如 system identity、当轮 user inputs

@dataclass(frozen=True)
class SegmentBudgetSpec:
    mode: BudgetMode
    max_tokens: int | None = None          # FIXED 必填；POOL_SHARE 可选封顶
    pool_share: float | None = None        # POOL_SHARE 必填 (> 0)
    min_tokens: int = 256                  # POOL_SHARE 保底水位
    target_ratio: float = 0.65             # 触发压缩时的目标比例 (0 < r <= 1.0)
    global_reclaim: bool = False           # 是否参与全局窗口阈值协同压缩
    settings_page: str = "context"         # 供前端 Overview 一键跳转的所属配置页标识

@dataclass(frozen=True)
class ResolvedSegmentBudget:
    mode: BudgetMode
    effective_max_tokens: int | None
    target_tokens: int | None
    pool_share: float | None
    global_reclaim: bool
    settings_page: str

@dataclass(frozen=True)
class SegmentCompactionState:
    compressed: bool = False
    summary: str = ""                      # 如 "2 cold nodes, 3 folded overlays" / "L1:3, L2:5"
    baseline_tokens: int | None = None     # 供 Home 等含受保护基线的段披露拆分明细
    dynamic_tokens: int | None = None

@dataclass(frozen=True)
class SegmentCompressResult:
    before_tokens: int
    after_tokens: int
    evicted_refs: tuple[str, ...] = ()

@runtime_checkable
class CompressibleSegment(Protocol):
    def countable_tokens(self) -> int: ...  # 计入该段可压缩水位的当前 token 数
    def compress_to(self, target_tokens: int) -> SegmentCompressResult: ...
    def compaction_state(self) -> SegmentCompactionState: ...
```

#### 2.2.2 可用弹性池解析公式

1. **参考有效窗口 $W_{\text{ref}}$（无耦合注入）**：
   - 由 `LLMRunner` 门面暴露只读查询 `reference_window_tokens(*profiles: str) -> int | None`（读取主循环 Phase1/Phase2 首选模型的 `context_window_tokens` 最小值）；
   - `UserTurnBuilder` 与 `Reflection` 组装器将其传入 `build_turn_context(..., reference_window_tokens=...)` → `ContextEngineBuilder`，与 `context.max_window_tokens` 取较小值作为 $W_{\text{ref}}$（独立单测未绑定模型时默认回退 `131072`），保持 `kernel/context` 与 `LLMSettings` 路由配置完全解耦，同时遵守 `test_agent_builder_does_not_assemble_turn_kernel_details`；
   - 全局触发线：`trigger_tokens = int(W_ref * context.compression_trigger_ratio)`（默认 `0.80`）；
   - 预留非段开销：`context.reserved_overhead_tokens`（默认 `16384` tokens，覆盖 Phase2 Tool Schemas、`TaskPrompt` 临时挂载 Skill 与模型输出预留的常规空间）。
2. **固定基线扣除与比例池分配**：
   - 计算当前已安装固定/基线段的实际占用之和 `baseline_used_tokens`（含 `identity`、`inputs`、`journal`、`memory`、`home` 的受保护默认项+目录、`plan`、`workspace`、`jobs`、`connections`）；
   - 可用弹性池：`elastic_pool_tokens = max(0, trigger_tokens - reserved_overhead_tokens - baseline_used_tokens)`；
   - 对每个 `POOL_SHARE` 段 $i$（权重归一化 `w_i = share_i / Σ share`）：
     `effective_max_i = clamp(int(elastic_pool_tokens * w_i), min_tokens_i, max_tokens_i)`
     `target_i = int(effective_max_i * target_ratio_i)`。

#### 2.2.3 两级触发逻辑与 Cycle 边界保护时序

1. **第一级：段自身高水位触发（Cycle 边界常态主力，保护同轮编辑与缓存命中）**
   - **关键时序设计**：在 **Turn `open()` 初始化完成时**，以及**每个完整 Cycle 边界（`CycleRunner` 进入新 Cycle 前的边界结算点 / Phase3 结果落入后，而非同一 Cycle 内 Phase1 → Phase2 之间）**，调用 `ContextEngine.reconcile_segment_budgets()` 遍历所有 `CompressibleSegment`：
   - 若 `segment.countable_tokens() > budget.effective_max_tokens`，立即调用 **`segment.compress_to(budget.target_tokens)`**（尽力而为，不抛异常中断正常流程）；
   - **为什么不在同一 Cycle 的 Phase1 与 Phase2 之间自压缩 `TurnTrace`**：
     1. Cycle $N$ Phase3 刚通过 `workspace.inspect` 读入的原文页受 `_protected_overlays` 保护；Cycle $N+1$ Phase1 只能选域（如选中 `workspace`），随后立即触发 `mark_model_consumed` 释放保护——紧接着的 **Cycle $N+1$ Phase2** 正好需要对照这页原文构造 `workspace.edit(old_text=...)`。将常规自压缩锚定在 Cycle 边界，可保证新读入的 `inspect` 页面完整服务完 **Phase1 + Phase2 整个决策轮**，并在进入 Cycle $N+2$ 前确定性折叠回收（完全符合 `AGENTS.md:51`“解除保护不立即移除正文”）；
     2. 同时避免在同一 Cycle 的 Phase1 与 Phase2 之间改写 `MessageStack` 中部历史，保住同 Cycle 内 Phase1 → Phase2 的供应商 Prompt Cache 前缀命中率！（注：Phase1 执行 `core.background` 动态加载 `Home` 时，对 `Home` 段单独检查动态高水位即可。）
   - **固定小增长段特例**：像 `plan`、`jobs`、`connections` 这类配置为 `mode = FIXED, global_reclaim = False, target_ratio = 0.65~0.70` 的段，**完全不会被全局窗口压力打扰，但当自身在超长 Turn 中增长触及 `max_tokens` 时，会在 Cycle 边界自动按 `target_ratio` 将已完结历史项折叠回落**。
2. **第二级：全局窗口阈值协同触发（`reclaim_pressure` 保险阀）**
   - 当 LLM 执行边界因某候选模型窗口较小（如降级到 64k 备选模型）、超大 MCP 工具集或分词偏差抛出 `ModelContextPressureError(usage)` 时：
   - 计算该候选模型的目标总消息容量：
     `model_target_tokens = max(0, int(usage.effective_window_tokens * context.compression_target_ratio) - usage.estimate.non_message_tokens - usage.reserved_output_tokens)`；
   - 扣除所有 `global_reclaim = False` 段与 `home` 受保护基线的当前占用 `exempt_tokens`，得到本次全局回收后的可用弹性目标池 `remaining_pool = max(0, model_target_tokens - exempt_tokens)`；
   - 对所有 **`global_reclaim = True`** 的段（默认即 `trace`、`session`、`home` 动态区），计算协同目标：
     `goal_i = min(int(current_countable_i * target_ratio_i), max(min_floor_i, int(remaining_pool * w_i)))`
     并统一触发 `segment_i.compress_to(goal_i)`！
   - 若本轮合计释放 `reclaimed_tokens > 0` 则重放当前 LLM Task；若所有可压缩段均已压至不可分割底线仍为 0，则返回 `NO_PROGRESS` 正常结束恢复尝试。

---

### 2.3 全量 Context 段具体预算配置与冰山压缩实现

| 段 ID | 配置归属 | 默认预算策略 | `target_ratio` | `global_reclaim` | 冰山无损自压缩算法 |
| --- | --- | --- | --- | --- | --- |
| `identity` | `context.toml` | `EXEMPT_UNBOUNDED` | — | `False` | 不压缩 |
| `inputs` | `context.toml` | `EXEMPT_UNBOUNDED` | — | `False` | 不压缩（与 `TurnTrace` 首条输入共同强调当轮用户诉求） |
| `journal` | `context.toml` | `EXEMPT_UNBOUNDED` | — | `False` | 不压缩 |
| `session` | `session.toml` | `POOL_SHARE`（`share = 0.25`, `min = 4096`, `max = 24576`）*可改配 `FIXED`* | `0.65` | **`True`** | L0→L1→L2→L3 四级会话冰山 + `SessionMap` 节点正文按活跃度折叠（见 §2.4） |
| `home` | `home.toml` | 目录固定 `max_skill_catalog_tokens = 2048` + 默认项豁免；**动态区 `POOL_SHARE`（`share = 0.15`, `min = 4096`, `max = 16384`）** | `0.65` | **`True`**（仅动态区） | 基线（`catalog + protected default_refs`）从 `countable_tokens()` 中排除且永不逐出；动态加载项记录最近访问序号，超水位按 **LRU** 逐出至 `target_tokens`（当前批次刚请求 `load_refs` 的条目受本批次保护，保留 catalog 入口可随时重 `load`） |
| `memory` | `memory.toml` | `EXEMPT_UNBOUNDED`（写入端已由 `max_active_chars` / `max_daily_chars` 硬约束） | — | `False` | 移除原空壳 `HEAP` `SELECT`/`RECLAIM`，改为清晰的只读/刷新 `STATE` 背景段 |
| `trace` | `context.toml` | `POOL_SHARE`（`share = 0.60`, `min = 8192`, `max = 49152`）*可改配 `FIXED`* | `0.60` | **`True`** | ① 先执行 `fold_overlays()` 折叠所有已解除单轮保护的 `foldable` 动作正文（保留 `recollection` 与 `origin_refs`）；② 若仍 `> target_tokens`，按完整 Cycle 将较早 `hot_entries`（保护末尾 `trace_min_hot_entries` 与未解除保护项）打入 `trace_chunk_tokens = 3072` 的 `LEAF` 及四叉 `BRANCH` 树节点 |
| `plan` | `context.toml` | `FIXED`（`max_tokens = 2048`） | `0.70` | `False` | 保留全部 `milestones` 及 `IN_PROGRESS`/`PENDING` todos；超 `max_tokens` 时按完成先后将较早 `DONE`/`CANCELLED` todos 折叠为摘要计数 `completed_todos_folded: N (traceable in turn:trace)`；若仅活跃项+milestones 即超 `max_tokens`，在 `WorkingPatch` 校验时返回局部控制反馈要求精简 milestone |
| `workspace` | `workspace.toml` | `FIXED`（`max_context_tokens = 3000`，`default_expand_depth = 3`） | `1.0` | `False` | 无状态 BFS 目录树折叠：低优目录（`jobs`/`mcp`/`connections`/`*.assets`）默认折叠，超预算子目录折叠为带子项计数的目录摘要，通过 `workspace.inspect` 展开 |
| `jobs` | `jobs.toml` | `FIXED`（`max_tokens = 1536`） | `0.65` | `False` | 始终完整保留 `RUNNING`/`WAITING_INPUT` 活动任务；超水位时将较早终态（`COMPLETED`/`FAILED`/`STOPPED`）任务折叠为单行摘要 `job_id [state] -> result_refs` |
| `connections` | `subagent.toml` | `FIXED`（`max_tokens = 1024`） | `0.70` | `False` | 完整保留活动委派连接；超水位时将较早空闲（`idle`）连接压缩为 `connection_id (agent_id, idle)` |

> **衔接说明**：先行的 Workspace 后端计划已将 `workspace.max_context_tokens = 3000` 与 `tinysoul/infra/tokens.py` 落地；本计划在 C2/C5 直接为 `WorkspaceSegment` 补齐 `SegmentBudgetSpec(mode=FIXED, max_tokens=3000, target_ratio=1.0, global_reclaim=False, settings_page="workspace")` 声明以纳入 Context Overview 统一监控面板。

---

### 2.4 `Session` 深度重构：动作分级、四级语义冰山与 `SessionMap` v2

#### 2.4.1 历史交互中的四类语义分级（`plugins/session/views/interaction.py` & `background.py`）

不改变 `SessionTurnRecord` 落盘的不可变原始事实（`session:turn/...#action/<i>` 仍可随时 `inspect` 查看原始参数与结果），仅升级 Background 模型投影：

1. **第一优先级：对话主干（Dialogue Backbone）**
   - `user.input`、`user.append`、`agent.question`（`core.ask` 完整题干、选项列表与说明，绝不拆散选项与回复）、`user.reply`、`agent.output`（`core.answer` 最终正式回复）。
2. **第二优先级：显式推理产物与本轮里程碑（Reasoning & Milestones）**
   - `agent.reason`（`core.reason`）：投影时提取其引导标题线索与结构化 `result` 结论，**省略请求侧冗长的 `guide_blocks` / `input_blocks` / `output_blocks` 模板文本**；
   - `working.milestones`：从 `SessionTurnRecord.working` 提取本轮结束时沉淀的 `milestones` 键值对，作为该轮关键事实结论的一部分。
3. **第三优先级：变更与执行动作（State-Modifying & Execution Actions）**
   - 对非 `foldable` 的业务动作（如 `workspace.create/compose/edit/append/move/delete/restore`、`execution.run/start`、`memory.memorize`、`home.*`、`web.fetch*`、`subagent.delegate`），投影为**“动作意图 + 目标引用 + 执行结果摘要”**，**剔除请求参数中的大块字面量正文（如 `text`、`old_text`、`new_text`、`source`）**：
     - 示例：`workspace.compose -> workspace:reports/arch.md#design (mode=replace, instruction="补充缓存一致性方案", ok, 1840 chars)`
     - 示例：`execution.run (python: "pytest tests/session", failed: exit_code=1 -> workspace:jobs/job_1/logs/stderr.log)`
4. **第四优先级：纯探索与披露读取动作（Exploratory Read-Only Actions）**
   - 凡 `result` 带 `inspected: True`（各域 `inspect`）或搜索页回忆结构（各域 `search`）的动作，仅保留读取目标 `ref`、覆盖范围与命中状态，不展开大段列表。

#### 2.4.2 线性历史的 L0–L3 四级语义冰山压缩算法（`SessionBackgroundSnapshot.fit`）

对候选历史 Turn 按优先级排序（`最近 3 轮` → `活跃话题/关系直接关联轮` → `未归类轮` → `其余历史轮`），根据目标预算 `target_tokens` 为每个 Turn 选择最高可容纳档位（最终仍按时间正序输出）：

- **L0（近期热轮完整态，默认赋给最近 1～2 轮且预算允许时）**：
  完整保留 `input/append`、`ask + 完整选项 + reply`、完整 `output`、`reason` 结论、`milestones`、每条变更/执行动作的意图结果行，以及探索读取动作的精简目标摘要。
- **L1（对话与结论保留态，过程折叠）**：
  保留完整（或高上限：单条 `<= 600` tokens，超长标明 `[excerpted — inspect session:turn/...#output]`）的 `input/append`、完整未截断的 `ask + reply`、`output` 与 `milestones`；将本轮全部中间动作**折叠为 1 行结构化行动摘要**：
  `Actions (5 ok, 1 failed): workspace.compose, workspace.edit×2, execution.run | refs: workspace:reports/arch.md (inspect session:turn/YYYY-MM-DD/k#actions)`。
- **L2（结构化轮次卡片态 / Turn Digest，单轮约 80～120 tokens）**：
  保留该轮的完整因果骨架，绝不只留一句孤立提问：
  - `Input`: 初始诉求与追加摘要（`<= 160` 字符）+ 若含问答则标注 `[1 Q&A settled]`（不拆出孤立选项）
  - `Conclusion`: 正式 `output` 核心摘录（`<= 240` 字符；无 `output` 时展示终态原因如 `cancelled`/`failed`）
  - `Key Milestones & Refs`: 最多 3 条 milestone 摘要 + 本轮关键 `target_ref` 列表
  - `Inspect`: `session:turn/YYYY-MM-DD/k`
- **L3（仅地图目录索引态）**：
  极端超长会话（数十至上百轮）在 L2 仍超出 `target_tokens` 时，旧轮次退出线性区，仅保留在 `session:map` 的话题 `turn_refs` 或 `unclassified` 列表中供 `core.context.inspect` 检索读取。

> **单调收缩保证**：若同一 Turn 内因全局窗口压力触发 `compress_to(smaller_target)`，在当前已披露集合内将部分 L0→L1、L1→L2 或 L2→L3 降档，本轮后续 `organize` 刷新沿用收紧后的本轮水位上限，下一新 Turn 重新按常规预算构建。

#### 2.4.3 `SessionMap` 图结构 v2 与无重复压缩投影（`annotations/models.py` & `views/`）

1. **存储结构升级（`map.json` 严格校验 `version == 2`，不保留 v1 历史兼容分支）**：
   - `SemanticNode`：
     - 新增字段 `turn_refs: tuple[str, ...] = ()`（校验每项为合法 `session:turn/YYYY-MM-DD/<seq>`，上限 64）；当 `kind == AnnotationKind.THREAD` 时，`turn_refs` 必填非空，直接表达该话题覆盖的轮次集合；`kind == AnnotationKind.NOTE` 时 `turn_refs` 可选；
     - `title` 上限 `160` 字符，`body` 上限从 `4000` 收紧为 `1200` 字符（促使模型提炼高密度话题脉络而非复制对话原文），`source_refs`（具体证据引用，上限 32）保持不变。
   - `SemanticEdge`：
     - 从 `SemanticRelation` 中**移除 `COVERS`**（保留 `continues`、`branches_from`、`clarifies`、`revises`、`supports`、`contradicts`、`resolves`、`steers` 8 种真实语义关系）；
     - `body` 改为**允许空字符串 `""`**，最大长度从 `4000` 收紧为 `240` 字符；
     - `source_refs` 改为可选（默认 `()`；当 `source` 或 `target` 为 `session:node/...` 且需补充具体叶级证据时填写；当两端本身已是 `session:turn/...` 时无需重复抄写两端 ref）。
   - `SessionView._unclassified()` 更新为：凡不在任何 `ACTIVE` `THREAD` 节点的 `turn_refs` 中的已完成 Turn 即为未归类轮次。
2. **模型可见 `session_map` 投影与配额协同**：
   - **消除双端重复**：`session_map` 清晰分为 `Topics & Notes` 与 `Relations` 两段，每条活跃 `SemanticEdge` 全局只渲染一次：
     - 节点展开态：`[thread] 标题 (session:node/...) | turns: 1, 2, 5 | body... | evidence: ...`
     - 节点折叠态：`[thread] 标题 (session:node/...) | turns: 1, 2, 5 [folded — inspect node]`
     - 关系行：`session:node/1 --[revises]--> session:node/2: 简短说明 (session:edge/1)`
   - **冷启动友好头**：即使尚未调用 `core.session.organize`（无人工节点），`session_map` 头部也清晰列出 `Completed turns: N | Unclassified: N (inspect session:history or session:map)`；
   - **弹性共享预算**：地图区最多使用当前 Session 目标预算的 `30%`（节点过多时按关联轮次新旧将旧节点从展开态降为折叠态）；地图未用完的预算 100% 留给下方线性历史。
3. **同步 `core.session.organize` Action 定义与指导**：
   - 更新 `tinysoul/assets/common/configs/action/catalog/core/actions/session_organize.toml` 与对应技能说明， 반영 `turn_refs`、无 `covers` 边及轻量 `edge.body` 协议。

---

### 2.5 Context Overview 监控契约扩展（对接前端 Delta 风格视图）

修改 `ContextEngine.installed_overview()`（`tinysoul/kernel/context/engine.py:914-952`）及 Endpoint `/v2/turns/{id}/context` 响应结构（向后兼容保留 `chars` 与 `image_bytes`，新增统一 `tokens` 与 `budget` 视图）：

1. **顶层新增 `window` 汇总对象**：
   ```json
   "window": {
     "reference_window_tokens": 262144,
     "trigger_ratio": 0.8,
     "target_ratio": 0.5,
     "trigger_tokens": 209715,
     "reserved_overhead_tokens": 16384,
     "fixed_baseline_tokens": 8420,
     "elastic_pool_tokens": 184911,
     "used_message_tokens": 42180
   }
   ```
   （注：若当前 Turn 已有实际执行的 LLM Task 记录了最新的 `effective_window_tokens` 与 `non_message_tokens`，一并附在可选 `"last_model_call"` 快照中供前端精确展示工具定义占用。）
2. **`segments[]` 每项新增字段**：
   - `"tokens": int`（该段总渲染 token 估算值）
   - `"budget"`: `{ "mode": "fixed" | "pool_share" | "exempt_unbounded", "effective_max_tokens": int | null, "target_tokens": int | null, "pool_share": float | null, "target_ratio": float | null, "global_reclaim": bool, "settings_page": str }`
   - `"compaction"`: `{ "compressed": bool, "summary": str, "baseline_tokens": int | null, "dynamic_tokens": int | null }`
3. 同步更新 `docs/endpoint/inspection.md`、`docs/endpoint/contracts/schemas/context-overview.json` 及示例 JSON。

---

## 3. 配置文件变更清单预览

1. **`context.toml`（`standard` & `development`）**：
   - 保留：`system_text`、`journal`、`max_window_tokens`、`max_image_bytes`、`compression_trigger_ratio = 0.8`、`compression_target_ratio = 0.5`、`trace_branch_factor = 4`、`trace_min_hot_entries = 2`、`max_trace_inspect_chars = 8192`
   - 新增/替换：
     - `reserved_overhead_tokens = 16384`
     - `plan_max_tokens = 2048`、`plan_target_ratio = 0.70`
     - `[context.trace]`（或扁平键）：`mode = "pool_share"`、`pool_share = 0.60`、`min_tokens = 8192`、`max_tokens = 49152`、`target_ratio = 0.60`、`chunk_tokens = 3072`（替换原 `trace_chunk_chars = 12288`）
2. **`session.toml`**：
   - 保留：`root`、`max_inspect_chars = 8192`
   - 替换 `max_background_chars` 为 `[session.context]`（或扁平键）：`mode = "pool_share"`、`pool_share = 0.25`、`min_tokens = 4096`、`max_tokens = 24576`、`target_ratio = 0.65`
3. **`home.toml`**：
   - `max_skill_catalog_tokens = 2048`（替换原 `max_skill_catalog_chars = 8192`；`max_read_chars`/`max_write_chars` 保持字符单位不变）
   - 新增动态背景预算：`[home.context]`：`mode = "pool_share"`、`pool_share = 0.15`、`min_tokens = 4096`、`max_tokens = 16384`、`target_ratio = 0.65`
4. **`workspace.toml`、`jobs.toml`、`capabilities/subagent.toml`**：
   - `workspace.max_context_tokens = 3000`（已由先行 Workspace 计划落地，本计划直接接入 `SegmentBudgetSpec` 概览展示）
   - `jobs.max_context_tokens = 1536`、`jobs.context_target_ratio = 0.65`
   - `capabilities.subagent.max_connections_tokens = 1024`、`capabilities.subagent.connections_target_ratio = 0.70`
5. **配置元数据目录与预设（Presets）同步**：
   - `tinysoul/infra/config/catalog/context.toml`：更新 `context_rules`、`session`、`home` 段预算字段；
   - `tinysoul/infra/config/catalog/execution.toml`：在 `surface = "jobs"` 下补充 `jobs.max_context_tokens`、`jobs.context_target_ratio`；
   - `tinysoul/infra/config/catalog/capabilities.toml`：在 `surface = "capabilities.subagent"` 下补充 `capabilities.subagent.max_connections_tokens`、`capabilities.subagent.connections_target_ratio`；
   - `tinysoul/infra/config/editing/presets.py`（`_BUDGETS` 与 `sections`）及 `docs/endpoint/contracts/examples/preset.json`：将旧 `session.max_background_chars`、`context.trace_chunk_chars` 替换为新 Token 预算路径。

---

## 4. 分阶段实施步骤

| 阶段 | 核心交付内容 | 主要涉及模块/文件 |
| --- | --- | --- |
| **C1：LLM 协议 Token 估算对齐** | 基于先行落地的 `infra/tokens.py` 新增 `tinysoul/llm/protocol/tokens.py`（`Message`/`ToolScope` 估算）并暴露 `reference_window_tokens`；切换 `llm/execution/context_window.py` 使用统一标尺并补齐中英文/代码/工具定义估算单测 | `tinysoul/llm/protocol/tokens.py`<br>`tinysoul/llm/execution/context_window.py`<br>`tinysoul/llm/runner.py` |
| **C2：Context 预算与调度内核** | 定义 `SegmentBudgetSpec` / `CompressibleSegment`；在 `ContextEngine`、`TurnSegments` 与 `CycleRunner` 实现参考窗口注入、弹性池解析、Cycle 边界段级自压缩触发与按权重全局 `reclaim_pressure`；扩展 `installed_overview` | `tinysoul/kernel/context/{config,engine,compress,background}.py`<br>`tinysoul/kernel/context/segments/{protocol,collection,registration}.py`<br>`tinysoul/kernel/loop/{assembly,cycle}.py`<br>`tinysoul/agent/user/builder.py`、`tinysoul/plugins/reflection/**` |
| **C3：各段自压缩与去空壳** | `TurnTraceHeap` 接入 token 分块与周期自压缩；`Home` 分离受保护基线与动态 LRU 预算（含当批加载保护）；`Memory` 移除空壳 `SELECT/RECLAIM`；`Plan`、`Jobs`、`Connections` 实现各自固定上限自压缩 | `tinysoul/kernel/context/builtin/{core,trace,working}.py`<br>`tinysoul/plugins/home/{config,background,engine}.py`<br>`tinysoul/plugins/memory/background.py`<br>`tinysoul/kernel/jobs/{config,segment}.py`<br>`tinysoul/plugins/capabilities/subagent/{config,segments/connections.py}` |
| **C4：Session 四级冰山与 Map v2** | 实现 Session 动作四分类投影、L0–L3 线性冰山压缩；升级 `SessionMap` v2（`turn_refs`、移除 `COVERS`、轻量可选 `edge.body`、单次边渲染）；更新 `core.session.organize` catalog 与提示词 | `tinysoul/plugins/session/{config,projection}.py`<br>`tinysoul/plugins/session/annotations/models.py`<br>`tinysoul/plugins/session/views/{background,interaction,inspection,navigation}.py`<br>`tinysoul/prompts/plugins/session.py`<br>`tinysoul/assets/common/configs/action/catalog/core/actions/session_organize.toml` |
| **C5：配置目录、契约与门禁** | 更新 `standard`/`development` TOML、`infra/config/catalog/{context,execution,capabilities}.toml`、`presets.py`；更新 `AGENTS.md`、`docs/design/{context,session,llm}.md`、`docs/endpoint/` schema 与示例；运行 Full 测试与 `ty check` | `tinysoul/infra/config/**`、`tinysoul/assets/**`<br>`AGENTS.md`、`docs/design/**`、`docs/endpoint/**`<br>`tests/**` |

---

## 5. 合理性与可行性验证分析

1. **所有权与依赖方向严格合规**：
   - `infra/tokens.py` 仅做纯文本/JSON/字节估算（零上层依赖），`llm/protocol/tokens.py` 负责 `Message`/`ToolScope` 估算，`kernel/context` 与 `plugins` 单向依赖 `infra` 与 `llm`，100% 满足 `tests/test_architecture.py`；
   - 各插件继续在各自 TOML 节持有自身段预算配置，通过段注册描述符向 `ContextEngine` 声明 `SegmentBudgetSpec`，内核统一计算弹性池但绝不硬编码外围插件业务规则。
2. **边界极端情况闭环**：
   - **当批次加载保护**：`Home` 动态加载某篇较大文档时，本批次 `prepare/install` 后若触发自压缩，刚请求加载的 ref 标记为当批活跃，优先逐出更早历史加载项，绝不出现“刚 `load` 进来还没给模型看就被自己逐出”的死循环；
   - **比例之和不等于 1 的鲁棒性**：弹性池分配采用归一化权重 `share_i / Σ active_shares`（例如在 Memory Reflection 情景下不挂载 `User Session` 段时，`trace` 与 `home` 自动按 `0.60 : 0.15` 即 `80% : 20%` 平滑分摊弹性池，无需写多套配置！）；
   - **最佳努力（Best-Effort）不崩溃**：当某段连最低不可分割单元（如单条超长用户输入、受保护的当轮 `inspect` 页、`session:map` 最小头）都大于 `target_tokens` 时，`compress_to` 安全停在最低无损形态并返回实际压缩后大小，不抛出破坏性异常。
