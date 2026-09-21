# 外部 Agent 委派

subagent 把外部 ACP Agent 接入同一个 TinySoul Turn。SubagentEngine 拥有连接与协议 session；kernel/jobs 拥有委派的受理、容量、监督、等待、停止和结果保留；Workspace 拥有工作目录与结果材料。连接不是 Job，协议会话也不是 TinySoul User Session。

## 使用与语境

模型先通过 `subagent.agents` 发现配置的目标，再 connect 准备连接，delegate 创建本 Turn 的 Job。公共 `core.job.status/wait/stop` 监督执行，collect 有界读取输出，respond 选择真实权限选项，disconnect 关闭空闲连接。有活 Job 的连接不能直接断开。没有绕过 connect 的 start，也没有可能隐式开始新工作的 send/steering。

同一连接同时只运行一个 prompt Job；其后同 Turn 的新 delegate 延续同一 session，但获得新的 Job 身份。新根 Turn 使用新 session。同日、同世代且相同 profile 的空闲连接，在成功释放旧 session 后可以复用；不支持或无法完成 session 释放时关闭连接。

`connections` Working State 段只显示连接身份、目标、ready/busy/unavailable、cwd Link 和当前 Job 引用。Engine 发布连接变化，段在固定 Inbox 批次 prepare/install；协议回调不改 Context，关闭段也不关闭服务。待答和输出分别由 jobs 段与 Trace 承载。

默认 cwd 为当天 Workspace 的独立连接目录，显式 cwd_link 可选择已有目录。brief 与最多八个 Workspace 引用经 owner 有界解析，父 Context、Home、Memory 和 Session 不自动复制。输出写入 `workspace:jobs/<job_id>/output.txt`；失败和取消保留已有材料，不回滚真实 Workspace 修改。

## 权限与完成

原生 permission callback 进入有界 Job 待答投影，每个请求拥有稳定身份、问题和原始 option_id。`core.job.wait` 在待答时唤醒父 Turn；父用 respond 回应，需要人的判断时复用 `core.ask`。INPUT/BUDGET 暂停期间只积累请求，不另起模型代答。子 Agent 最终文本中的问句仍是完成结果，可由下一次 delegate 继续。

prompt 的 StopReason 决定委派执行结果，不根据输出文本或 idle 猜测完成，也不把正常结束解释为父任务目标已完成。权限过期、busy、无效目标属于局部结果。断流不重发 prompt；配置与必要进程停止失败进入所属 bridge，Workspace 失败仍由 Workspace bridge 解释。

Job 终态与执行资源关闭分开。Codex adapter 的后台终端更新在 ACP 适配层归一，prompt 结束后停止它仍拥有的后台执行，才允许同 session 新委派。取消先请求协议停止并有界等待；无响应则关闭整个受控进程树，连接明确不可用。只有实际不能关闭执行时才阻止后续生命周期转换。

Turn 收尾依次清理共享 Jobs、释放本轮 session/引用、同步 Workspace。日切、reload/restart/shutdown 关闭连接；没有跨日 cwd 迁移、旧 Job 自动续跑或第二套调度器。已停止进程后的附属客户端关闭错误只作为诊断。

## 配置与协议边界

先在 TinySoul Python 环境安装 `python -m pip install -e ".[external-tools]"`；开发环境的 `.[dev]` 包含这些依赖。ACP SDK 锁定 `agent-client-protocol==0.12.1`。本轮核验的真实目标为 `@agentclientprotocol/codex-acp@1.12.0` 与 `@openai/codex@0.154.0`，用户自行安装到稳定位置并准备目标自身的登录。配置 command 指向可执行程序；Windows 可用 node.exe 加 adapter 的 JS 入口，不把 `.cmd` 或 shell 拼接当协议进程入口。

```toml
[capabilities.subagent.agents.coder]
enabled = true
description = "在指定 Workspace 中进行代码分析与修改"
command = 'C:\Program Files\nodejs\node.exe'
args = ['C:\Tools\codex-acp\node_modules\@agentclientprotocol\codex-acp\dist\index.js']
auto_approve = false
```

`configs/capabilities/subagent.toml` 通过正常 include 加载；named collection、候选保存与空闲 reload 均复用配置门面。启用目标检查本地依赖、命令与显式 env_refs，不在装配时启动 Agent；默认资源模板不启用任何目标。非敏感固定值可用 env，凭据使用 env_refs 引用 ConfigEnvironment 中的变量。

auto_approve 显式选择 adapter 的自动许可运行模式；默认保留原生权限回调。不广告 TinySoul 未实现的 ACP fs/terminal 回调，不转发 TinySoul 的 MCP 服务或密钥，不在 Turn 中自动安装 CLI、打开浏览器或建立认证工作流。协议 stdio 使用公共 SDK 传输入口和 infra/process 的统一进程所有权；Codex 后台任务扩展留在 adapter 内，不进入 kernel 协议。

真实 Codex 的握手、session close 和新 session 隔离已验证；连续委派、权限、后台任务停止与取消由真实 ACP SDK 的本地协议 fixture 验证。本轮未运行真实模型委派，不据此宣称真实 Codex 的全部执行能力已经端到端验证。
