# Action Domain 合并迁移执行计划

## 目标

将 Phase1 的 Action Domain 收敛为宽泛、允许重叠的行动方向，同时保持 Capability、持久状态与失败语义的模块所有权不变：Resource actions 并入 Workspace Domain，Script 与 Shell actions 并入新的 Execution Domain，并统一共享 process job 的生命周期 actions。

## 已确认设计

- Domain 是 Phase1 面向模型的粗粒度路由视图，不与 Capability Python 包或配置 section 一一对应。
- `resource` Domain 删除；转换能力继续由 `tinysoul.capabilities.resource` 拥有，但模型侧 action identity 迁移为 `workspace.convert_with_markitdown` 与 `workspace.convert_with_pypdf`。
- Resource 转换原有 90 秒、serial 运行语义下沉到具体 Action，不能继承 Workspace Domain 的 30 秒、allowed 默认值。
- `script` 与 `shell` Domain 删除，建立 `execution` Domain；Script/Shell 继续分别拥有 source、command、policy、依赖和 run executor。
- Script authoring 与不同运行入口使用明确的 `execution.*` action identity；共享 job 生命周期统一为 `execution.wait/stop/read_candidate/apply/discard`。
- 生命周期 Action 根据当前 Turn 与 `execution_id` 解析唯一 job 及实际 owner；模型不再选择 Script/Shell 专用 lifecycle tool。
- `tinysoul.capabilities.supervised_process` 继续拥有单 unresolved job、wait、日志/候选、事务 apply/discard、Cycle pacing 与 cleanup，并新增共享 lifecycle Action 接入边界。
- 不保留旧 Domain、旧 Action alias、兼容 Catalog 或双注册路径。

## Action Identity

Workspace 转换：

- `workspace.convert_with_markitdown`
- `workspace.convert_with_pypdf`

Execution authoring 与运行：

- `execution.write_script`
- `execution.rewrite_script`
- `execution.patch_script`
- `execution.promote_script`
- `execution.run_python_script`
- `execution.run_bash_script`
- `execution.run_powershell`
- `execution.run_cmd`
- `execution.run_bash_command`

Execution job lifecycle：

- `execution.wait`
- `execution.stop`
- `execution.read_candidate`
- `execution.apply`
- `execution.discard`

## 执行项

- `completed`：盘点 Catalog、registrar、manager、Home HOW、配置裁剪、文档和测试引用。
- `completed`：迁移 Resource Catalog identity、runtime 与 Workspace Domain HOW，调整 Resource registrar。
- `completed`：建立 Execution Catalog 与 HOW，迁移 Script/Shell registrar 和 action identity。
- `completed`：建立 supervised-process 共享 lifecycle Action executor，使 Manager 按 Turn/execution id 解析 owner。
- `completed`：同步设计文档、AGENT 当前语义、package assets 和测试。
- `completed`：运行聚焦测试、完整 `scripts/test.ps1` 与 `scripts/typecheck.ps1`。

## 验收

- Phase1 effective Domain 只暴露 `core/home/memory/workspace/execution/web` 中实际含有效 Action 的项目子集。
- Phase1 不展开主要 Action；Phase2 在 Workspace/Execution 内看到合并后的具体工具与统一 HOW。
- Resource、Script、Shell 配置与依赖仍由原 Capability parser/registrar 拥有。
- 同一 unresolved Script/Shell job 只暴露一组 Execution lifecycle Action，并保持 owner-specific run/result 事实。
- 原 Domain、Action identity 与 prompt mount 不再出现在有效 Catalog 或新项目资产中。
- 全量测试与类型检查通过。

## 实施结果

- Builtin Catalog 的有效 Domain 收敛为 `core`、`execution`、`home`、`memory`、`web`、`workspace`；旧 `resource`、`script`、`shell` Domain、Action 与 prompt mount 已删除，不保留 alias。
- Resource conversion 继续由 Resource capability 的配置、依赖、service 与 `resource.*` handler 实现，但模型侧归入 Workspace；两个转换 Action 显式保留 90 秒 serial runtime。
- Script/Shell 启动行为继续由各自 capability handler 实现；共享 lifecycle 由 `supervised_process.*` handler 统一注册，Manager 只用当前 Turn 与 execution id 找到 job，owner 作为已记录事实返回。
- Execution HOW 合并脚本维护、即时命令、事务镜像信任边界、监督、apply/discard 和收尾规则；Workspace HOW 合并文档转换选择规则。
- `scripts/test.ps1`：833 passed，23 skipped，1 个既存 Starlette/httpx 弃用警告。
- `scripts/typecheck.ps1`：全部检查通过。
