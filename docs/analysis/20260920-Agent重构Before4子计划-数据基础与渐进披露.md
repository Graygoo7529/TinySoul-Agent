# Agent 重构 Before 4 子计划：数据基础与渐进披露

状态：`pending`（方案已确认，尚未实施）。
日期：2026-09-20。
主计划：[Agent 架构重构](20260915-agent-architecture-refactor-plan.md)。
方案依据：[前三轮 Review 与 R4 前基础补强方案](../chat/20260920-r1-r3-review-and-pre-r4-foundation-plan-latest.md)。
代码基线：`be61886`，含 R3 收口。本计划不重新打开 R1、R2、R3 已完成的内核、SDK、owner 和失败协议迁移。

## 1. 目标与已确认边界

本计划是进入 R4 之前的基础补强，先把当前 Turn 的事实、当日 Session 的导航和渐进披露做成可验证的数据能力，再进入 fswatch、插件事件订阅和其它 S4 环境能力。它不把 R4–R6 的新能力提前塞进收口，也不提前实现 Organize Action 的完整模型工作流。

已确认的设计边界：

- Organize 面向当日此前多个历史 User Turn 和当日已有 map，持续梳理对话逻辑、意图、推理行动和交流分支，不限上一成功 Turn。
- Session Map/Organize 只服务当日持续对话；当日 turns 与 map 一起归档，新日从空地图开始。归档和 Reflection 的历史读取保持原有语义。
- execution/ACP 运行在受信独立主机上，不要求脚本或 ACP 无法绕过业务写限制；保留 owner、原子文件写、资源收尾和准确结果等运行正确性，不新增 OS 沙箱、逐操作审批或安全治理平台。
- Organize 是同一 Agent 的 `core.session.organize` Action，动作内部不再启动隐藏 LLM；模型在正常 Turn 中推理，Session owner 只负责校验和原子应用修改。
- Trace 与 Session 共享渐进披露构件，但保持各自事实 owner、顺序语义、分组规则和消息映射；不建立持久上下文数据库或平行历史库。

## 2. 当前 Review 发现的分级问题

| 编号 | 判断 | 处理 |
|---|---|---|
| BF1 | `SealedTurnTrace` 有 entries/actions，但 Session 主要投影 inputs/actions/最终 State，缺少统一交错事实顺序 | Before 4 实施 |
| BF2 | 当日 Map/inspect 尚未消费稳定事实和逐层披露构件 | Before 4 实施 |
| BF3 | BusinessClock/IanaBusinessClock/business_day、组合根与插件声明的旧表述仍可误导后续实现 | Before 4 成套清理 |
| BF4 | Linux 类型检查和本地 Web discovery 仍有环境耦合 | Before 4 修正测试/平台边界 |
| F8 | fswatch 与 owner 事件适配尚未实现 | 保留给 R4，不伪报缺陷关闭 |
| F9 | Organize 运行 Action、注释持久化和运行中 Map 刷新尚未实现 | 保留主计划尾期 |
| F10 | Gateway v2、ACP/MCP 完整适配尚未实现 | 按 S5/S6 推进 |

## 3. BF1：补齐当前 Turn 的可追溯事实

### 3.1 事实协议

在 `kernel/context` 的 Trace 事实协议中增加稳定有序引用，沿用已有 Action 身份。正文仍由 typed Input、Action、Environment 和 Job owner 提供；时间线只保存 ref、kind、seq、必要 cycle 与关联，避免复制同一输出。

必须记录：

- 输入的受理身份、接收顺序以及 Inbox 批次成功安装后对 Context 的可见位置。
- Action 的请求、开始和结算事实，按实际回调记录；并行 Action 的完成顺序不能从最终 ActionBatch 排序反推。
- 已交付的环境事实、待答请求、Job 终态和结果引用；进度按既有合并规则保存有限摘要。
- 失败、取消、未执行和未知结果的真实状态；不能伪造成功。

时间线 seq 只表达 owner 观察/提交顺序，不宣称外部物理时刻或因果关系。plan 的最终快照继续保存；无 Action 的重要变更也通过同一 typed 入口记录，不保存无意义的每次状态快照。

### 3.2 Session 接入

Session completion 接收上述 typed 事实并写入同一不可变 TurnRecord。Trace 折叠只改变模型渲染，不改变事实身份、问题/回复关系或 Action 请求/结果关系。取消前已接受的重要记录沿既有收尾流程消费；必要记录写失败仍是持久化失败，不能由观察事件成功掩盖。

不静默迁移、丢弃或 reset 已部署数据。若 schema 必须调整，显式记录 owner 负责的变化；模型投影不暴露 schema、revision、digest 或内部提交字段。

### 3.3 BF1 验收

- 串行行动间追加输入、并行行动反序完成、ask/reply、等待时事件/Job 终态都能按事实顺序解释。
- Trace 压缩后事实引用和调用/结果关联不变。
- 失败、取消和未知结果可在重新打开 Session 后追溯。
- 不新增顶层日志模块、事件溯源数据库或 Inbox WAL。

## 4. BF2：当日 Map 导航与渐进披露

### 4.1 统一访问语义

Stack 表达交互顺序，Map 表达事实/话题关系，State 表达现态；“压缩后呈现堆”描述的是访问方式，不改变这些 shape。统一渐进披露结构：顶层给出线索，节点提供有界详情、下级线索、横向关系和原始来源 ref。

Trace 的旧区间按 Cycle/行动组逐层展开；Session 按当日概览、确定性 Turn 分组、事件/行动和事实详情逐层展开；Home/Memory 保留 owner 自己的目录和渐进读取。一个事实可以被多个节点引用，不复制正文；没有 Organize 时不预先生成未经模型判断的话题和意图。

建议复用已有 JSON/分页边界，形成小型 typed 描述：

```python
DisclosureHint(ref, title, clue)
DisclosurePage(
    ref,
    content,
    children,
    related,
    sources,
    continuation,
)
```

实际字段随代码落定。公共层只负责节点/线索、分页、ref 路由、容量和无进展判断；owner 负责事实、合法分组、线索、保护项、来源和读取内容。render 纯读；压力下的纯内存折叠不调用隐藏 LLM，也不持久改写事实。

### 4.2 渐进披露约束

1. 折叠或增加父级节点只改变可见层，所属视图寿命内已返回的 ref 仍可解析；事实 ref 与展示位置分开。
2. 根、分支、关系列表和叶子都支持有界分页；长叶子由 owner 分片，不能静默裁掉正文。
3. inspect 成功返回的内容先作为可见 Action 结果保留，至少进入一次实际消费它的决策模型请求后才允许折叠。容量拒绝的请求不能提前解除保护。
4. RECLAIM 不授予 Context 任意削减某段的权力。Session 只有自身超水位才给可折叠候选；未超限或已达最低投影时返回零。
5. 披露节点只引用 Trace/Session 唯一事实来源；不从摘要重新猜调用配对，不保存跨 Turn 无限展开集合。

### 4.3 `core.context.inspect`

统一使用同一 Action 进行导航、详情读取和范围内定位。当前实现只有 ref/continuation；query 和 QUERY 能力属于本计划待实施方案。

```python
core.context.inspect(
    ref,
    query=None,
    continuation=None,
)
```

- 无 query：根/分支返回目录和可导航引用，叶子/事实返回内容并支持分页。
- 有 query：只在给定 ref 范围内查找，返回摘录、稳定 ref、顺序/来源和继续读取入口；不建立全局 search 动作或跨 owner 混合排名。
- continuation 绑定 ref/query 和读取视图；Session organize 改变视图时固定视图或明确游标失效，不静默混页。
- 不支持 query 的 owner 返回明确局部不支持结果，不忽略参数，也不被迫实现空搜索方法。

inspect 只读，不执行 Organize，不自动恢复旧帧或永久展开 Background。Background 的 load/evict 仍由各 Heap owner 管理；Session organize 是独立 Action。

### 4.4 BF2 顺序切片与验收

| 切片 | 内容 | 完成条件 |
|---|---|---|
| BF2.1 事实导航 | 消费 BF1 身份/时间线，完善当日 Map 与精确事实 ref | 无 Organize 即可查看当日问答、行动和重要事件 |
| BF2.2 共用披露 | 从 Trace 提取线索、分层显示和分页构件，Session 接入 | 只沿根线索与 ref 逐层到达事实，折叠后旧 ref 仍可用 |
| BF2.3 inspect 闭环 | typed inspect/page、ref 路由、ActionResult 可见保护 | 取回内容实际进入决策模型后才折叠；关系和工具关联不变 |
| BF2.4 辅助 query | 沿同一 inspector 加确定性范围查询 | 查询结果与精确 ref 读取指向同一证据，分页不漏不重 |

首要验收是不使用 query 也能逐层追溯。Session 空历史、损坏历史、日切归档旧地图和新日空地图都要有明确行为。公共披露只存引用/线索/视图，事实和正文仍归 owner。

## 5. BF3：所有权、日期和受信执行边界

- 将 `BusinessClock/IanaBusinessClock` 改为 `CalendarClock/IanaCalendarClock`，Turn 活动日期字段统一为 `active_day`；Reflection 保留 `source_day/target_day`。同步类型、调用者、Observation/SDK、配置和测试，不保留旧别名。
- CalendarDay 和无业务协调的 CalendarClock 归 infra；Agent 日切协调归 agent/lifecycle，Archive 继续负责目录归档。
- 完成贡献接入唯一 `TurnCompletionPipeline`；不搬 Session recorder 到空 Segment，不创建独立完成事件总线。段显示顺序与服务依赖分开，PluginDeclaration 不承诺覆盖全部异步资源生命周期。
- User/Reflection 正式动作的 owner/profile 分工继续保留；受信脚本直接写入的实际副作用由 owner reconcile 反映，不把 cwd 或 Service grant 宣称为 OS 隔离。

BF3 不扩大为目录重排。只修正仍会诱导后续实现的名称、边界和公开契约；现有内聚分包保持不动。

## 6. BF4：让本地门禁可复现

- Windows 控制台实现按平台条件隔离，使 Linux ty 不解析不可用的 `msvcrt` 成员；保留 Windows 功能，不全局忽略类型错误。
- Web URL 校验继续保留生产解析；本地 discovery 测试注入确定性 resolver，fake 页面、robots 和 resolver 一起构成可重复用例。
- httpx/OpenAI fake 服务测试不依赖宿主代理；不因测试修复顺手改变生产代理配置。
- 保留 Linux 真实进程/后代收尾和 SDK 跨日聚焦测试；Windows 实机验证与目标类型检查分别记录。

按 AGENTS 执行聚焦 → Fast → Full → typecheck；Generation/wheel/external 单独记录。环境不能完成的门禁准确记录，不用全局 skip 伪造全绿。

## 7. BF5：集成验收与主计划回填

Before 4 的代表路径：fake provider SDK 提问 → Action → 追加输入 → 环境/Job 终态 → 完成 → 同日下一 Turn inspect 先前事实；日切后旧日视图不继续进入新地图。

验收还必须证明：

- typed 完成事实不依赖 Observation 成功，必要写失败不宣称成功。
- inspect → 下一 Cycle 新 Map → 下一 Turn 继续追溯，不启动额外 LLM。
- 同一事实的 ref、顺序、关联在折叠、分页、重开和日切归档后保持可解释。
- 更新受影响 `docs/design`、协议说明和主计划；Organize Action/注释写存储仍保持尾期未实施。
- 只在代码、文档、必要验证全部通过后将本文件移动为 `docs/analysis/done/` 并更新主计划；不改写前三轮历史验收数字。

## 8. 与 R4 及尾期的边界

R4 前补强只交付事实顺序、当日导航/渐进披露、命名和可复现门禁；不提前实现全部环境 SPI、fswatch 或 Organize。

R4/S4 承接“外部文件变化 → owner reconcile → Segment 批次更新 → 后续模型看到”，复用现有 SDK、Inbox、prepare/install、等待和资源关闭。S5 实施 Gateway v2，S6 锁定 ACP/MCP adapter。主计划尾期实现 `core.session.organize`、语义节点/边和 map.json 的持久注释；S7 完成全仓一致性收口。

本子计划已纳入用户确认的当日 Session 范围和受信独立主机假设，当前没有额外待确认产品语义；具体类型、字段、容量和外部协议方法必须在实施中以真实消费者和测试落定。
