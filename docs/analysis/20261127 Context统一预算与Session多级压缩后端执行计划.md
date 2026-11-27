# Context 统一预算与 Session 多级压缩后端执行计划

- 日期：2026-11-27
- 状态：`ready`（设计已明确，准备实施；须先完成 Workspace 后端交接，C1–C5 未实施）
- 初审基线：`712abf02`；准入复核：`6988824d`。本次变更仅为计划审阅。
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

本计划拟统一段预算的 token 估算、段级高低水位与全局压力回收，并重构 Session 的线性历史投影和解释图。针对的是 Trace/Home 缺少自预算、按形状排序而非按可缩内容回收、用 UTF-8 字节近似 token，以及历史结论与过程摘要的取舍失衡；不追求与供应商 tokenizer 完全相同。

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
   - 例如 7 万个三字节汉字，现实现仅正文就计约 21 万；按拟定确定性估算约 7 万。这个差异可由代码验证，真实供应商用量还取决于内容、模型和消息开销。
2. 同时，`context.max_window_tokens` 用 `tokens` 配置，而 `session.max_background_chars`、`context.trace_chunk_chars`、`home.max_skill_catalog_chars` 全用 `chars` 配置，用户在 Context 设置页难以直观换算各段占总窗口的真实比例。

### 1.2 段自预算缺失、全局 `RECLAIM` 顺位倒挂与空壳声明

1. **核心动态段缺乏自身高水位**：
   - `TurnTraceHeap`（`tinysoul/kernel/context/builtin/trace.py:541-584`）在日常 Cycle 追加时从不调用 `fold_overlays()` 或 `compact()`，导致几十轮前已读完的 `inspect` 8k 页面一直常驻热区，直到撞上全局窗口阈值；
   - `HeapSegment`（`tinysoul/kernel/context/background.py:195-215, 346-383`）在 Phase1 动态 `load_refs` 时无任何段上限检查，且逐出顺序按字典插入顺序而非最近使用（LRU）。
2. **全局回收顺序不合理**：`TurnSegments.reclaim`（`tinysoul/kernel/context/segments/collection.py:238-257`）按 `STATE → HEAP → STACK → MAP` 线性扣减，直到凑够 `required_chars` 即停止——导致 `Home Heap` 先被整篇清空，而后才轮到 `TurnTrace` 折叠旧临时页。
3. **空壳能力声明**：`MEMORY_SEGMENT`（`tinysoul/plugins/memory/background.py:75-80, 196-203`）声明了 `{SELECT, RECLAIM}`，但内部 `evictable_default_refs = ()` 且无可动态加载项，`reclaim()` 恒返回 0。
4. **状态投影不按渲染预算缩减**：`WorkingContext` 保留尚未显式移除的 todos；`JobsSegment` 只保留最近一份快照，不是不断追加快照，但该快照内的终态项仍整项渲染。Job 数量已有 `retained_capacity`，不同于展示 token 上限。

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

1. **纯基础设施标尺（`tinysoul/infra/tokens.py`，由先行 Workspace P1 首先交付文本估算，当前尚不存在）**：
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
    config_path: str | None = None         # owner 的可编辑字段入口；无入口时不伪造跳转

@dataclass(frozen=True)
class ResolvedSegmentBudget:
    mode: BudgetMode
    effective_max_tokens: int | None
    target_tokens: int | None
    pool_share: float | None
    global_reclaim: bool
    config_path: str | None

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
   - 在 generation 已编译的 `LLMConfig.tasks/models` 上取得主循环 Phase1/Phase2 所配置首选模型窗口的最小值。它是**配置参考值**，不冒充实际命中的模型。`llm/execution/task.py` 对每次尝试的窗口校验仍是权威；不为注入的 `LLMRunner`、fake 或 SDK 新增必须实现的第二套模型路由接口。
   - 经 `UserTurnBuilder`、`ReflectionBuilder` → `build_turn_context` → `ContextEngineBuilder` 显式注入数值，不把配置注册表传入 Kernel。配置参考值与 `context.max_window_tokens` 取已有值的最小值；仅两者都缺失的独立内核使用明确的参考默认值 `131072`，不报告为实测。
   - 全局触发线：`trigger_tokens = int(W_ref * context.compression_trigger_ratio)`（默认 `0.80`）；
   - 预留非段开销：`context.reserved_overhead_tokens`（默认 `16384` tokens，覆盖 Phase2 Tool Schemas、`TaskPrompt` 临时挂载 Skill 与模型输出预留的常规空间）。
2. **固定基线扣除与比例池分配**：
   - `baseline_used_tokens` 按当前已安装固定段与不可压基线**渲染后的 token 估算实占**扣除，不为未用的固定额度预留空间。`workspace_archive` 若安装也须入账，Home 受保护基线只扣一次。段可切换 fixed 时按本次模式核算，不按 owner 名硬编码；下一预算边界按更新后的投影重算。
   - 可用弹性池：`elastic_pool_tokens = max(0, trigger_tokens - reserved_overhead_tokens - baseline_used_tokens)`；
   - 对每个 `POOL_SHARE` 段 $i$（权重归一化 `w_i = share_i / Σ share`）：
     `effective_max_i = clamp(int(elastic_pool_tokens * w_i), min_tokens_i, max_tokens_i)`
     `target_i = int(effective_max_i * target_ratio_i)`。

#### 2.2.3 两级触发逻辑与 Cycle 边界保护时序

1. **第一级：段自身高水位触发（Cycle 边界常态主力，保护同轮编辑与缓存命中）**
   - **唯一的常规调度点**：Turn 段 open、preparation 的首批信号安装后，第一次以及以后每次进入 `CycleRunner.run`，在起始 `_boundary(cycle_scope)` 结算且允许继续后、构造 Phase1 请求前协调。不要既在 Phase3 末尾又在下轮开头执行；不能挂到通用 `_boundary` 本体（Phase 间也调用），也不能只靠 Phase3（Phase1/2 局部失败可能提前结束 Cycle）。
   - 若 `segment.countable_tokens() > budget.effective_max_tokens`，调用 `segment.compress_to(budget.target_tokens)`；保护/最小可读单位不足以继续时报告实际占用，不吞掉 owner 的真实契约/存储错误。
   - **为什么不在同一 Cycle 的 Phase1 与 Phase2 之间自压缩 `TurnTrace`**：
     1. 上一轮 Phase3 的 Inspect 页仍受 `_protected_overlays` 保护；只有携带该页的主循环 Phase1/2 请求取得响应才可解除，容量拒绝、SDK 浏览及 Action 内模型调用不算。解除不是删除。在无额外全局压力的常规路径，两阶段间不主动折旧页，Phase2 可用原文生成 `old_text`。已解除的页在**确有压力**时可折叠，不承诺跨两次调用驻留，也不承诺下一轮必折。
     2. 这样减少不必要的前缀变化，不保证供应商缓存命中。Home 加载在固定批次的候选视图中计算 LRU 和当批保护，整批成功才 install；render/Overview 不刷新 LRU。保护下确实超额时明确报告，不静默反复加载/逐出。
   - **固定小增长段特例**：像 `plan`、`jobs`、`connections` 这类配置为 `mode = FIXED, global_reclaim = False, target_ratio = 0.65~0.70` 的段，**完全不会被全局窗口压力打扰，但当自身在超长 Turn 中增长触及 `max_tokens` 时，会在 Cycle 边界自动按 `target_ratio` 将已完结历史项折叠回落**。
2. **第二级：全局窗口阈值协同触发（`reclaim_pressure` 保险阀）**
   - 当 LLM 执行边界因某候选模型窗口较小（如降级到 64k 备选模型）、超大 MCP 工具集或分词偏差抛出 `ModelContextPressureError(usage)` 时：
   - 计算该候选模型的目标总消息容量：
     `model_target_tokens = max(0, int(usage.effective_window_tokens * context.compression_target_ratio) - usage.estimate.non_message_tokens - usage.reserved_output_tokens)`；
   - 扣除所有 `global_reclaim = False` 段与 `home` 受保护基线的当前占用 `exempt_tokens`，得到本次全局回收后的可用弹性目标池 `remaining_pool = max(0, model_target_tokens - exempt_tokens)`；
   - 对所有 **`global_reclaim = True`** 的段（默认即 `trace`、`session`、`home` 动态区），计算协同目标：
     以**解析后额度**的 `target_tokens` 为段的预期值，不是每次把 `current_countable × ratio` 再打一次折。比例段目标取当前值、段目标、按剩余池分配的目标三者较小值；应用配置下限时不反向扩大已更小的段。`min_tokens` 是常规分配保底，不是强令填满，也不能使保护中的事实消失。全固定/无 share、cap 生效及池小于各段保底之和都要有测试；总目标不可满足时允许实际超额，不做无限再分配。
   - 必须扣除本次实际请求的不可回收项（含 TaskPrompt/局部 Skill；它们是 **message** tokens，不是 tools），不在这一层再扣估算的常规 reserve；不要把 fixed 且 `global_reclaim=True` 的段既扣为全局豁免又参与加权。只对已安装且本次请求实际能变小的内容计算进展。
   - 用渲染前后的同口径 token 差区分 `RECOVERED`/`NO_PROGRESS`；后者沿现有 Trap 结束作用域，不凭 `changed`、字符串长度或压缩调用次数重复尝试。保留 `ContextPressureTrapHandler` 的可重放 Module/Phase 目标，重新组装消息，不直接重放已提交 Action 或旧 MessageStack。

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
| `workspace_archive`（Memory Reflection） | Workspace | 使用 Workspace 已配置的固定模型投影预算 | `1.0` | `False` | 仅计实际安装的来源日只读投影；保留 `workspace_archive:<day>` 分页导航。活动工作台和归档背景是两个真实段，不互作替身 |
| `jobs` | `jobs.toml` | `FIXED`（`max_tokens = 1536`） | `0.65` | `False` | 按 `JobState.terminal` 分组，保留 starting/running/waiting_input/stopping 和完整待答；succeeded/failed/cancelled 可折为带真实状态、ref 的摘要。只缩展示，不删除 JobRegistry 内的结果 |
| `connections` | `subagent.toml` | `FIXED`（`max_tokens = 1024`） | `0.70` | `False` | 使用 owner 的 ready/busy/unavailable、active_job_id、turn_id；不发明 idle 协议值、不关闭连接、不隐藏活动 Job |

> **上游条件**：Workspace 后端尚未实施。待其交付 `workspace.max_context_tokens` 与 `infra/tokens.py` 后，C2/C5 读取 Workspace 的有效配置（非硬编码 3000），不再实现一次目录折叠。登记项以各 profile 实际安装集合为准。

---

### 2.4 `Session` 深度重构：动作分级、四级语义冰山与 `SessionMap` v2

#### 2.4.1 历史交互中的四类语义分级（`plugins/session/views/interaction.py` & `background.py`）

不改变 `SessionTurnRecord` 落盘的不可变事实。`completion.project_action_record` 保存请求和 canonical result（foldable 结果可能只有回忆和引用），没有保存的原始页面不能由 Inspect 还原；中断事实不伪造结果。分级只改变 Background 视图，不能删减共享 `project_interactions` 供精确 Inspect/Search 使用的事实。

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
     - **边的 `source_refs` 是补充证据，可省略或传 `[]`**，包括两端都是解释节点时。Organize 接受两种输入，v2 写出和返回统一为空列表；有值时仍逐项解析、去重校验并遵守 32 条上限。边的两个端点照常校验；节点自身的来源要求不变。边的 `body` 独立可空，不用补一句空泛说明换取通过。
     - 事实端点不必在边上重抄。纯节点边没有独立证据时，Inspect 可沿端点查看节点各自的出处，不把它们复制成边的直接证据。像 `revises`、`contradicts` 这样的判断若有能说明关系的原话或行动，指导模型优先附具体 ref，但不按关系种类强制条数。所有语义边仍是可修订的解释，不是已验证的事实。
   - `SessionView._unclassified()` 更新为：凡不在任何 `ACTIVE` `THREAD` 节点的 `turn_refs` 中的已完成 Turn 即为未归类轮次。
2. **模型可见 `session_map` 投影与配额协同**：
   - **消除双端重复**：`session_map` 清晰分为 `Topics & Notes` 与 `Relations` 两段，每条活跃 `SemanticEdge` 全局只渲染一次：
     - 节点展开态：`[thread] 标题 (session:node/...) | turns: 1, 2, 5 | body... | evidence: ...`
     - 节点折叠态：`[thread] 标题 (session:node/...) | turns: 1, 2, 5 [folded — inspect node]`
     - 关系行：`session:node/1 --[revises]--> session:node/2: 简短说明 (session:edge/1)`
   - **冷启动友好头**：即使尚未调用 `core.session.organize`（无人工节点），`session_map` 头部也清晰列出 `Completed turns: N | Unclassified: N (inspect session:history or session:map)`；
   - **弹性共享预算**：地图区最多使用当前 Session 目标预算的 `30%`（节点过多时按关联轮次新旧将旧节点从展开态降为折叠态）；地图未用完的预算 100% 留给下方线性历史。
3. **同步 `core.session.organize` Action 定义与指导**：
   - 更新 `tinysoul/assets/common/configs/action/catalog/core/actions/session_organize.toml` 与对应技能说明，反映 `turn_refs`、无 `covers` 边及轻量 `edge.body` 协议。

---

### 2.5 Context Overview 监控契约扩展（对接前端 Delta 风格视图）

修改 `ContextEngine.installed_overview()` 及既有 `GET /v2/requests/{request_id}/context` 响应结构（保留 `chars` 和 `image_bytes` 作为辅助计量，不新增按 turn_id 的路由；返回体仍标识正式 `turn_id`）：

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
   `used_message_tokens` 为当下已安装段的估算；`reserved_overhead_tokens` 是预算而非已用量。当前 `ModelContextUsage` 是 LLM 尝试的局部对象，没有按 Turn 保存的“最近一次真实模型调用”投影；没有独立的已绑定数据源就不发 `last_model_call`，不读 Observation 反推，不混加上次工具估算与本次段用量。
2. **`segments[]` 每项新增字段**：
   - `"tokens": int`（该段总渲染 token 估算值）
   - `"budget"`: `{ "mode": "fixed" | "pool_share" | "exempt_unbounded", "effective_max_tokens": int | null, "target_tokens": int | null, "pool_share": float | null, "target_ratio": float | null, "global_reclaim": bool, "config_path": str | null }`
   - `"compaction"`: `{ "compressed": bool, "summary": str, "baseline_tokens": int | null, "dynamic_tokens": int | null }`
3. `tinysoul/gateway/endpoint/http/schemas/responses.py` 的 `ContextOverviewResponse` / `ContextSegmentResponse` 是实际响应类型；同步 `measurement`、schema、`docs/endpoint/inspection.md` 和示例，走 `tests/gateway/endpoint/test_contracts.py` 的真实 owner 交接测试。字段都来自已安装视图；无活动 Context 仍按现有不可用语义，不创建会话服务于设置页。

---

## 3. 配置文件变更清单预览

1. **`context.toml`（`standard` & `development`）**：
   - 保留：`system_text`、`journal`、`max_window_tokens`、`max_image_bytes`、`compression_trigger_ratio = 0.8`、`compression_target_ratio = 0.5`、`trace_branch_factor = 4`、`trace_min_hot_entries = 2`、`max_trace_inspect_chars = 8192`
   - 新增/替换：
     - `reserved_overhead_tokens = 16384`
     - `plan_max_tokens = 2048`、`plan_target_ratio = 0.70`
     - `[context.trace]`：`mode = "pool_share"`、`pool_share = 0.60`、`min_tokens = 8192`、`max_tokens = 49152`、`target_ratio = 0.60`、`chunk_tokens = 3072`（替换原 `trace_chunk_chars = 12288`，不设扁平别名）
2. **`session.toml`**：
   - 保留：`root`、`max_inspect_chars = 8192`
   - 替换 `max_background_chars` 为 `[session.context]`：`mode = "pool_share"`、`pool_share = 0.25`、`min_tokens = 4096`、`max_tokens = 24576`、`target_ratio = 0.65`
3. **`home.toml`**：
   - `max_skill_catalog_tokens = 2048`（替换原 `max_skill_catalog_chars = 8192`；`max_read_chars`/`max_write_chars` 保持字符单位不变）
   - 新增动态背景预算：`[home.context]`：`mode = "pool_share"`、`pool_share = 0.15`、`min_tokens = 4096`、`max_tokens = 16384`、`target_ratio = 0.65`
4. **`workspace.toml`、`jobs.toml`、`capabilities/subagent.toml`**：
   - `workspace.max_context_tokens = 3000`（由先行 Workspace 计划交付，本计划读取该值）
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
| **C1：LLM 协议 Token 估算对齐** | 使用 Workspace P1 的 `infra/tokens.py`；LLM 装配提供参考窗口，协议负责 `Message`/`ToolScope` 估算；校验候选窗口及中英文/代码/工具开销 | `tinysoul/llm/protocol/tokens.py`、`llm/execution/{context_window,task}.py`、`llm/config/types.py`、generation 装配 |
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
   - **按实际安装分配**：只在实际的 `pool_share` 集合内归一化权重；集合为空则不除。`SessionPlugin.build_generation` 在 Memory Reflection 也登记只读来源日 Session，不能假定该情景没有 Session；它还会安装 `workspace_archive`。
   - **最佳努力（Best-Effort）不崩溃**：当某段连最低不可分割单元（如单条超长用户输入、受保护的当轮 `inspect` 页、`session:map` 最小头）都大于 `target_tokens` 时，`compress_to` 安全停在最低无损形态并返回实际压缩后大小，不抛出破坏性异常。

## 6. 实施准入与验收口径

| 决策 | 实施与验收 |
| --- | --- |
| D1 固定段按实占扣池 | 例如固定上限 8000、当前占 1000，只扣 1000；在不触及零下限时，若下个边界占用增至 2500，其他量不变，弹性池相应减少 1500。独立预留的工具/任务开销不计为已用。全局压力仍按当次完整请求处理。 |
| D2 可追溯，不强制每条边单独举证 | 对事实端点、两个有来源的解释节点，均测试无补充 ref 可提交并按解释披露；另测显式来源可读、无效来源或未知端点导致整批不提交。端点修订不自动重写边或升级其证据，节点撤回仍须按现有规则处理活动关系。C4 同步 Organize 的 schema、`SessionMap.apply` 与 `docs/design/session.md`：区分节点来源、边端点与边的直接证据，不新增置信度或证明状态字段。 |

两项设计已收敛，`ready` 是设计准入，不代表实现完成。开始 C1 前核对 Workspace 后端已交付文本估算函数与有效 Workspace 配置；不并行创建另一套标尺。完成条件仍是 C1–C5、真实 Endpoint 交接及本地门禁。

### 实施与验收补充

1. **计量与压力链**：字节冒充 tokens 的问题属实，3～4 倍不是对所有模型/文本的实测结论。新标尺是确定性估算，不是真 tokenizer 或硬上界；保留消息包装、工具选择、回放、图片与预留输出，图像字节硬限独立。`kernel/loop/pressure.py`、`agent/user/pressure.py`、`plugins/reflection/turn/runtime.py`、`context/{compress,segments/collection}.py` 和 Trace 报告要一起去掉 token→char 回算；字节型拒绝不能靠折几行文本声称恢复。`fixed + global_reclaim` 的段按自身目标而非不存在的 share 压缩，先用其压后实占计算留给比例段的空间。全局下限、超额、无进展和 fallback 小模型分别测试。
2. **保护投影，不丢事实**：Memory 移除 SELECT/RECLAIM 不等于移除 current/latest/target。`ContextEngine.background_refs()` 目前直接取 `selection_view().loaded`；须把“已安装的事实引用”与“允许模型加载/逐出的控制选项”分开，保留 refresh、`seal().resolved_references`、Session 来源日和 Overview 读口，不让 protected refs 从 completion 消失。Plan、Jobs、Connections 压缩只作用于可见视图；Plan 的全部 patch 先投影/校验、全部可安装才提交，不从折叠计数重建事实。终态 Job 受现有 retained capacity 限制，不能宣称无限积累；无真实 Trace 引用时不写“可在 Trace 恢复全文”。
3. **Session 边界**：`turn_refs` 是同日、在固定 prior-Turn 集合内存在的完整 Turn 根，不是 source_refs：接受的本轮 input/已结算 Action 可作证据，不能作历史成员。NOTE 如给出关联轮次不算归类；共用成员不重复正文，撤回按活动 THREAD 重算。`apply` 原子校验本地 key、事实与关系；更新存储严格解析/空图创建、Organize schema/Skill、inspect/query/search、活动与归档读口。L0/L1 保留成对问答和真实失败，L2/L3 只报事实与可读入口；同一 Turn 以既有可见档位为上限，不因 organize 刷新重新展开旧页。地图预算放不下时优先留 `session:history/topics/unclassified` 等导航，不承诺把全部成员列表常驻。不可变记录与 v1 解释图不是同一工件；旧 map/preset 不自动丢弃、迁移或用空图替代。
4. **交接与门禁**：将主配置字段路径（如 `jobs.max_context_tokens`）交给 Endpoint/UI 映射设置页，不让 Kernel 协议依赖前端 `SettingsPageId`；Home 动态分子只与动态额度比较，总占用另列。三 profile 真装配验证预算；SDK/HTTP 只读 Overview 不触盘、不触发压缩。更新两套模板、catalog、预设 capture/apply 与实际契约样例。用 `tests/llm/execution/test_context_capacity.py`、`tests/kernel/{context,loop}`、`tests/plugins/{home,memory,session}` 做 owner/保护时序回归，用 `--suite full tests/gateway/endpoint/test_contracts.py` 核对真实交接，再跑默认 Fast、`uv run --locked --extra dev python scripts/test.py --suite full` 和 `uv run --locked --extra dev ty check`。审阅基线的 128 项聚焦测试不是新算法通过的证据。
