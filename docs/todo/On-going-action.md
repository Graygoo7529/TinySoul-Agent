# ONGOING Action 生命周期完善

## 背景

旧记录中提出需要支持 `is_ongoing=True` 的动作和 stop/check_status 机制。当前源码已经实现基础 ONGOING 链路：`ActionMode.ONGOING`、`ONGOING_STARTED/TICK/COMPLETED` signal、ongoing action list、runtime control registry、`monitor` 示例动作和 `stop_ongoing_action`。

当前问题已经不是“完全不支持”，而是基础链路仍偏内存级、示例级，需要补足长期任务的生命周期策略。

## 当前现状

- action metadata 支持 `action_mode: ONGOING`。
- Loop 会把动作 mode 写入 `ActionSpec`。
- Dispatcher 对 ONGOING action 的启动结果发出 `ONGOING_STARTED`。
- 后台任务通过 `context_provider.emit_signal()` 发出 tick/completed。
- InterruptHandler 根据 ongoing signal 维护 `ongoing_action_list`。
- `ContextProvider` 提供 register/unregister/request termination 能力。
- `stop_ongoing_action` 可以按 `execution_id` 请求终止。
- Loop 在 completed/exhausted/interrupted/aborted 时请求所有 ongoing action shutdown；suspended 不主动关闭。

## 问题

### 1. 生命周期状态仍然偏薄

`ongoing_action_list` 目前只有 execution id、action name、turn、status、started_at 等基础字段，缺少 heartbeat、last_tick、progress、termination reason、error summary 等信息。

### 2. 缺少持久化和恢复策略

ONGOING 控制注册表是内存对象。Loop 结束或进程重启后，无法恢复或清理之前的运行控制。

### 3. 健康检查和超时策略不足

当前没有统一的 max runtime、tick timeout、health check 或 stale execution 清理策略。后台线程如果静默失败，状态可能依赖 completed signal 才能移除。

### 4. 示例 action 不能代表生产模型

`monitor` 使用 daemon thread，适合作为示例，但长期运行任务可能需要子进程、外部 job id、可重连控制或资源清理回调。

## 建议

- 保留当前 signal 驱动模型。
- 将 `execution_id` 作为 ongoing 控制的唯一标识，不用 action name 停止任务。
- 为 ongoing record 增加 heartbeat/last_tick/termination reason 等字段。
- 为 ONGOING action 定义标准控制契约：start、tick、complete、stop、shutdown。
- 增加最大运行时和 stale 清理策略。
- 对非 demo 型 ongoing action 优先使用可控子进程或外部 job 句柄。

## 实施方案

### 阶段 1：增强 ongoing record

建议扩展记录字段：

- `last_tick_at`
- `tick_count`
- `progress`
- `termination_reason`
- `last_message`
- `error`

Context view 可以继续压缩展示，避免 prompt 过长。

### 阶段 2：统一 ONGOING 控制契约

定义 action 侧约定：

- 启动成功必须注册 `OngoingControl`。
- 后台任务必须在完成、取消或失败时发出 `ONGOING_COMPLETED`。
- shutdown/user_cancel 必须设置 termination reason。
- stop action 必须按 `execution_id` 操作。

### 阶段 3：增加健康检查

实现可选策略：

- max runtime。
- max silent interval。
- stale ongoing cleanup。
- Loop 每轮检查 ongoing 健康状态。

异常 stale 状态应进入 loop error 或反馈错误，而不是永久留在 ongoing list。

### 阶段 4：沉淀标准执行器

为长期任务准备标准执行器：

- thread-based demo executor。
- process-based ongoing executor。
- external-job ongoing executor。

不同执行器共享 signal 和 control 契约。

## 验收标准

- ONGOING record 能反映最近进展和终止原因。
- `stop_ongoing_action` 对 unknown/completed execution 有明确错误。
- Loop 终态 shutdown 后能 drain completed signal，并避免悬挂状态。
- stale ongoing action 能被检测或清理。
- 至少有一个测试覆盖 user cancel，一个测试覆盖 shutdown。

## 设计原则

- ONGOING 是按 execution 管理，不按 action name 管理。
- 后台任务不直接写 QueryState，只发 signal。
- 挂起态保留 ongoing；终态请求清理 ongoing。
- 长期任务的资源控制应比示例 `monitor` 更严格。
