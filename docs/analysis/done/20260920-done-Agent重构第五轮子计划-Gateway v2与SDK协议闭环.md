# Agent 重构第五轮子计划：Gateway v2 与 SDK 协议闭环

状态：`done`（2026-09-20 实施、文档同步与门禁完成；主计划 S5 保持 `in_progress`，等待其余协议范围）。
日期：2026-09-20。
主计划：[Agent 架构重构](../20260915-agent-architecture-refactor-plan.md)。
前置：[R4 环境事件与插件运行闭环](20260920-done-Agent重构第四轮子计划-环境事件与插件运行闭环.md)。
参考：[整体功能想法](../../chat/00%20doing%20something.md)，其中旧 Gateway、状态和兼容表述以主计划与 AGENTS.md 为准。

## 1. 本轮目标

R5 落实主计划 S5：让 Gateway、Endpoint、CLI 和嵌入式 SDK 共享同一组 Agent 门面、请求、结果和状态投影，完成外部协议的运行闭环。Gateway 只做协议适配、鉴权、输入校验、错误映射与 Observation replay；Agent、Turn、Job、Workspace、Reflection 和配置事实仍由各自 owner 管理。

本轮确认：

- 当前 `/v1` 协议直接迁移到 `/v2`，删除旧 v1 路径，不保留兼容别名或双路径转发。
- Job 可以由 Endpoint 查询并请求停止，但必须通过 Turn 所有权和现有 Job owner 入口，不直接操作 backend。
- 项目初始化、reset 和 start 命令继续由 CLI 提供；HTTP 只提供运行时协议，不暴露 reset 等破坏性项目操作。

## 2. 当前基线与缺口

当前 Endpoint 已有 loopback/token 鉴权、状态、输入、控制、Reflection、配置、Action catalog、Workspace、Observation replay、WebSocket 和可选 Journal。Agent SDK 已拥有根队列、TurnHandle、追加输入、reply、grant、cancel、来源状态和世代失效语义。

本轮需要补齐的闭环是：

1. 统一 admission receipt、TurnSnapshot、TurnResult、JobSnapshot 和 RuntimeSnapshot 的外部投影。
2. 为外部调用提供结构化 Turn 创建、查询、追加、reply、grant、cancel 以及 Job 查询/停止入口。
3. 统一 `/v2/status`、replay、WebSocket 重连和 gap 语义；Observation 继续是旁路事实，不变成业务数据库。
4. 将配置、Action catalog、Reflection、Workspace 和运行控制迁移到 v2 协议并同步 OpenAPI/Endpoint 文档。
5. 让 CLI、HTTP 和 SDK 共用 Agent facade；保留 CLI-only 的 `init`、`reset`、`start` 项目命令。
6. 将 Endpoint 错误收敛为稳定 code/message/details，不泄露原始异常、绝对路径、文件正文或供应商细节。

## 3. 统一外部模型

### 3.1 请求受理与执行结果

请求先返回 admission receipt，表示 Agent 是否接受请求；Turn 完成后由 TurnResult 表达回答、Reflection 完成、等待、停止、失败或耗尽。Endpoint 不复制 Turn 状态，所有查询从当前 Agent facade 投影。

句柄被 Agent 的有限保留窗口淘汰后，Endpoint 返回 `turn.not_found`；不新增 Endpoint 专用持久数据库，不伪造历史完成结果。

### 3.2 Runtime、Turn 与 Job

Runtime projection 复用 AgentRuntimeServices，表达世代 activity/activation、active day、活动 Turn、队列和来源；Endpoint 叠加自身 instance 与 Observation cursor，SDK Agent.status 继续表达宿主生命周期。`TurnSnapshot` 表达 Turn identity、kind、state、等待原因、问题、预算请求、结果和 Job 摘要；不携带完整消息栈或私有对象。

Job 仍是 Turn-owned。Endpoint 只按 Turn identity 查询有限 `JobSnapshot`，停止请求经 Job owner 的 typed facade 进入现有 supervision/cleanup；不暴露 backend、monitor task、物理路径或原始异常。

### 3.3 事件与重连

`/v2/events` 与 `/v2/events/ws` 继续提供 Observation replay。客户端使用 `instance_id + sequence` 游标；WebSocket 首帧协商 token、after 和 mode。断线后先 replay，再读取 status；`gap=true` 时重新读取权威 Runtime、Reflection 和 Workspace projection。Journal 是可重建观察索引，不能替代业务 owner。

## 4. v2 协议形状

```text
GET  /v2/status
POST /v2/input                  # 终端式文本入口
POST /v2/control                # 活动 Turn 停止/Agent 退出意图
POST /v2/turns
GET  /v2/turns/{turn_id}
POST /v2/turns/{turn_id}/input
POST /v2/turns/{turn_id}/reply
POST /v2/turns/{turn_id}/grant
POST /v2/turns/{turn_id}/cancel
GET  /v2/turns/{turn_id}/jobs
POST /v2/turns/{turn_id}/jobs/{job_id}/stop

GET  /v2/reflection
POST /v2/reflection
GET  /v2/events
WS   /v2/events/ws
GET  /v2/config
GET  /v2/config/catalog
GET  /v2/config/actions
PATCH /v2/config
POST /v2/config/reload

现有 Workspace 资源路径整体迁移到 /v2/workspace/*。
GET /v2/health 保持无鉴权健康检查。
```

外部结构化请求不使用 `/reply`、`/grant` 等文本命令；CLI 的本地文本解析仍可支持这些命令，但最终进入同一 AgentCommands。所有 JSON schema 拒绝未知字段。

POST /v2/turns 明确创建独立 work，满载返回 409，返回 turn_id 与当前受理状态；同身份同内容复用句柄。POST /v2/input 保留终端式输入，活动时追加并允许命令解析；它返回 CommandReceipt。两种回执表达各自意图，不增加第二套调度。Reflection 的领域入口复用结构化 Turn 受理。精确请求与响应见 docs/endpoint/runtime.md 及 OpenAPI。

配置 patch 只保存候选，reload 显式激活；活动或等待 Turn 阻止激活而不阻止保存候选。Action catalog 由 Action owner 投影，Endpoint 不扫描 TOML。

## 5. 失败与生命周期

- schema、鉴权和参数错误映射为 4xx；容量、忙碌、旧世代、Turn 状态冲突映射为 409；未知 Endpoint 失败映射为 500。
- 失败 code 是稳定协议标识，message 有界，details 只保留类型化摘要。
- reload 后旧世代服务失效，已完成 Turn 句柄仍可读取原结果；restart/shutdown 关闭旧服务与命令受理，已持有句柄保留其收敛结果。调用者重取可操作服务，失败 reload 保留旧世代。
- EndpointHost 是 Agent 的受控服务，启动失败经 Endpoint runtime bridge 进入 Agent 生命周期；Endpoint 不拥有进程退出权。
- Observation sink、Journal 和 WebSocket 断开不改变业务提交；cleanup diagnostic 与主结果分开。

## 6. 顺序实施切片

| 切片 | 内容 | 验收 |
|---|---|---|
| R5.1 `done` | SDK facade 的 Runtime/Turn/Job typed projection 与查询/控制门面 | SDK 直接路径可查询活动/完成 Turn，追加、reply、grant、cancel、Job 查询/停止遵循 owner 边界 |
| R5.2 `done` | HTTP v2 schemas、routes、错误映射和 v1 删除 | OpenAPI 只出现 v2；结构化请求与 CLI 使用同一 Agent facade；旧 v1 路径不存在 |
| R5.3 `done` | 状态、replay、WebSocket cursor/gap 与断线重连 | cursor、instance、gap、heartbeat 和 journal 失败语义稳定，Observation 不进入业务事实 |
| R5.4 `done` | Reflection、配置、Action catalog、Workspace 与项目协议同步 | v2 owner API 可用；reset 仍只在 CLI；Workspace 仍无任意路径/CAS |
| R5.5 `done` | CLI/EndpointHost 生命周期与协议文档 | 启停、reload、旧对象失效、错误边界和 Endpoint 文档一致；HTTP restart 与 ACP Job 应答保留主计划后续范围 |
| R5.6 `done` | 全门禁与主计划核对 | 聚焦、Fast、Full、typecheck、generation/wheel 通过；S5 的未落地项如实保留 |

## 7. 明确不做

本轮不实现 ACP/MCP adapter、远程多用户鉴权、内部子 Turn、Gateway 自有状态库、任意文件 API、自动配置激活、旧 v1 兼容层、Session Organize 或 Memory/Home 新维护动作。

## 8. 设计与验证记录

实现核对：

- R5.1：agent/handles.py 的 TurnSnapshot/TurnResult 投影，agent/services.py 与 sdk.py 的运行、Turn、Job 门面；JobControl 只查询/停止，不暴露执行 backend。Loop 活动协议未增加 Gateway 专用方法。
- R5.2：gateway/endpoint/http 的 v2 路由与 schema；新建、追加、reply、grant、cancel 直接消费 AgentCommands。HTTP 统一映射容量、等待关联、旧服务与 Job owner 失败，不回传异常正文。
- R5.3：events buffer/engine/routes 的实例重连、超前 cursor reset、gap 和 heartbeat；原有 journal 降级继续复用。
- R5.4：Reflection 复用结构化 Turn 受理，配置/Action/Workspace 路由整体迁移；CLI 项目命令与 package data 保留现有实现。
- R5.5：协议握手 version=2；docs/design/agent.md、endpoint.md、reflection.md 与 docs/endpoint 全套文档同步。仅更新前端对接要求，未修改 visualization 源码。
- R5.6：聚焦真实 Agent HTTP 闭环、Job owner 停止/收尾并发已通过；Full `1106 passed, 23 deselected`，Generation/wheel `5 passed, 1124 deselected`，typecheck 通过。Fast 主线包含于 Full 门禁，本轮未运行 external provider/network 与 Linux 实机。

测试覆盖主线：问题与预算同时待决；字面斜杠文本按新建请求受理；追加去重；容量拒绝；排队取消；完成结果与 SDK 一致；真实 Python Job 停止和回收；旧实例/超前 cursor 的 HTTP 与 WebSocket replay。

## 9. 主计划核对边界

以下记录基础 R5 批次完成时的边界；后续 HTTP restart 与稳定宿主的实施记录见 [R5 收口子计划](20260920-done-Agent重构第五轮收口子计划-Endpoint生命周期与重启.md)，ACP Job 应答仍归 S6 adapter。

本轮已确认路由表没有 HTTP restart 或 Job 应答。主计划 §12.2 的这两项保持 pending，不因 SDK 已有 restart 就宣称 HTTP 已完成；Job 应答需要 S6 的 ACP 反向请求协议，当前不预建空入口。S5 因这些未落地项保持 in_progress。本轮 R5 按已确认查询/停止和 Gateway v2 范围独立验收，不削去主计划目标。CLI init/reset/start 的边界不变。
