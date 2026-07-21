# Application Integration Next Stage Plan

Status: done

## 意图

下一阶段不重建 TinySoul 的 Agent、Loop、Action、Context 或持久化模型，而是在已经完成的 App、Endpoint、Observation、Workspace 和桌面前端骨架上，形成一个单进程、可发现、可同时由 Terminal 与前端交互的完整应用。

应用运行始终只有一个业务后端实例。Terminal 中的 `tinysoul start` 拥有后端进程和退出生命周期；前端不嵌入 Terminal、不启动或停止后端，只发现并连接当前项目已经运行的实例。未发现实例时，前端弹窗展示推荐启动命令，由用户自行在 Terminal 中运行。

## 已确认的设计语义

1. `tinysoul start --root <project> --mode normal|verbose|model` 是唯一交互运行入口；`--mode` 只控制当前 Terminal 的信息显示等级。
2. `tinysoul start` 同时装配 Terminal input、Console output 和 authenticated loopback Endpoint。Endpoint Observation route 固定为 `model`，不提供降低采集等级的启动参数。
3. `AppCommandGateway` 是 Terminal、Endpoint 和后续可信用户输入适配器的统一命令入口；它不承担输出总线职责。
4. 所有用户可见反馈继续由业务模块通过 `ObservationEmitter` 发出，再由 `ObservationRouter` 分发到 Terminal Console 和 Endpoint event buffer，不允许适配器绕过 Router 写事件。
5. 前端始终订阅 `model`，保留 normal、verbose 和 model 全部事件，再依据事件等级、scope、identity 和 sequence 在本地切割展示。
6. Terminal 和前端都可以提交普通输入、Turn control、Home/Memory Maintenance 请求和 Home Maintenance decision；同一命令产生稳定回执与关联 identity。
7. Maintenance availability、work lifecycle、decision required 和 decision resolved 是不同事实。多个可信界面同时看到 decision 时，第一个有效 `decision_id` 提交生效，其余界面通过 resolved 事件或 stale 响应收敛。
8. 每个项目最多运行一个 TinySoul 后端。启动时持有项目级进程锁；Endpoint ready 后在当前用户运行目录原子写入有界连接描述，退出时清理。前端通过 Tauri 读取并验证连接描述，不直接读取项目业务目录。
9. 前端关闭只断开连接，不请求 `exit_program`；Terminal 中的后端负责正常退出。前端不提供自动唤起 Terminal 或后台 sidecar。
10. 连接描述、Endpoint token 和 MODEL message stack 都只属于当前本地进程生命周期，不写入 Session、Workspace、Home、Memory、浏览器 localStorage 或 URL。

## Stage 1：单一运行入口与实例发现

- 增加显式 `tinysoul start`，在同一个 AppBuilder 中同时启用 Terminal 与 Endpoint。
- 删除公开 `serve` 运行路径和 `--terminal`、`--terminal-mode`、Endpoint `--mode` 参数；保留 `tinysoul init` 等非运行命令。
- Endpoint route 固定为 `ObservationLevel.MODEL`，Console route 使用 `start --mode`。
- 为项目增加进程级单实例 lease 和用户运行目录中的连接描述；重复启动必须在构建第二个 WorkspaceEngine 前失败。
- ready/status/WebSocket handshake 增加 `instance_id` 与项目 identity，前端据此识别后端重启和错误项目连接。

## Stage 2：统一命令与 Maintenance 状态

- 为外部命令生成稳定 `command_id`，Gateway 返回明确的 accepted receipt；Endpoint 响应不再只有无关联的布尔值。
- Terminal 文本命令仍由纯 `InputCommandParser` 解释；Endpoint 普通输入、control、Maintenance request 和 decision 使用结构化边界，最终进入同一个 Gateway/Dispatcher/Program queue。
- 增加明确的 Maintenance request API，避免前端把 `/maintenance ...` 伪装为普通对话文本。
- 为普通输入、Maintenance work 和 decision 补齐可广播的 accepted、started、required、resolved、completed/failed 事实，并保留模块已有细粒度 Observation。
- 初始 Turn 输入和活跃 Turn append 必须形成可供前端还原用户消息的 Observation；Signal 仍只承担内部控制，不作为 Endpoint event 的替代品。
- 增加 Maintenance 当前状态查询，使晚连接或 sequence gap 后的前端能够恢复 availability 与 pending decision。

## Stage 3：前端只连接模式

- 删除 Tauri sidecar spawn/kill 状态和 React 的 backend start/stop 流程。
- Tauri 只根据规范化项目根定位、读取和验证连接描述，并把内存连接信息交给 React。
- 未发现有效实例时，前端展示包含正确 root quoting 的推荐 `tinysoul start` 命令；用户确认后由轮询或显式重试连接。
- 首次连接从当前实例 `after=0` 回放，不能以 `latest_event_sequence` 跳过启动事件；重连只从已提交到 store 的 sequence 继续。
- raw event store 以 `(instance_id, sequence)` 去重并保持因果顺序。发生 gap 时清理不可恢复的执行细节，并重新读取 Maintenance、Session 和 Workspace 权威投影。
- normal/verbose/model 是前端展示过滤条件，不改变 WebSocket 的 MODEL 订阅。

## Stage 4：验收与文档

- 覆盖 Console normal/verbose/model 与 Endpoint MODEL 的双 sink 测试。
- 覆盖重复项目启动、失效连接描述、正常退出清理和错误项目身份拒绝。
- 覆盖 Terminal/Endpoint 普通输入互见、Maintenance 请求互见、decision 竞争与 resolved 广播。
- 覆盖前端首次回放启动提醒、sequence 去重、实例变化和 gap 恢复。
- 更新 `AGENT.md`、App/Endpoint 设计文档、前端对接文档和 CLI 使用说明；完成后将本计划标记为 done。

## 后续能力候选

以下方向尚未获得足够真实场景，不进入本次应用接入实现：Deterministic Utilities、Home/Memory backlink、Memory 语义检索、Knowledge、Home 文档体系优化，以及基于 Codex 源代码的进一步研习。

## 完成记录

2026-07-21 已完成单一 `tinysoul start` 入口、项目进程 lease 与连接描述、Endpoint 固定 MODEL、command/request identity、结构化 Maintenance 请求和状态、decision required/resolved 广播，以及 Tauri/React 纯连接模式。前端不再启动或停止后端，首次连接从 sequence 0 回放并在 gap 后恢复权威投影；Terminal 与前端共用 Gateway 输入和 ObservationRouter 输出。全量 pytest、Python 静态类型检查、TypeScript/Vite 构建和 Rust `cargo check` 均通过。
