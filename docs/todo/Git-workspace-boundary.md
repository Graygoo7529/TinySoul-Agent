# Git Action 工作区边界

## 背景

`git` action 是 read-only CLI action，支持 `status`、`log`、`diff`、`branch`、`show`、`remote` 等白名单子命令。当前命令通过 argv list 执行，不走 shell，降低了注入风险。

剩余问题在于 `path` 没有绑定到 workspace 或显式允许的 repo root。

## 当前现状

- Git action 依赖 `git` 可执行文件，缺失时不会注册。
- 子命令有白名单。
- 参数通过 subprocess argv list 传递，不做 shell 拼接。
- `path` 来自 action input，命令形态是 `git -C path subcommand ...`。
- 当前没有调用 `Workspace.resolve_access()` 校验 path。

## 问题

### 1. 可能读取工作区外 repo

如果模型生成了工作区外路径，git action 可能读取外部仓库状态、日志或 diff。虽然是 read-only，也越过了 workspace 资源边界。

### 2. Git repo root 语义不清

有些项目 workspace 可能是 repo 子目录，也可能不是 repo。需要明确默认允许范围：workspace 内目录、workspace 所在 repo root，还是显式配置的 repo roots。

### 3. args 白名单不足

子命令白名单不能覆盖所有参数语义。部分 read-only 参数仍可能读取额外路径或产生大量输出。

## 建议

- 默认将 `path` 限制在 workspace 内。
- 如果需要支持 workspace 外 repo root，必须通过显式配置允许。
- path 解析使用 `Path.resolve()` 和 `Path.relative_to()`。
- 对 args 做按 subcommand 的最小约束，而不是完全透传。
- 限制输出大小，避免 diff/log 过大进入 action record。

## 实施方案

### 阶段 1：绑定 workspace

在 GitExecutor 执行前：

- 取得 `context_provider.workspace`。
- 将 `path` 解析为 workspace-relative 路径。
- 使用 `workspace.resolve_access()` 或等价 `relative_to()` 校验。
- 默认 path 为 workspace root。

### 阶段 2：支持显式 repo roots

如确实需要工作区外 repo：

- 增加 settings 或 action runtime config。
- 只允许配置列表中的 repo root。
- 在 action result 中标明实际 repo path。

### 阶段 3：约束 args

按 subcommand 定义允许参数：

- `log`: `--oneline`、`-n`、`--max-count`
- `diff`: `--stat`、指定 workspace 内路径
- `show`: 限制输出大小

拒绝危险或不必要参数。

### 阶段 4：测试

覆盖：

- workspace 内 repo path 成功。
- workspace 外 path 失败。
- 默认 path 使用 workspace root。
- unsupported args 失败。
- 输出过大被截断或报错。

## 验收标准

- Git action 默认不能访问 workspace 外路径。
- 所有 path 校验使用 resolved path 和 `relative_to()` 语义。
- 子命令和 args 都有明确允许范围。
- 输出大小有上限。

## 设计原则

- Read-only 不等于无边界。
- CLI action 必须服从 workspace 访问模型。
- 允许访问外部 repo 必须是显式配置，而不是模型自由决定。
