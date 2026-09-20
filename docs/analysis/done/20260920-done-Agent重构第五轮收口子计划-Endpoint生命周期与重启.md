# Agent 重构第五轮收口子计划：Endpoint 生命周期与 HTTP Restart

状态：`done`。
日期：2026-09-20；完成核对：2026-09-21。
主计划：[Agent 架构重构](../20260915-agent-architecture-refactor-plan.md)。
前置：[R5 Gateway v2 与 SDK 协议闭环](20260920-done-Agent重构第五轮子计划-Gateway v2与SDK协议闭环.md)。

## 1. 收口目标

本子计划补齐 R5/S5 中仍未闭合的宿主生命周期语义，使 Endpoint 在同一 Agent 进程内跨 SDK restart 保持稳定，同时允许 HTTP 客户端请求宿主重启。Endpoint 继续是协议适配层，不拥有 Agent、Turn、Job、Workspace 或配置事实。

本轮确认的协议边界：

1. EndpointHost、EndpointEngine、Observation buffer/journal 和 `instance_id` 属于进程宿主生命周期；Agent generation 切换只替换它们访问的当前 Agent facade。
2. 新增独立 `POST /v2/restart`。请求等待 Agent 完成旧 generation 收尾并装配、激活新 generation 后返回当前 runtime projection；`instance_id` 保持不变，`generation_id` 改变。
3. 活动/排队 Turn 及其 Turn-owned Job 按既有 Agent restart 语义收敛。旧 generation 的 commands、services 和 endpoint binding 在切换后失效，调用者重新取得当前 facade；不迁移旧 Turn、Job 或 Workspace lease。
4. ACP Job 应答不属于本轮通用 Gateway 协议。主计划中的“Job 回应”移入 S6 ACP adapter，由 `subagent.respond` 等真实动作按 ACP 权限请求语义实现；R5 只提供 Job 查询和停止。
5. HTTP restart 失败不新增恢复状态机。Endpoint 保持可访问，稳定错误映射为有限 code/details；若旧 generation 已关闭，客户端重新读取 `/v2/status` 并等待宿主按现有生命周期重新启动。

## 2. 当前问题与设计收敛

收口前 EndpointHost 作为 `AgentAssembly` service 挂载，Assembly 重建时会停止 HTTP server；EndpointEngine 直接持有旧 generation 的 gateway/services/config，无法在 restart 后安全复用。直接添加路由会形成失效引用和重启期间的第二套状态。

收敛为一个稳定 EndpointHost：

- EndpointEngineContext 只保存稳定 settings/events 与当前绑定的 Agent facade；bind/unbind 在 generation 边界替换引用，未绑定时返回 typed service unavailable。
- EndpointHost 负责 HTTP server 和 Observation route 生命周期，`bind(assembly)` 负责切换 facade；旧 Observation route 先移除，新 route 再登记，避免重启后重复写入同一个 journal。
- EndpointHost 不再作为 Assembly 的业务 service 参与 generation close。CLI/宿主在 Agent 启动后启动它，在最终 shutdown 前停止它；Agent restart 只通过 factory 重新 bind。
- `mount_endpoint` 只为单 generation 的嵌入式装配随 Assembly 启停。CLI 和需要跨 restart 的嵌入方显式持有同一个 EndpointHost，并在每次 factory build 后 bind，server 独立于 Assembly 启停。
- EndpointEngine 通过 typed `EndpointLifecycle` 接收 restart 能力；没有宿主控制器的嵌入式 Endpoint 只返回有限的 `endpoint.lifecycle_unavailable`，不伪造 restart。
- Agent 的进程等待跨越 restart，重启失败由发起方接收，仍可从稳定 Endpoint 查询和显式重试；最终退出/关闭才结束宿主等待。Ctrl-C 每次取得当前 commands，factory 重建时重新加载配置和输入来源，不继续使用旧代对象。

## 3. 实施切片

| 切片 | 内容 | 验收 |
|---|---|---|
| R5C.1 `done` | EndpointEngineContext 动态绑定、EndpointHost stable owner、Observation route 可移除/重绑 | 同一 engine/instance 与 cursor 跨 restart；旧 commands 拒绝；route 无重复写入，失败隔离不漂移 |
| R5C.2 `done` | CLI/嵌入式宿主生命周期装配 | 真实 HTTP server 跨连续重启与一次失败后重试存续；ready 只发布一次；重启后的 Ctrl-C 正常退出 |
| R5C.3 `done` | `POST /v2/restart`、lifecycle facade、错误映射 | 新 runtime、503 restart_failed、409 未绑定和无 lifecycle、鉴权边界均有验证 |
| R5C.4 `done` | ACP Job 回应边界、主计划和文档同步 | R5/S5 只描述 Job 查询/停止；S6 明确承接 ACP response，不出现通用空接口 |
| R5C.5 `done` | 测试与门禁 | Fast、Full（包含 Generation/wheel）、typecheck 与 diff-check 通过，详细证据见 §7 |

## 4. 不做

本轮不实现 ACP/MCP adapter、`/jobs/{job_id}/respond` 通用入口、HTTP reset/init/start、跨 generation Turn/Job 迁移、Endpoint 自有业务状态库、自动重连或失败恢复状态机。

## 5. 失败与控制流

- HTTP schema/auth/request 错误继续由 EndpointRequestError 处理。
- Agent restart 的生命周期失败由 Agent SDK/Runtime bridge 分类后经 HTTP 统一映射；Endpoint 不回传原始异常或 traceback。
- Observation/journal 写入失败仍是旁路诊断，不阻止 Agent restart；route 移除按对象身份完成，既有失败 sink 隔离不因位置移动而改变。
- bind 期间没有可用 generation 时，业务查询和写入返回稳定 service-unavailable；status、health 和 replay 仍可用。不读取旧 generation 私有对象，也不创建临时状态副本。

## 6. 完成条件

实现、`docs/design/`、`docs/endpoint/`、AGENTS.md 与主计划同步；旧 R5 子计划的已完成范围不被重复实现；Full、Generation/wheel、typecheck 和 diff-check 通过。完成后将本文件标为 `done`、加入文件名 `-done-` 并移动到 `docs/analysis/done/`。

## 7. 实施记录

2026-09-21 已完成 R5 收口：`EndpointHost` 持有进程级 `EndpointEngine`、Observation buffer/journal 和 instance identity，`EndpointEngineContext` 在 generation 边界只重绑当前 typed facade；旧 generation 的 commands、services、Turn 和 Job lease 在切换后失效。CLI 与嵌入式装配均在 Agent factory 完成 bind，HTTP server 不因正常 Agent restart 重建，最终 host stop 会清理 lifecycle 并解绑 generation。

新增 `POST /v2/restart`，由宿主 lifecycle 等待 Agent restart 完成后返回新的 runtime projection；重启窗口仍可读取 status，Endpoint instance 和事件游标空间保持稳定。ACP Job response 保持在 S6 adapter 范围，R5 只提供 Turn-owned Job 查询/停止。

最终复核补齐 CLI 真实主线：`tinysoul/agent/sdk.py` 中 Agent.wait 等待 Agent 退出，跨越 generation restart；`tinysoul/gateway/cli.py` 重新装配配置和 Terminal、按需获取 commands，保证失败重启不会结束宿主。`tinysoul/gateway/endpoint/host.py` 与 `engine/context.py` 拥有稳定传输和可重绑依赖，`engine/runtime.py` 映射有限请求失败。`tinysoul/agent/observation/outputs.py` 按 route 身份隔离 sink 故障，移除 route 不改变其余 sink 的失败状态。

验证由 `tests/gateway/test_cli_fake_provider.py` 的真实 CLI 宿主/HTTP server 回归覆盖连续重启、临时未绑定、构建失败与显式重试、instance/cursor、旧 facade、route 去重和重启后 Ctrl-C；`tests/agent/test_sdk.py` 覆盖进程等待与等待者取消隔离；Endpoint API 与 Observation owner 测试覆盖局部协议。2026-09-21 Windows Fast `1104 passed, 28 deselected`；Full `1109 passed, 23 deselected`，包含全部 5 项 Generation/wheel；`typecheck.ps1` 与 `git diff --check` 通过。未运行 Linux 实机和真实 provider/network。

依据 AGENTS 核对：没有新增业务事实副本、第二套 Turn/Job 状态机、自动恢复或旧协议别名。生命周期由 Agent 拥有，Gateway 只请求并映射，资源仍经 owner facade；主计划 S5 标记 done，S3 Organize 延后项和 S6–S7 保留。
