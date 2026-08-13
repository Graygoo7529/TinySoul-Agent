# Loop Cycle Task Profile Routing Execution Plan

状态：`done`

## 背景与目标

当前 `loop` 的 Phase1 和 Phase2 在实现中都硬编码使用 `TaskProfile.FRAMEWORK`。这使得 Cycle 的阶段协议虽然已经复用 User Turn 和 Maintenance Turn 的核心流程，却不能分别选择适合自己的 LLM task profile。

本轮允许在 Cycle 配置中选择 Phase1、Phase2 使用的 task profile，同时保持清晰的模块所有权：

- `loop` 只拥有 Cycle 阶段路由和 Turn budget；
- `llm` 继续拥有 task profile、模型链、重试和调用默认设置；
- `app` 负责两个模块之间的引用校验和 Runtime Generation 装配；
- `infra` 负责配置来源、catalog 描述和 endpoint 的通用读写；
- User Turn 与所有 Maintenance Turn 共享同一组 Cycle 阶段路由；不同 Turn 的 prompt、Action scope 和最大 Cycle 数继续分别管理。

## 确定的设计语义

### 配置归属

`loop.toml` 增加：

```toml
[loop.cycle]
phase1_task_profile = "framework"
phase2_task_profile = "framework"
```

`[llm.tasks.<profile>]` 继续定义完整 task profile。Loop 不复制模型列表，也不解析 Provider、模型能力或 adapter 细节。

`CycleSettings` 是 Loop 的不可变配置值，包含两个非空 task profile 引用。两个引用可以相同，也可以分别指向不同 profile。User Turn 和 Maintenance Turn 均从同一个 `LoopSettings.cycle` 读取它们。

### 调用与失败边界

Phase1/Phase2 接收装配层注入的 profile 字符串，并将其放入 `TaskCall.profile`。Loop 继续强制：

- `answer_format = NONE`；
- `tool_use = REQUIRED`；
- `context_overflow_policy = RECOMPOSE_CONTEXT`。

task profile 仍提供模型链、重试/切换策略以及通用调用默认值。LLM 的 `CapabilityPolicy` 根据最终 `tool_use` 自动要求 `tool_calling`，不在 Loop 中复制模型能力校验。LLM 链耗尽、Provider 错误和模型能力错误继续由 LLM 既有 Runtime bridge/链分类处理；模型输出协议失败仍然转换为现有的 Phase 局部 `PhaseFailure`。

### 校验与激活

App 编译 `AppConfigPlan` 时增加 Loop 引用到 LLM task profile 的跨模块校验：

- `loop.cycle.phase1_task_profile` 必须存在于 `llm.tasks`；
- `loop.cycle.phase2_task_profile` 必须存在于 `llm.tasks`。

错误使用对应 Loop 配置 key，并通过 `ConfigEnvironment.enrich_error()` 保留来源信息。启动时由 `RuntimeLoopBridge` 映射；endpoint PATCH 时返回 `config.invalid`，不写入候选配置，也不替换当前 generation。

配置成功后由既有 Runtime Generation 流程统一重建，稳定的 EndpointHost、事件缓冲、实例锁和连接信息保持不变。

### 装配边界

`build_turn_kernel()` 接收 `CycleSettings`，把 Phase1/Phase2 profile 分别传给两个 Phase unit。`CycleRunner` 不保存也不解释 profile，因为它只负责阶段顺序和边界控制，不直接执行 LLM 调用。

MaintenanceBuilder 现有的 `loop_settings` 参数应实际用于共享 Cycle 路由；UserTurnBuilder 继续使用同一值。不同 Turn 的 `TurnSettings` 仍分别从 User 和 Maintenance 配置读取。

### Visualization 配置体验

在 Models & Routing 下增加 `Cycle Routing` 页面，展示两个引用选择器：Phase1 Task Chain、Phase2 Task Chain。Task Chains 页面继续编辑 profile 的模型顺序和调用策略，并显示 profile 是否被 Cycle Phase 或 Action route 使用。所有字段标题、分组和说明均来自 Infra catalog，不在 Loop 或前端硬编码描述。

不新增 endpoint：现有配置状态/catalog 查询和 `PATCH /v1/config` 已能完成引用选择、持久化和 generation 激活。

## 实施步骤

1. **Loop 配置模型与解析**
   - 增加 `CycleSettings`、`LoopSettings.cycle`。
   - 解析 `[loop.cycle]`，校验两个 task profile 引用为非空标识符。
   - 更新 Loop 导出和配置单元测试。

2. **Phase 与 Turn 装配**
   - 移除 Phase1/Phase2 对 `TaskProfile.FRAMEWORK` 的硬编码。
   - 将 profile 从 `build_turn_kernel` 注入 User/Maintenance 两条分支。
   - 保持 Phase 局部失败和现有调用策略不变。

3. **App 跨模块校验**
   - 在配置计划编译阶段校验两个 task profile 存在。
   - 保持 RuntimeLoopBridge、ConfigError 和 generation 原子激活语义。
   - 为跨模块校验补充 source enrichment。

4. **配置模板、catalog 与文档**
   - 更新 development/standard profile 的 `loop.toml`。
   - 在 Infra catalog 增加 Cycle Routing surface、分组和字段描述。
   - 同步 `docs/design/loop.md` 与 `docs/design/llm.md` 的实现语义。

5. **Visualization**
   - 增加 Cycle Routing 导航和页面映射。
   - 在 Task Chains 页面聚合 Cycle/Action 引用状态。
   - 复用通用 reference 控件和运行时只读状态。

6. **验证与收尾**
   - 增加 parser、Phase 注入、App 引用校验、配置激活和前端测试。
   - 运行 Loop/App/Infra/LLM 相关 Fast 测试、Visualization 测试、完整测试和 typecheck。
   - 将本文件状态改为 `done`，并核对每项实施结果。

## 实施核对

- [x] Loop 增加 `CycleSettings`，解析并导出两个共享 Phase task profile 引用。
- [x] Phase1/Phase2 移除 `TaskProfile.FRAMEWORK` 硬编码，保留固定工具调用和局部失败语义。
- [x] User Turn 与所有 Maintenance Turn 通过 `build_turn_kernel()` 使用同一组 Cycle 路由。
- [x] App 在配置计划编译阶段校验 profile 引用，并保留 Loop source provenance 与 RuntimeLoopBridge 映射。
- [x] Standard/Development `loop.toml`、Infra catalog、Loop/LLM design 文档已同步。
- [x] Visualization 增加 Cycle Routing 页面入口，并在 Task Chains 页面聚合 Cycle/Action 引用状态。
- [x] 后端 Loop/App/Infra 聚焦测试通过，TypeScript 类型检查通过。
- [x] Visualization Vitest/Vite 完整命令已尝试；当前 `node_modules/.pnpm` 文件访问 `EPERM` 阻断属于本地依赖文件权限，不是本轮源码诊断结果。新增 settings projection 测试和 TypeScript 类型检查已通过。

## 预期修改范围

- `tinysoul/loop/config.py`
- `tinysoul/loop/phases.py`
- `tinysoul/loop/assembly.py`
- `tinysoul/loop/__init__.py`
- `tinysoul/loop/user/builder.py`
- `tinysoul/maintenance/builder.py`
- `tinysoul/app/builder.py`
- 两套 project config profile 的 `loop.toml`
- `tinysoul/infra/config/catalog/models.toml`
- `visualization/src/features/settings/*`
- `docs/design/loop.md`
- `docs/design/llm.md`
- 对应 `tests/` 与 `visualization` 测试
