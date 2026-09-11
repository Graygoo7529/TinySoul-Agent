# Task Chain 模板路由同步与 memory_daily 重命名

状态：`done`

## 目标

让 standard/development 配置模板使用当前确认的运行路由：

- `[loop.cycle]` 使用 `frame_stage1`、`frame_stage2`，并由 User Turn、Home Turn、Memory Turn 共享；
- frame 阶段和现有任务 profile 使用当前确认的模型顺序与重试策略；
- development OpenAI 模型的 provider 顺序为 `orca -> sublyx_proxy -> wenrugou`；
- 将 Memory-owned daily composer 的 profile 从 `memory_daily_composition` 原子重命名为 `memory_daily`。

## 设计边界

`frame_stage1/frame_stage2` 是完整 Turn 的 Phase1/Phase2 路由。Home Turn 与 Memory Turn 共享该外层 Cycle kernel，但各自仍使用独立 Context、Action scope 和 completion 语义。

`memory_daily` 只服务 `maintenance.memory.compose_daily` action 内部的 daily Markdown 合成与校验，使用独立模型链；它不替代 Memory Turn 的 frame 阶段。Home review 当前没有独立的内层 LLM 合成任务，不添加未被调用的 `home_daily` profile。

实际项目实例不在本计划中原地迁移。开发实例将由修正后的 development 模板 reset 重建，因此不保留 `framework` 或 `memory_daily_composition` 兼容 profile。

模板中的具体 Model Chain 和 Provider Chain 是可编辑的运行配置，不由测试逐项复制断言。测试保留配置解析、跨模块 profile 引用、失败分类和“Provider 重试 -> Provider 切换 -> Model 切换 -> 下一 cycle”的通用行为契约，避免把某次模板偏好固化为重复快照。

## 实施项

- [x] 将 `TaskProfile.MEMORY_DAILY_COMPOSITION` 重命名为 `TaskProfile.MEMORY_DAILY`，更新 composer、测试和设计文档。
- [x] 同步 development/standard 的 `llm/tasks.toml`：使用 `frame_stage1/frame_stage2`，更新任务链，并将 daily profile 改为 `memory_daily`。
- [x] 同步 development/standard 的 `loop.toml` 到 `frame_stage1/frame_stage2`，同时清理 `TaskProfile.FRAMEWORK` 和 `CycleSettings` 的旧默认值。
- [x] 调整 development OpenAI 模型 provider 顺序为 `orca -> sublyx_proxy -> wenrugou`；保留 standard 的 direct OpenAI fallback。
- [x] 删除模板专属的 Model/Provider 顺序快照断言，保留配置边界和 LLM 路由恢复行为测试。
- [x] 核对 LLM 三层失败流程；将 Provider 链不可能空转等防御分支归类为 `LLMInvariantError`，不改变现有 Runtime bridge 映射。
- [x] 运行聚焦测试、Fast、Full 和 typecheck，完成文档核对。

## 验收

- 两套模板初始化后均能通过跨模块配置校验，`loop.cycle` 引用存在的 task profile。
- Memory daily composer 发出的 `TaskCall.profile` 为 `memory_daily`。
- development OpenAI 模型的三个 provider 顺序与实际配置一致；standard 仍保留 direct OpenAI fallback。
- 无遗留的内置 `memory_daily_composition` 配置或代码引用。
- `LoopSettings` 默认 Cycle 路由与内置 task profiles 一致，直接覆盖 User Turn budget 不会制造无效的 `framework` 引用。
- 模板路由偏好变化不要求同步修改重复的精确顺序断言；通用重试、切换、耗尽和 Runtime bridge 行为仍有直接测试。

## 实施结果

- standard/development 的 Cycle、Task 与 Memory daily profile 已完成原子同步；development OpenAI Provider Chain 使用确认后的模板顺序，standard 保留 direct OpenAI binding。
- `TaskProfile` 和 `CycleSettings` 不再保留已失效的 `framework`/`memory_daily_composition` 内置身份；fake-provider 端到端夹具也使用当前两个 frame profile。
- 删除了 initializer/config 测试中逐项复制模板 Model/Provider 顺序的断言。LLM 路由恢复测试继续直接验证 retry、Provider switch、Model switch、cycle、耗尽和 Runtime bridge。
- LLM TaskRunner 的局部失败、Provider 恢复输入、模块边界异常与 Runtime bridge 路径保持原设计；三个不可达防御分支改用 `LLMInvariantError`，避免误报调用契约失败。
- 按维护者确认未修改实际 `my-agent-dev`，后续 reset 将从 development 模板重建。

验证结果：聚焦 LLM config、Memory composer、Loop config、App、initializer generation 与 TaskRunner 测试通过；`Full` 为 976 passed、2 skipped、23 deselected；`ty` 类型检查和 `git diff --check` 通过。仅保留依赖侧 Starlette/httpx2 deprecation warning。
