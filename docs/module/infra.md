# Infra 模块

## 定位

Infra 模块提供 TinySoul 的基础运行能力：配置、日志、能力探测、资源读取、文本处理、进程管理和脚本沙箱。它不包含 Loop 决策，也不包含具体业务动作。

Infra 的目标是让上层模块使用稳定的小接口，而不是直接散落访问环境变量、文件系统、子进程和第三方依赖。

## 配置

`GlobalSettings` 在 `tinysoul/infra/settings.py` 中定义，初始化时会加载 `.env`。加载规则是：`.env` 只填充当前进程尚未设置的变量，系统环境变量优先。

主要配置包括：

- Loop 轮次和超时。
- LLM 调用超时与重试。
- Action/CLI/Script 超时。
- 并发分发 buffer。
- 上下文压缩上限。
- 日志开关和输出。
- 工作区和沙箱相关选项。

当前 `settings.parallel_dispatch_buffer` 默认是 `20.0` 秒。全局 settings 中没有固定 `api_timeout` 字段；API 超时是 ActionRuntimeConfig 预留的动作级配置。

`settings` 是模块级单例。测试或特殊运行模式需要修改配置时，应优先通过环境或显式配置入口完成，避免在业务代码中随意改写单例。

## 默认值

`tinysoul/infra/defaults.py` 维护跨模块默认常量，包括：

- 默认 provider/model 规格。
- 默认 capabilities。
- 默认超时。
- 默认上下文压缩数量。
- 默认日志格式。

这些默认值是系统的启动基线。Provider 层会在此基础上结合环境变量生成真实可用模型配置。

## 日志

`EventLogger` 提供结构化事件日志：

- 按 category 组织事件。
- 按 level 控制输出。
- 支持控制台和文件 sink。
- 对常见事件提供格式化输出。

日志模块服务于调试和可观测性，不参与控制流判断。业务代码不应依赖日志文本来决定行为。

## 能力探测

Capabilities 用于描述当前运行环境能做什么，例如：

- 可执行文件是否存在。
- Python 包是否可导入。
- 某类 provider 或模型能力是否可用。

ActionRegistry 在注册动作时会使用能力探测过滤不可执行动作。这样模型看到的动作列表与实际环境保持一致。

## 资源读取

资源模块封装包内 markdown、prompt 和其他静态资源读取。Prompt 模块通过它读取内置 system/guide 文件，避免硬编码文件系统路径。

资源读取应保持显式失败。内置资源缺失通常表示安装或包结构错误，不应静默忽略。

## 文本工具

文本工具提供轻量处理能力，例如截断、格式化、JSON 提取辅助等。原则是只做通用转换，不承载业务语义。

结构化数据应优先使用 JSON/Pydantic/显式对象处理，不应依赖复杂字符串拼接。

## 进程管理

`ManagedProcessRunner` 封装子进程执行：

- 启动进程。
- 收集 stdout/stderr。
- 处理 timeout。
- 根据 `RunConfig` 响应取消或终止请求。
- 先 terminate，再在短等待后 kill。

CLI 类动作和脚本执行器通过该层获得统一的超时和取消行为。

## 沙箱

脚本沙箱由主进程和 worker 进程协作完成：

1. 主进程校验脚本 AST。
2. 写入 payload 到 `.tinysoul_runtime`。
3. 启动 `python -m tinysoul.infra.sandbox_worker`。
4. worker 在受限 builtins、受限 import 和工作区路径包装下执行脚本。
5. 主进程读取结果并清理临时文件。

沙箱限制包括：

- 禁止危险 AST 节点。
- 限制可导入模块白名单。
- 包装 `open` 等文件访问入口。
- 将路径解析限制在工作区内。
- 通过子进程隔离运行。

这是面向自动化脚本的防护层，不是强安全隔离。某些标准库路径能力可能绕过 Python 层包装，因此高风险脚本仍应由动作 allowlist 和运行环境权限共同控制。

## 与其他模块的关系

- Loop 使用 settings、logger 和 process 超时能力。
- Action 使用 capabilities、RunConfig、sandbox 和 process runner。
- Prompt 使用 resource helper。
- LLM 使用 settings/defaults 构建 provider 配置。
- Workspace 和脚本执行依赖 infra 的路径与沙箱能力。

Infra 应保持低层、无业务状态，避免反向依赖 Loop、Action 或 Trap。

## 当前边界

- `.env` 加载发生在 settings 初始化阶段，运行中修改 `.env` 不会自动刷新。
- 沙箱是 best-effort 防护，不提供操作系统级强隔离。
- 子进程取消依赖操作系统进程控制，线程内不可中断代码无法由 Infra 强杀。
- 日志 formatter 只面向可读性，不是稳定 API。
- Provider 默认规格不代表适配器一定存在，实际能力以注册 adapter 和配置解析为准。

## 设计不变式

- 环境读取集中在 settings/defaults/capabilities。
- 子进程和脚本执行必须受 RunConfig 控制。
- 包内资源通过资源 helper 读取。
- Infra 不反向调用业务层。
- 安全边界要显式描述，不把 best-effort 沙箱写成强隔离。
