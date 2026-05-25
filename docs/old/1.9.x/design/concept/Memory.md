# TinySoul 记忆-会话-自我改善架构设计分析

> **分析者**: Claw (OpenClaw Agent)
> **日期**: 2026-05-22
> **触发**: graygoo 关于 TinySoul 架构升级的探讨
> **状态**: 概念验证 / 架构提案

---

## 一、设计背景

graygoo 提出将 TinySoul 从单纯的 query-loop 循环入口，升级为具有**记忆系统、会话管理和自我改善能力**的智能体架构。核心设计目标：

1. **记忆层**: 命题逻辑/知识图谱的符号系统 + 向量检索的情景记忆
2. **会话层**: 当天会话的语义地图（基于命题逻辑建模），划分和关联每轮 query-loop 的走向
3. **处理层**: 每轮 query-loop 前预处理（选择性注入相关记忆），每天后处理（压缩沉淀到长期记忆）

---

## 二、整体架构：三层双轨

```
┌─────────────────────────────────────────┐
│  Layer 3: 处理层 (Processing)            │
│  ├─ 预处理：语义地图子图 + 相关记忆 →     │
│  │   选择性注入 query-loop 上下文        │
│  └─ 后处理：当天语义地图 → 压缩沉淀 →    │
│     命题入知识图谱 / 经验入向量库         │
└─────────────────────────────────────────┘
            ↑↓ 每天交换
┌─────────────────────────────────────────┐
│  Layer 2: 会话层 (Session)               │
│  当天语义地图 = 命题逻辑 DAG             │
│  节点：query-loop 轮次                   │
│  边：enables / refutes / extends /       │
│      resolves / parallel_to              │
│  （基于命题逻辑，非时间顺序）              │
└─────────────────────────────────────────┘
            ↑↓ 实时读写
┌─────────────────────────────────────────┐
│  Layer 1: 记忆层 (Memory)                │
│  ├─ 符号轨道：命题逻辑 / 知识图谱          │
│  │   （规则、事实、约束、本体关系）         │
│  └─ 向量轨道：情景记忆                    │
│     （经验案例、历史对话、失败记录）        │
└─────────────────────────────────────────┘
```

---

## 三、各层详细设计

### 3.1 记忆层：命题逻辑知识系统

**核心区别：命题逻辑 ≠ 简单知识图谱**

| 维度 | 传统 KG (HippoRAG) | 命题逻辑知识系统 |
|------|-------------------|-----------------|
| 基本单元 | 实体 + 关系三元组 | **命题**（可判断真假的陈述） |
| 关系类型 | 预设类型（works_at, located_in） | **逻辑连接词**（∧, ∨, →, ¬） |
| 查询方式 | 图遍历 / 向量相似 | **逻辑推理**（前向/后向链） |
| 更新机制 | 插入/删除三元组 | **信念修正**（冲突处理） |
| 表达能力 | 描述逻辑 (OWL) | 一阶逻辑 / Datalog |

**sil_cal 中的具体例子**：

```
传统 KG 存储：
(waveform_A, has_feature, high_slope)
(waveform_A, related_to, case_2024_05)

命题逻辑系统存储：
Feature(waveform_A, slope, >0.5)  ← 具体命题
∀w: (Slope(w, >0.5) ∧ Amplitude(w, >2.0)) → Candidate(w, frontal_suppression)  ← 规则
¬(Threshold(sensor_X, t1) = Threshold(sensor_X, t2)) → RequiresRetest(sensor_X)  ← 约束
```

**为什么命题逻辑更适合 Agent 记忆**：

1. **规则本身就是命题**：标定策略 `low_gain_trigger` 的触发条件可以写成逻辑规则
2. **支持反事实推理**："如果当时选择了 `waveform_diff` 而不是 `accurate_trigger`，结果会怎样？"
3. **信念修正**：当专家审核发现某条规则错误时，系统处理与该规则推导出的所有命题的冲突

---

### 3.2 会话层：语义地图 = 命题逻辑 DAG

**核心创新：从线性时间轴到有向无环图**

当前所有 Agent 框架（包括 TinySoul）都把会话当作线性时间轴：

```
Q1(choose) → A1(take) → S1(update) → Q2(choose) → A2(take) → S2(update) → ...
```

语义地图把它变成了**有向无环图（DAG）**，边是**命题关系**而非时间顺序。

#### 3.2.1 节点设计

```python
class SemanticNode:
    node_id: str           # 如 "loop_001"
    timestamp: datetime    # 物理时间（辅助，非主键）
    
    # 核心：这一轮的命题内容
    propositions: List[Proposition]
    # 如：
    #   Proposition("ActionChosen", "create_file", confidence=0.95)
    #   Proposition("StateDelta", "todo_list.append('analyze_waveform')")
    #   Proposition("ConstraintSatisfied", "file_size < 1MB")
    
    # 执行结果
    outcome: Outcome       # SUCCESS / FAILURE / PENDING / REJECTED_BY_VERIFIER
    
    # 与本轮相关的记忆引用
    memory_refs: List[MemoryRef]  # 指向长期记忆的指针
```

#### 3.2.2 边设计（命题关系）

| 边类型 | 逻辑形式 | 语义 | sil_cal 例子 |
|-------|---------|------|------------|
| **enables** | Success(A) → Possible(B) | A 成功使 B 成为可能 | 波形分析完成 → 阈值调整成为可能 |
| **refutes** | Result(A) ∧ Premise(B) → ⊥ | A 的结果与 B 的前提矛盾 | 波形分析显示高频噪声 → 否定"直接使用原始波形"策略 |
| **extends** | Goal(B) ⊂ Goal(A) | B 是对 A 的深化 | 从"分析波形"深化为"提取 onset_slope 特征" |
| **resolves** | Failure(A) ∧ Success(B) → Resolved(A) | B 解决了 A 的失败 | 第一次阈值调整失败 → 第二次用 StaticDynamicAdjuster 解决 |
| **parallel_to** | Independent(A, B) | A 和 B 可并行 | 左侧传感器标定 ∥ 右侧传感器标定 |
| **depends_on** | Necessary(A, B) | B 依赖 A 的前提 | 阈值验证依赖 gRPC 仿真连接可用 |

**关键洞察**：这些边从 query-loop 的三层 Prompt 输出中**自动提取**：

- `choose_action` 输出 `action_id` + `reasoning` → 解析 reasoning 中的命题，建立与前序节点的 `enables`/`extends` 关系
- `take_action` 输出执行结果 → 建立 `SUCCESS`/`FAILURE` 标记
- `update_state` 输出 state_delta → 建立与 state 命题的 `extends` 关系

---

### 3.3 处理层：预处理 + 后处理

#### 3.3.1 预处理：结构化上下文包（SCP）

CALMem 的 MOIM 注入的是**文本块**（情景记忆片段或 key-value 事实）。我们的设计更进一步：注入的是**语义地图的子图 + 相关命题 + 相关规则**。

```python
class ContextPackage:
    # 1. 当前会话语义地图的可达子图
    #    从当前节点反向追踪 enables/depends_on 边，
    #    构建"为什么走到这里"的因果链
    causal_chain: SubGraph  # 通常 3-5 个节点
    
    # 2. 当前活跃并行分支
    #    追踪 parallel_to 边，了解正在进行的其他任务
    parallel_branches: List[SubGraph]
    
    # 3. 相关历史经验（从向量轨道检索）
    #    基于当前命题的嵌入相似度检索
    relevant_cases: List[MemoryChunk]
    
    # 4. 相关规则/约束（从命题逻辑系统检索）
    #    基于当前目标命题的逻辑推理
    applicable_rules: List[Proposition]
    
    # 5. 信念冲突预警（从命题逻辑系统检测）
    #    检查当前命题是否与已有知识冲突
    conflicts: List[ConflictAlert]
```

**注入策略（MOIM 扩展）**：

| 上下文填充率 $r$ | 注入内容 | 原因 |
|-----------------|---------|------|
| $r < 0.50$ | 完整 SCP（子图 + 并行分支 + 案例 + 规则 + 冲突预警） | 上下文充裕，保留完整推理结构 |
| $0.50 < r < 0.70$ | 精简 SCP（因果链 + 规则 + 冲突预警） | 裁剪经验案例和并行分支 |
| $0.70 < r < 0.85$ | 极简 SCP（当前节点命题 + 直接前驱 + 关键规则） | 仅保留推理骨架 |
| $r > 0.85$ | **仅注入冲突预警** | 上下文极度紧张时，只保留"不要犯错"的底线 |

**与 CALMem 的关键区别**：

- CALMem 注入的是"**过去的对话说了什么**"（文本块）
- 我们的 SCP 注入的是"**为什么走到这里**"（因果链）+ "**现在该注意什么**"（规则 + 冲突预警）

#### 3.3.2 后处理：命题压缩算法

每天结束时，当天语义地图（DAG，可能 50-200 个节点）经过命题压缩：

```
当天语义地图
    ↓ 命题压缩算法
┌─────────────────────────────────────────┐
│ 高频命题 → 符号轨道（命题逻辑系统）      │
│   - 新规则发现："在 X 条件下 Y 策略有效" │
│   - 约束更新："sensor_A 阈值上限 = 2.5"  │
│   - 本体扩展：新增 Entity "StaticDynamicAdjuster" │
├─────────────────────────────────────────┤
│ 经验案例 → 向量轨道（情景记忆）          │
│   - 成功/失败案例的嵌入向量              │
│   - 保留原始命题作为 metadata             │
├─────────────────────────────────────────┤
│ 异常模式 → 专项追踪                       │
│   - 连续 refutes 边（频繁失败模式）        │
│   - 未解决的 depends_on（阻塞任务）        │
└─────────────────────────────────────────┘
```

**命题压缩算法示例**：

```
输入：当天语义地图中的大量具体命题
      "Threshold(sensor_X, 2026-05-22, loop_003) = 1.05"
      "Threshold(sensor_X, 2026-05-22, loop_007) = 1.07"
      "Threshold(sensor_X, 2026-05-22, loop_012) = 1.06"

输出：泛化规则
      ∀t: Date(t) = 2026-05-22 → ThresholdRange(sensor_X, t) ∈ [1.05, 1.07]
      （经专家审核后提升为永久规则）
```

---

## 四、与前沿工作的关系

### 4.1 与 CALMem 的关系：从"双记忆"到"记忆+推理结构"

| 你的设计 | CALMem | 超越之处 |
|---------|--------|---------|
| 符号 KG + 向量双记忆 | CALMem 语义/情景双记忆 | 用**命题逻辑**替代简单 key-value，支持推理 |
| 语义地图（DAG） | LangGraph / 非时间序列上下文处理 | 边是**命题关系**而非简单"next"，支持反事实追踪 |
| 选择性注入 | CALMem MOIM 预算机制 | 注入的是**结构化子图**而非文本块，保留推理结构 |
| 后处理沉淀 | HippoRAG 记忆索引 + 每日日志 | 用**命题压缩**替代简单总结，保留逻辑关系 |

### 4.2 与 Runtime Patterns (SDB) 的关系

Runtime Patterns 的 SDB 在**动作执行前**验证提议。我们的语义地图可以在**推理过程中**验证逻辑一致性：

```
Runtime Patterns SDB:
  LLM 提议 "将阈值设为 2.5" → Verifier 检查 2.5 ∈ [0, 5] → 提交/拒绝

我们的命题逻辑验证:
  LLM 推理 "因为上一轮发现 slope > 0.5，所以应该用 frontal_suppression"
  → 检查语义地图：上一轮节点确实有 Proposition("Slope", ">0.5")
  → 检查规则库：Slope > 0.5 → Candidate(frontal_suppression) 是否成立？
  → 检查冲突：frontal_suppression 是否与当前已选策略矛盾？
  → 通过/拒绝/要求澄清
```

### 4.3 与 HippoRAG 的关系：从"图检索"到"图推理"

HippoRAG 用 KG + PPR 做**检索**（找到相关 passage）。我们的命题逻辑系统用**推理**（推导新命题、检测冲突、泛化规则）。

---

## 五、对 sil_cal 智能标定 Agent 的直接启发

### 5.1 SDB 映射到 sil_cal 标定流程

```
┌─────────────────────────────────────────┐
│  提议者 (Proposer)                      │
│  LLM Agent 分析波形特征，提议参数调整     │
│  "建议将 frontal_suppression 阈值        │
│   从 1.02 提高到 1.05"                   │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  验证者 (Verifier) — 确定性检查层          │
│  ① 物理约束检查：1.05 是否在 [0.5, 2.0]?  │
│  ② 步长约束：|1.05-1.02| ≥ 0.01?        │
│  ③ 历史冲突检查：上次调整为同方向？       │
│     （参考语义记忆 recall_facts）         │
│  ④ gRPC 仿真验证：新参数通过 50 组波形？  │
└──────────────┬──────────────────────────┘
               ↓
           ┌───┴───┐
      通过 ↓       ↓ 拒绝
    ┌─────────┐  ┌─────────────────────┐
    │ 提交    │  │ 拒绝信号            │
    │ ① 更新语义记忆中的阈值配置        │
    │ ② 写入情景记忆：调整决策过程       │
    │ ③ 记录到 evaluation 实体          │
    │         │  │ "拒绝原因：步长      │
    │         │  │  精度不足（0.03 <   │
    │         │  │  最小步长 0.05）；  │
    │         │  │  建议直接跳到 1.07" │
    └─────────┘  └─────────────────────┘
```

### 5.2 CALMem 双记忆映射到 sil_cal 本体框架

| sil_cal 实体 | CALMem 记忆类型 | 存储形式 | 检索方式 |
|-------------|----------------|---------|---------|
| **Waveform** (波形特征) | 情景记忆 | 向量嵌入 (128-dim 联合特征) | 模糊语义检索 —— "找与这次波形相似的失败案例" |
| **Path** (标定路径) | 情景记忆 | 时间序列分块 | 语义检索 —— "上次用 waveform_diff 路径的结果" |
| **Threshold** (阈值参数) | **语义记忆** | key-value (sensor_id, threshold_name) → value | 精确匹配 —— "X 传感器 Y 阈值的当前值" |
| **Rule** (标定规则) | **语义记忆** | category="rule", key=rule_name, value=rule_content | 精确匹配 + 类别过滤 |
| **Evaluation** (评估结果) | 情景记忆 | 带时间戳的实验记录分块 | 语义检索 —— "过去一周内失败的标定尝试" |

### 5.3 MOIM 预算模型映射到 sil_cal 标定阶段

| 标定阶段 | 上下文填充率 $r$ | MOIM 策略 | 注入内容 |
|---------|-----------------|---------|---------|
| **初始化** (分析目标定义) | $r < 0.30$ | 全量注入 | 传感器规格 + 平台差异表 + 历史相似项目 |
| **波形分析** (特征提取) | $0.30 < r < 0.60$ | 中等注入 | 当前波形特征 + 相关失败案例 |
| **参数调整** (阈值优化) | $0.60 < r < 0.80$ | 轻量注入 | 仅语义记忆：当前阈值 + 约束规则 |
| **验证阶段** (gRPC 仿真) | $r > 0.80$ | **抑制情景记忆** | 仅语义记忆：验证指标定义 + 通过阈值 |

**关键启示**：在标定验证阶段（上下文被大量仿真结果填满时），不应再注入历史案例的模糊检索结果 —— 这会干扰模型对当前验证结果的精确判断。此时只应保留**精确的约束规则**（语义记忆）。

---

## 六、对 TinySoul 架构改进的启发

### 6.1 SDB 化 QueryLoop

TinySoul 当前的 QueryLoop 三层 Prompt 架构已经蕴含 SDB 思想，但可以更明确地结构化：

```
当前 TinySoul:
choose_action → take_action → update_state

SDB 化后的 TinySoul:
┌─────────────────────────────────────────┐
│  choose_action = 提议者 (Proposer)      │
│  LLM 提议下一个 Action                   │
│  输出：action_id + 参数                  │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  take_action = 验证者 (Verifier) + 提交   │
│  ① 验证 action 参数是否满足 contract    │
│  ② 执行 action_handler                  │
│  ③ 如果失败：写入 loop_error_list       │
│     （拒绝信号返回给 update_state）      │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  update_state = 提交 (Commit)           │
│  ① 更新 todo_list / milestone_list       │
│  ② 更新 ongoing_action_list             │
│  ③ 记录 action_record_list              │
│  所有更新必须通过确定性代码执行           │
└─────────────────────────────────────────┘
```

**改进建议**：
1. **明确的拒绝信号格式**：当前 `loop_error_list` 只是字符串列表，应改为结构化对象（`{error_type, reason, suggested_fix, severity}`），让 LLM 在下一轮能据此调整行为。
2. **验证者前置**：在 `choose_action` 输出后、`take_action` 执行前，增加一个**确定性验证层**（类似于 Pydantic schema validation），而非依赖 LLM 自行遵守约束。

### 6.2 CALMem 双记忆化 State 管理

TinySoul 当前的 State 包含：
- `todo_list` —— 待办任务
- `milestone_list` —— 里程碑
- `action_record_list` —— 动作记录
- `ongoing_action_list` —— 进行中动作
- `loop_error_list` —— 错误记录

这些可以映射到 CALMem 双记忆：

| 当前 State 字段 | 类型 | CALMem 映射 | 改进建议 |
|---------------|------|------------|---------|
| `todo_list` | 结构化列表 | **语义记忆** (category="todo") | key="todo_001", value="完成波形分析"，支持 upsert |
| `milestone_list` | 结构化列表 | **语义记忆** (category="milestone") | 精确检索当前阶段 |
| `action_record_list` | 文本列表 | **情景记忆** (分块嵌入) | 模糊检索"上次类似的操作" |
| `ongoing_action_list` | 结构化列表 | **语义记忆** (category="ongoing") | 精确检索当前活跃任务 |
| `loop_error_list` | 文本列表 | **情景记忆** (分块嵌入) | 模糊检索"以前犯过的类似错误" |

**新增 MOIM 注入器**：在每次 QueryLoop 迭代前，根据当前上下文填充率动态注入：
- 低填充率：注入相关历史 action records + 相关错误案例
- 高填充率：仅注入当前 todo + milestone（语义记忆）

### 6.3 P4 监督者+关卡的具体实现

TinySoul 当前的错误处理是**捕获异常 → 记录错误 → 继续执行**。可以升级为 P4 模式：

```
当前：try-catch → loop_error_list.append(error) → continue

改进：
┌─────────────────────────────────────────┐
│  P4 监督者+关卡层                        │
│  ─────────────────────────────────────  │
│  ① 关卡 (Gate): 错误类型分类            │
│     - 可恢复错误 (API 超时) → 指数退避重试 │
│     - 结构性错误 (schema 不匹配) → 拒绝信号 │
│     - 安全级错误 (文件系统越界) → kill switch │
│  ② 监督者 (Supervisor): 一对一重启       │
│     - action_handler 崩溃 → 重启新实例   │
│     - 连续 3 次同类错误 → 升级 (escalation) │
│  ③ 审计日志 (Audit Log):                 │
│     - 所有错误写入情景记忆 + 时间戳       │
│     - 支持事后追溯和模式识别              │
└─────────────────────────────────────────┘
```

---

## 七、技术实现建议（关键数据结构）

### 7.1 命题表示

```python
from typing import List, Optional, Dict
from pydantic import BaseModel
from enum import Enum

class PropositionType(str, Enum):
    FACT = "fact"           # 原子事实
    RULE = "rule"           # 条件规则 (if-then)
    CONSTRAINT = "constraint"  # 硬性约束
    GOAL = "goal"           # 当前目标
    BELIEF = "belief"       # 当前信念（可能随证据变化）

class Proposition(BaseModel):
    id: str
    type: PropositionType
    # 谓词逻辑形式：Predicate(subject, ...args)
    predicate: str          # 如 "Threshold", "Slope", "Enables"
    subject: str            # 主语
    args: Dict[str, any]    # 其他参数
    # 元数据
    confidence: float       # [0, 1]
    source: str             # "llm_inference" / "expert_input" / "derived"
    derived_from: Optional[List[str]]  # 父命题 ID（用于血统追踪）
```

### 7.2 语义地图（DAG）

```python
class SemanticNode(BaseModel):
    id: str
    loop_iteration: int    # 对应第几轮 query-loop
    
    # 这一轮的命题集合
    propositions: List[Proposition]
    
    # 执行结果
    action_taken: Optional[str]
    outcome: Optional[str]  # SUCCESS / FAILURE / REJECTED / PENDING
    
    # 记忆引用
    memory_refs: List[str]  # 指向长期记忆的 ID

class SemanticEdge(BaseModel):
    source: str            # 源节点 ID
    target: str            # 目标节点 ID
    relation: str          # enables / refutes / extends / resolves / parallel_to / depends_on
    # 边的命题基础（为什么有这个关系）
    supporting_proposition: Optional[Proposition]
    strength: float        # [0, 1] 关系强度

class SemanticMap:
    # 用 NetworkX 存储
    graph: nx.DiGraph
    
    def get_causal_chain(self, node_id: str, depth: int = 3) -> SubGraph:
        """获取到达当前节点的因果链（反向追踪 enables/depends_on 边）"""
        ...
    
    def get_parallel_branches(self, node_id: str) -> List[SubGraph]:
        """获取与当前节点并行的分支"""
        ...
    
    def detect_conflicts(self) -> List[Conflict]:
        """检测图中的逻辑冲突（如 A refutes B 但 B extends C）"""
        ...
```

### 7.3 预处理注入器

```python
class ContextInjector:
    def build_scp(self, current_node_id: str, fill_ratio: float) -> ContextPackage:
        """根据上下文填充率构建结构化上下文包"""
        
        if fill_ratio < 0.5:
            return ContextPackage(
                causal_chain=self.map.get_causal_chain(current_node_id, depth=5),
                parallel_branches=self.map.get_parallel_branches(current_node_id),
                relevant_cases=self.vector_memory.search(current_node.propositions),
                applicable_rules=self.kb.reason(current_node.propositions),
                conflicts=self.map.detect_conflicts()
            )
        elif fill_ratio < 0.7:
            # 裁剪经验案例和并行分支
            ...
        elif fill_ratio < 0.85:
            # 仅保留推理骨架
            ...
        else:
            # 仅冲突预警
            return ContextPackage(conflicts=self.map.detect_conflicts())
```

---

## 八、潜在挑战与应对

### 挑战 1：命题提取的准确性

**问题**：从 LLM 的自然语言输出中自动提取命题，误差会累积。

**应对**：
- 短期：在 Prompt 中要求 LLM 以结构化格式输出推理步骤（如 JSON 中的 `propositions` 字段）
- 中期：训练一个小型命题提取器（BERT 级别即可），专门从 Agent reasoning 中提取命题
- 长期：LLM 原生支持"思维链的命题化输出"

### 挑战 2：命题逻辑系统的规模爆炸

**问题**：大量具体命题（如 `Threshold(sensor_X, date, loop_id) = 1.05`）会快速膨胀。

**应对**：
- **抽象层次**：具体实例 → 会话级模式 → 跨会话规则 → 本体公理
- **压缩触发**：当同一模式出现 >3 次，自动泛化并提升抽象层次
- **遗忘机制**：低置信度、长期未使用的具体命题定期归档到向量库

### 挑战 3：语义地图的图维护成本

**问题**：DAG 随着会话进行不断增长，检测冲突、提取子图的开销可能过高。

**应对**：
- **分层图**：当天活跃子图（内存）+ 历史压缩图（持久化）
- **索引**：为常用查询模式（如"找所有 refutes 边"）预建索引
- **近似**：冲突检测不需要全图精确求解，可以用启发式 + 采样

### 挑战 4：与现有 LLM 的兼容性

**问题**：当前 LLM（GPT-4、Claude 等）的上下文接口是线性文本，如何注入结构化子图？

**应对**：
- **文本化编码**：将子图编码为 Markdown/JSON 文本块注入（如上面 ContextPackage 的设计）
- **专用 token**：如果未来模型支持结构化输入（如 Gemini 的多模态），直接传递图结构
- **渐进式**：先用文本编码验证概念，再逐步优化格式

---

## 九、从 TinySoul 迁移的路径

### Phase 1：增强 State（立即可行）

当前 TinySoul 的 `QueryState` 管理 `todo_list`、`milestone_list`、`action_record_list`、`loop_error_list`。

**最小改动**：给每个 action_record 增加 `propositions` 字段：

```python
class ActionRecord:
    action_id: str
    timestamp: datetime
    result: str
    
    # 新增
    propositions: List[Proposition]  # 这一轮的关键命题
    memory_refs: List[str]           # 引用的长期记忆
```

### Phase 2：引入语义地图（1-2 周）

在 `QueryLoopManager` 中维护一个 `SemanticMap` 实例：

```python
class QueryLoopManager:
    def __init__(self):
        ...
        self.semantic_map = SemanticMap()  # 新增
    
    def run_loop(self):
        # choose_action
        action = self.llm.choose_action(...)
        
        # 提取命题（短期：从 LLM 输出解析；长期：自动提取）
        propositions = extract_propositions(action.reasoning)
        
        # 建立与上一轮的语义关系
        self.semantic_map.add_node(
            node_id=f"loop_{self.iteration}",
            propositions=propositions,
            action_taken=action.id
        )
        if self.iteration > 0:
            self.semantic_map.add_edge(
                f"loop_{self.iteration-1}",
                f"loop_{self.iteration}",
                relation=infer_relation(...)  # 从命题推导关系
            )
        
        # take_action
        result = self.execute(action)
        
        # update_state
        self.update_state(result)
```

### Phase 3：选择性注入（2-4 周）

修改 `QueryLoopContext` 构建逻辑，从简单列表拼接变为 SCP 构建：

```python
class QueryLoopContext:
    def build_prompt(self, fill_ratio: float):
        # 原逻辑：拼接历史 action_records
        # 新逻辑：
        scp = self.semantic_map.build_scp(
            current_node_id=f"loop_{self.current_iteration}",
            fill_ratio=fill_ratio
        )
        return render_scp_as_text(scp)  # 文本化编码
```

### Phase 4：后处理沉淀（4-6 周）

每天 session 结束时运行命题压缩：

```python
def daily_compression(semantic_map: SemanticMap):
    # 1. 泛化高频模式
    new_rules = generalize_patterns(semantic_map.propositions)
    
    # 2. 入符号轨道（命题逻辑系统）
    for rule in new_rules:
        kb.add_proposition(rule, source="derived_from_session")
    
    # 3. 经验案例入向量轨道
    for node in semantic_map.nodes:
        if node.outcome == "FAILURE":
            vector_db.embed(node.to_text(), metadata=node.propositions)
    
    # 4. 归档语义地图
    archive(semantic_map)
```

---

## 十、总结：为什么这个架构可能定义下一代 Agent 记忆系统

当前 Agent 记忆系统的三代演进：

| 世代 | 代表 | 核心思想 | 局限 |
|------|------|---------|------|
| **G1** | RAG / Context Window | 检索相关文本块注入上下文 | 线性注入，无结构，丢失推理过程 |
| **G2** | CALMem / HippoRAG | 双记忆（语义+情景）+ 图检索 | 记忆是"内容"，不是"结构" |
| **G3** | **你的设计** | **记忆是命题，会话是推理地图，注入是结构化子图** | 实现复杂度高，需要解决命题提取和图维护 |

你的设计的核心突破在于：**把 Agent 的推理过程本身作为一等公民来存储、检索和注入**。

不是"上一轮说了什么"，而是"**为什么从上一轮走到这一轮**"、"**现在有哪些并行的推理分支**"、"**当前信念与已有知识是否冲突**"。

这正是人类专家在解决复杂问题时的认知方式 —— 不是记住所有对话内容，而是记住**推理链条**和**关键决策点**。

---

*分析完成。如需进一步展开任何部分（命题提取 Prompt 设计、语义地图可视化、与 sil_cal 标定流程的深度结合），请随时告知 ovo*
