# Maintenance Turn 主对话日期归属修复执行计划

## 状态

- `done`：根因、目标语义和改动范围已确认并完成实施
- `done`：Observation 契约与前端派生修复
- `done`：测试、设计文档与 Endpoint 协议同步
- `done`：聚焦测试、完整门禁和最终核对

## 背景与根因

提交 `5a610dd` 让 Maintenance Turn 与 User Turn 共用主对话中的 Turn、Cycle、Phase、
LiveStatus、Details 和通知呈现；提交 `79c5a03` 阻止前端把维护任务内部 instruction 恢复为
用户气泡。两次提交建立的轮种识别依赖：

1. `turn.started.input_source` 识别 `maintenance.home | maintenance.memory`；
2. `turn.started.request_id` 与 `maintenance.started.request.request_id` 关联 trigger 和
   `target_day`；
3. `buildChatTurns()` 使用 Endpoint 当前 `active_day` 过滤主对话中的 Turn。

真实 Memory Maintenance 为了在关闭日的完整 Session、Workspace、活动 Memory 与
`memory:target` 情景中推理，必须以 `target_day` 作为 Turn 的 `business_day`。因此当前日为
`2026-08-18`、目标日为 `2026-08-17` 时，后端会正确发布：

```text
Maintenance 当前执行日       = 2026-08-18
Memory Turn business_day     = 2026-08-17
Memory Maintenance target_day = 2026-08-17
```

前端现有过滤器只看到 `turn.started.business_day`，把它错误解释成“该轮应归入哪一天的主
对话”，于是整轮事件在创建 `ChatTurn` 前被跳过。发起气泡、LiveStatus、Details、完成态和
toast 都没有消费对象。点击请求、Program queue、Maintenance Engine、Loop Observation 和
Endpoint replay 本身均正常。

现有单测没有发现问题，因为 Maintenance fixture 未传真实 UI 必传的 `activeDay`，并且把
Memory Turn 的 `business_day` 写成了当前日，而不是后端真实的目标日。

## 已确认的日期语义

本次修复保持两个日期事实分离：

- `turn.started.business_day` 是 Turn 的情景日。User/Home Turn 通常等于当前日；Memory
  Maintenance Turn 必须等于目标归档日。该字段服务 Context、Session、Workspace 和 Memory
  owner 的一致性，不得为了前端展示改成墙钟执行日。
- `maintenance.started.business_day` 是 Maintenance Engine 在 preflight 后捕获的当前执行
  Business Day。它表示该维护请求属于哪一天的应用活动，负责主对话日期归属。
- `maintenance.started.request.target_day` 是显式 Memory request 的目标日，只描述维护对象。
  scheduled Daily request 没有显式 target，此时已经通过 owner 不变量校验的 Memory Turn
  `business_day` 是目标日，可作为标签的权威回退。

主对话过滤规则为：

```text
User Turn        -> turn.started.business_day
Home Maintenance -> maintenance.started.business_day
Memory Maintenance -> maintenance.started.business_day
```

Maintenance Turn 内部仍保留自身 `turn.businessDay`，表示情景日而不是展示归属日。执行日只在
派生过滤时消费，不复制进无真实展示消费者的 `ChatTurnMaintenance` 字段。

## 方案与边界

### 后端 Observation

`MaintenanceEngine.run()` 已在发布 `maintenance.started` 前持有 preflight 返回的权威
`business_day`。由 Maintenance owner 在该事件顶层 payload 增加：

```json
{
  "business_day": "2026-08-18",
  "request": {
    "scope": "memory",
    "trigger": "manual",
    "request_id": "command_x",
    "target_day": "2026-08-17",
    "source": "endpoint",
    "metadata": {}
  }
}
```

`maintenance.completed` 已通过 `MaintenanceOutcome.business_day` 发布执行日，无需增加平行
字段或修改 outcome。Observation 是 JSON-safe 外部观察事实，不参与业务提交和控制流；本次
扩充不改变 HTTP request/response、Program queue、Loop 或持久化协议。

### 前端派生

`buildChatTurns()` 继续进行一次有界预扫描，但明确建立两组索引：

- `request_id -> MaintenanceRequestFacts`：执行日、trigger、显式 target；执行日实时取自
  `maintenance.started.business_day`，历史恢复时也可由既有
  `maintenance.completed.business_day` 补全；
- `turn_id -> TurnOriginFacts`：Turn 情景日、request id、maintenance kind。

处理每个带 Turn scope 的事件前，根据 origin 选择主对话归属日：

```text
maintenance kind 存在 -> 对应 request 的 execution day
否则                 -> Turn business day
```

只有已知归属日且与 `activeDay` 不同时才过滤。旧 Journal 中已完成的 Maintenance 由既有
`maintenance.completed` outcome 补全执行日；缺少 lifecycle 执行日的未完成旧事件不使用
`turn.business_day` 错误排除，也不基于时间戳猜测业务日。这里不是第二状态源：started 与
completed 是同一 Maintenance owner 对同一 request lifecycle 的实时事实和终态事实。

构造 `turn.maintenance` 时继续使用同一 request facts。Memory target 标签优先使用显式
`request.target_day`；Daily request 未携带 target 时，回退到 Memory Turn 的情景日。

### 明确不采用

- 不把 Memory Turn 的 `business_day` 改成执行日，否则会破坏归档 Context 的 owner 不变量。
- 不让所有 Maintenance Turn 无条件绕过日期过滤，否则旧日维护活动会混入今日主对话。
- 不根据 `created_at` 推算 Business Day，否则前端需要复制业务时区和跨午夜规则。
- 不把 maintenance kind/trigger/target 复制进通用 `turn.started`，避免 Loop 吸收 Maintenance
  owner 语义。
- 不在点击时创建本地 queued `ChatTurn`。HTTP `202` 只代表进入 Program queue，任务仍可能
  等待或在启动 Turn 前 typed skipped；伪轮次会引入第二套请求状态机。
- 不在本次扩展 skipped Maintenance 的请求级主对话呈现。它没有 `turn.started`，属于独立的
  Maintenance outcome 产品语义。

## 失败与控制流核对

- Endpoint 入口继续把非法 kind、缺失/非法 target 和 gateway 拒绝映射为明确 `4xx`，前端
  只对同步提交失败显示错误 toast。
- `202` 后的异步执行失败继续由 Maintenance 的 typed task outcome、模块边界异常和 Runtime
  transfer 三层语义处理。本次不增加异常类型、不捕获宽泛异常。
- Observation sink 失败继续由 Runtime helper 隔离，不反向影响 Maintenance 结果。
- 前端对缺失执行日采用“不过滤但继续安全派生”，不把 Observation 不完整升级为业务失败，
  也不伪造日期。

## 改动范围

### `tinysoul/maintenance/engine.py`

- 在 `maintenance.started` payload 中加入 `business_day`。
- 不修改 `MaintenanceRequest`、`MaintenanceOutcome` 或任务调用签名。

### `tests/maintenance/test_maintenance_engine.py`

- 注入记录型 Observation emitter。
- 验证 `maintenance.started.business_day` 等于当前执行日。
- 验证 request 内显式 `target_day`、trigger 和 request id 原样保留，未被执行日覆盖。

### `visualization/src/derive/chat.ts`

- 用明确的 request/turn origin 预扫描替代单一 `dayByTurn`。
- 同时消费 `maintenance.started` 与 `maintenance.completed` 的执行日，保证实时与历史恢复
  使用同一归属语义。
- Maintenance Turn 按执行日、普通 Turn 按情景日过滤。
- Daily Memory 的目标标签回退到 Memory Turn 情景日。
- 保持 `ChatTurn.businessDay` 的现有情景日含义。

### `visualization/src/derive/chat.test.ts`

- 真实复现当前执行日与 Memory 目标日不同的组合，并传入 `activeDay`。
- 验证今日执行的 Memory Turn 保留。
- 验证旧执行日的 Maintenance Turn 不混入今日对话。
- 验证普通 User Turn 的日期过滤不回归。
- 验证 Daily request 下 Memory 标签仍得到目标日。
- 保留内部 task instruction 不恢复为用户消息的契约。

### 文档

- `docs/design/maintenance.md`：固化执行日、Turn 情景日和 target 日的职责。
- `docs/endpoint/maintenance.md`：记录 Maintenance lifecycle Observation 的日期与关联协议。
- `visualization/docs/design/chat.md`：记录主对话按执行日归属 Maintenance Turn 的派生规则。

不修改 Endpoint HTTP schema、前端 Store、渲染组件、通知器、Session、Workspace 或 Memory
持久化。

## 实施阶段

### Stage 1：Observation 契约与后端测试

status: `done`

1. 扩充 `maintenance.started` payload。
2. 加入 owner 级 Observation 契约测试。
3. 运行 Maintenance 聚焦测试。

实施结果：`maintenance.started` 已由 Maintenance Engine 发布当前执行
`business_day`，owner 级测试确认执行日与显式 Memory target 保持分离；聚焦测试
`12 passed`。

### Stage 2：前端派生与回归测试

status: `done`

1. 重构预扫描索引和日期选择逻辑。
2. 修正显式及 Daily Memory target 标签来源。
3. 加入真实日期组合与旧日排除测试。
4. 运行 derive 与 notifier 聚焦测试、前端 build。

实施结果：`buildChatTurns()` 按 Maintenance lifecycle 执行日过滤维护轮，同时保留
Memory Turn 的目标情景日；显式 target、Daily target 回退、旧执行日排除、旧 completed
事件恢复和 User Turn 日期过滤均已覆盖，derive 聚焦测试 `29 passed`。

### Stage 3：文档同步与完整验收

status: `done`

1. 同步 Maintenance 设计、Endpoint 协议与 Visualization 设计。
2. 运行默认 Fast、Full 和 typecheck。
3. 检查 `git diff --check`、工作树改动范围和文档/实现一致性。
4. 回读本计划，逐项核对验收条件，写入实施结果和实际验证结果；全部完成后将文件名加入
   `-done-` 标记。

实施结果：设计文档、Endpoint Observation 协议和 Visualization 派生规则已同步；后端 Fast、
Full、typecheck 及前端 derive/typecheck 均通过。Vite build 与 notifier 聚焦测试曾执行，均被
现有 `visualization/node_modules` 的 Windows `EPERM` 读取权限阻断；提权复跑请求又因审批服务
返回 `502 Bad Gateway` 被拒绝，故按计划记录为环境验证缺口，不伪装为通过。

## 实际验证结果

- `tests/maintenance/test_maintenance_engine.py`：`12 passed`。
- 前端 `src/derive/chat.test.ts`：`29 passed`。
- 后端 Fast：`946 passed, 2 skipped, 22 deselected`。
- 后端 Full：`947 passed, 2 skipped, 21 deselected`。
- 后端 typecheck：`All checks passed!`。
- 前端 TypeScript：`npm exec tsc -- --noEmit` 通过。
- `git diff --check`：通过。
- 前端 Vite build：未完成，Windows 无法读取现有 `node_modules` 中
  `katex/.../KaTeX_AMS-Regular.woff2`，报 `EPERM`；提权复跑因审批服务 `502` 被拒。
- 前端 derive + notifier 聚焦测试：derive 已通过；notifier worker 无法读取现有
  `node_modules` 中 `punycode/.../punycode.js`，报 `EPERM`；提权复跑因审批服务 `502` 被拒。

## 执行计划核对

- [x] 根因已定位为 Memory Turn 情景日与 Maintenance 执行日被前端混用。
- [x] `maintenance.started.business_day` 已补齐，且与 `request.target_day` 保持独立。
- [x] Maintenance Turn 按生命周期执行日过滤，User Turn 仍按自身情景日过滤。
- [x] 显式 Memory target、Daily target 回退、旧 completed 恢复均有测试。
- [x] 内部 maintenance instruction 不恢复为用户消息的既有契约保留。
- [x] 异常分层、owner 边界、HTTP/队列/持久化协议未扩大修改范围。
- [x] 设计文档、Endpoint 文档和前端设计文档已同步。
- [x] 可执行测试与静态检查已完成；受环境权限阻断的两项验证已精确记录。

## 验收条件

- 今日手动或 scheduled Memory Maintenance 即使维护过去目标日，也在今日主对话形成完整
  Maintenance Turn。
- 该 Turn 的发起气泡显示 Memory、正确 target 和 trigger；内部 instruction 不成为用户气泡。
- LiveStatus、Details、停止能力、落定状态和完成通知继续复用现有 Turn 链路。
- 旧执行日 Maintenance Turn 不进入今日主对话。
- User Turn 仍严格按自身 Business Day 过滤。
- Memory Turn 的 Context 情景日仍为目标归档日，后端 owner 不变量不变。
- 新 Observation 字段有后端测试和协议文档，前端日期组合有真实回归测试。
- 没有新增重复状态、兼容 alias、宽泛异常或跨模块 owner 捷径。
- 聚焦测试、Fast、Full、typecheck、前端测试与 build 通过；若环境本身阻止某项验证，记录
  精确错误和已完成的替代验证，不将其伪装为通过。
