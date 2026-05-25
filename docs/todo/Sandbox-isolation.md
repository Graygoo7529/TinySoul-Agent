# Sandbox 隔离边界

## 背景

脚本沙箱用于执行动态注册的 workspace Python 脚本。当前已有 AST 校验、受限 builtins、import 白名单、workspace 路径包装和 worker 子进程。它适合受控自动化，但不是强安全隔离。

本 todo 目标是明确并逐步收紧边界，避免把 best-effort 防护误认为生产级沙箱。

## 当前现状

- 主进程会在执行前校验 AST。
- worker 进程执行脚本。
- builtins 中的危险函数被限制。
- import 模块使用白名单。
- `open` 被包装为 workspace 内访问。
- worker 会 `os.chdir()` 到 workspace。
- payload/result 通过 `.tinysoul_runtime` 文件传递。
- 路径校验当前使用 resolved path 的字符串前缀判断。

## 问题

### 1. 没有 OS 级隔离

当前没有容器、低权限用户、Windows Job Object、seccomp、网络隔离或文件系统 mount 限制。

### 2. Python 层代理可能被绕过

`pathlib` 等标准库能力可能不完全受 `open` 包装控制。只依赖 builtins 代理不能覆盖所有文件 I/O 路径。

### 3. 路径校验方式可更稳健

字符串前缀判断容易出现边界歧义。应改为 `Path.resolve()` + `Path.relative_to()`。

### 4. `os.chdir()` 是进程全局状态

worker 是子进程，所以不会污染主进程；但在 worker 内仍是全局状态。若后续 worker 内出现并发执行，会产生风险。

## 建议

- 文档持续明确 sandbox 是 best-effort。
- 使用 `Path.relative_to()` 替代字符串前缀路径判断。
- 评估是否从白名单中移除或包装 `pathlib`。
- 默认禁用网络能力，或在强隔离模式下运行脚本。
- 对生产级执行设计 OS 级隔离方案。

## 实施方案

### 阶段 1：修正路径校验

将 `_resolve_in_workspace()` 改为：

- workspace 和 target 都 `resolve()`。
- target 必须 `relative_to(workspace)` 成功。
- 明确允许 workspace root 或仅允许其子路径。

补充 Windows 路径大小写、符号链接和 `..` 的测试。

### 阶段 2：收紧 Python 能力

评估白名单模块：

- `pathlib`
- `os`
- `subprocess`
- `socket`
- `shutil`

当前如果允许某模块，应明确它能做什么、不能做什么。

### 阶段 3：增加强隔离运行模式

根据平台选择：

- Windows：低权限用户、Job Object、受限 token。
- Linux：容器、namespace、seccomp、只读 mount。
- 通用：网络禁用、临时目录、资源限制。

该阶段可以作为未来生产部署能力，不阻塞当前本地自动化。

### 阶段 4：清理 runtime 文件策略

`.tinysoul_runtime` 当前可能被 workspace scan 发现。可以考虑：

- scan 时忽略 runtime 目录。
- runtime 目录放到 workspace 外的受控临时目录。
- 保留调试开关用于失败后查看 payload/result。

## 验收标准

- 路径校验使用 `Path.relative_to()` 语义。
- workspace 逃逸、符号链接和绝对路径有测试覆盖。
- 文档明确 sandbox 不是强隔离。
- 对允许的标准库模块有清晰理由。
- runtime 临时文件不会误导 workspace resource view，或该行为被明确记录。

## 设计原则

- 安全边界要保守表达。
- Python 层限制只能作为第一道防线。
- 高风险脚本应由 allowlist、用户确认和 OS 级隔离共同控制。
