# Runtime 失败桥接统一与死抽象清理执行计划

- 日期：2026-11-23
- 状态：`done`（P1–P4、A1–A8 已逐项核对；完整 Full 与 ty 门禁通过）
- 初次核对基线：`0fe0e75e`
- 修订核对基线：`b4f91b95`（与初次基线相比，本计划涉及的生产、测试及设计文档无差异）
- 实施基线：`415d85d1`（维护者已提交修订计划；生产代码与审阅基线一致）
- 依据：
  - [AGENTS.md](../../../AGENTS.md)
  - [Runtime 设计](../../design/runtime.md)
  - [Capabilities 设计](../../design/capabilities.md)
  - [Agent 设计](../../design/agent.md)
  - [Endpoint 配置协议](../../endpoint/configuration.md)
  - 本线程维护者对审阅建议的确认：“合理，请进一步分析和修订执行计划；若计划明确可行，则进行准备实施状态。”

## 0. 确认结论与实施准入

本计划的核心问题已通过代码追踪和局部复现确认。修订采用已讨论的方向：失败分类归 owner，是否进入 Runtime 由调用边界决定；统一 Bridge 不等于把所有配置或局部执行错误转换为 RuntimeException。

| 已确认决策 | 实施约束 |
| --- | --- |
| 分离局部失败与 Runtime 失败 | `ExpandFailure` / `SubagentFailure` 保持局部短原因；新增各自 `FailureKind`，不整体修改局部错误码 |
| 统一依赖诊断键归属 | 使用 `capabilities.web.dependencies.*` / `capabilities.resource.dependencies.*`，不新增 `PluginConfig.error_prefixes`、`owns_error_key` 或 Agent 特判 |
| 只保留一条能力装配路径 | 插件在候选世代内完成一次依赖检查、凭据解析与服务构造；registrar 只绑定 executor 和声明 support，不保留旧的检查/构造入口 |
| 清除无消费者参数 | 删除 `ReflectionTurnEntry.kind` 参数及校验、属性；情景选择与有效性校验仍由真正消费 kind 的 Reflection 装配与指导选择负责 |
| 补齐行为和架构验收 | AST 守卫拒绝无合格枚举的 Bridge；HTTP 回归验证 422/500 分类和旧世代、文件状态；不以结构检查替代调用链测试 |

- [x] 重新核对规约、计划问题和真实调用链，区分功能缺陷、诊断一致性与机械清理。
- [x] 核对服务可按世代共享：service 不保存本轮 Context；进程 handle、取消控制、JoinedOperations 与 staging 子目录按调用持有。
- [x] 核对诊断键消费者与测试迁移入口；未发现仓库内前端按旧依赖诊断键分支，Resource 有一处精确键断言需要更新。
- [x] 明确冷启动、PATCH、apply/reload 与关闭边界；不修改既有激活事务或资源回收状态机。
- [x] 明确改动文件、测试归属、文档同步、执行顺序和验收标准。
- 未决设计项：无。维护者已明确授权“按此实施，实施完成后基于 AGENTS.md 和实施情况核对该执行计划”；实现、文档与门禁已全部核对，完成记录见 §6–§8。
- 状态沿 `ready → in_progress → done` 推进；完成与归档基于实际验证，不以轮次或测试数量代替语义验收。

## 1. 目标与改动预览

本计划修正已核实的模块失败桥接、能力插件启动所有权及无消费者代码问题，不重建执行内核或通用异常管理平台。下表保留实施前状态与确认目标；实际完成结果、验证及规约复核见 §5–§8。

| 切面 | 当前状态 | 改进后目标语义 |
| --- | --- | --- |
| `expand` / `subagent` 失败枚举分层与 Bridge 契约 | `ExpandFailure` 与 `SubagentFailure` 同时混装局部请求错误与 Runtime Bridge 失败项，且 `configuration_failed`、`execution_close_failed` 缺少 `<module>.` 前缀；调用 `RuntimeExpandBridge` / `RuntimeSubagentBridge` 时直接触发 `RuntimeContractError` | 拆分为服务于 Bridge 的 `ExpandFailureKind` / `SubagentFailureKind`（带 `expand.` / `subagent.` 前缀）与仅承载局部请求错误的 `ExpandFailure` / `SubagentFailure`；移除无生产与消费路径的 `SubagentFailure.PROTOCOL`；保持 Action `ActionLocalFailure.reason` 与 Endpoint `expand.<reason>` 外部契约不变 |
| `web` / `resource` 启动配置与依赖失败所有权 | 插件借用 Action Bridge；检查按三个 profile 重复执行；`ProfileAssembly` 将 `ConfigError` 强行包装为 RuntimeException；旧依赖诊断键不在 owner 配置范围内 | 新增最小 owner Bridge；依赖诊断键回到 owner 下；世代检查和构造一次、profile 纯注册；冷启动准确归属 owner，热激活配置错误返回 422 |
| Bridge 结构与诊断一致性 | 12 个 Bridge 已有 frozen dataclass 与显式映射；Execution、Expand、Subagent、Jobs 存在形态或公共诊断 helper 使用差异 | 对齐四个既有及两个新增 Bridge；配置入口使用有界 `key/expected`，普通异常入口使用 `error_type`；不为没有配置入口的 Bridge 添加空接口 |
| 架构测试守卫闭合 | 手工参数表只覆盖 14 个模块；按 `*FailureKind` 后缀过滤可能将“未找到枚举”当作成功 | 补齐四个 owner；以完整枚举身份和文件集合核对登记；每个 Bridge 必须实际引用所属枚举，不能空匹配通过 |
| 死抽象、未读私有状态与冗余导入 | 聚合配置模块无生产调用；计划列出的字段未读取；Reflection Entry 的 kind 除校验外无消费者；10 个非门面文件有 12 处未使用导入 | 删除聚合 parser、迁移五个测试文件；清理未读字段、无消费者参数和导入，保留有效构造参数、门面重导出及继承读取 |

边界声明：

- 本计划严格限定在后端代码、测试与文档范围（`tinysoul/`、`tests/`、`docs/`），不修改 `visualization/`。
- 不改变任何模型可见固定文案（`tinysoul/prompts/`），不新增 Runtime 通用控制原因或 Trap 处理器，不新增 Endpoint 路由。
- 不新增通用 Bridge 基类、动态 registry、配置归属别名或 `skip_validation` 一类双路径开关。
- 不改变 Action visibility/grants、Workspace 写入语义、User/Reflection Context 隔离、Job 监督和持久化格式。
- 依赖诊断 `details.key` 的命名调整及配置激活 500 → 422 是明确的外部可观察变化，实施时同步 Endpoint 文档；不建立旧键兼容 alias。

---

## 2. 已核实的现状与问题依据

### 2.1 `expand` 与 `subagent` Bridge 触发 `RuntimeContractError`

1. `tinysoul/runtime/failures.py:13-29` 的 `runtime_exception` 强制校验模块命名空间归属：
   - 当 `not module or not kind.value.startswith(f"{module}.")` 时，直接抛出 `RuntimeContractError("Failure kind must belong to its module")`。
2. `tinysoul/plugins/capabilities/expand/failures.py:6-18` 将 `CONFIGURATION_FAILED = "configuration_failed"`、`EXECUTION_CLOSE_FAILED = "execution_close_failed"` 与 9 个局部请求错误放在同一个 `ExpandFailure(StrEnum)` 中；`tinysoul/plugins/capabilities/expand/runtime_bridge.py:10-27` 将上述无前缀枚举传入 `runtime_exception(module="expand", kind=...)`。
3. `tinysoul/plugins/capabilities/subagent/failures.py:6-13` 与 `tinysoul/plugins/capabilities/subagent/runtime_bridge.py:10-27` 存在完全相同的问题；同时全仓检索确认 `SubagentFailure.PROTOCOL = "protocol_failure"` 在 `tinysoul/` 与 `tests/` 中均无任何抛出或断言位置。
4. 在当前 `.venv` 下实测调用以下四个入口：
   - `RuntimeExpandBridge().from_config_error(ConfigError("bad", key="capabilities.expand"))`
   - `RuntimeExpandBridge().close_failed(RuntimeError("close failed"))`
   - `RuntimeSubagentBridge().from_config_error(ConfigError("bad", key="capabilities.subagent"))`
   - `RuntimeSubagentBridge().close_failed(RuntimeError("close failed"))`
   均抛出 `RuntimeContractError`，导致 MCP / ACP 配置错误与受控进程关闭失败无法按设计进入 `RUNTIME_STARTUP_FAILED` / `RUNTIME_AGENT_END`。
5. 不能简单给现有 `ExpandFailure` / `SubagentFailure` 全员加前缀：
   - `tinysoul/gateway/endpoint/http/app.py:237` 通过 `f"expand.{error.reason.value}"` 生成 HTTP 错误码（加前缀会劣化为 `"expand.expand.invalid_request"`）；
   - `tinysoul/plugins/capabilities/expand/actions.py:254` 与 `tinysoul/plugins/capabilities/subagent/actions.py:56` 将 `error.reason.value` 直接写入 `ActionLocalFailure.reason`（如 `"invalid_request"`、`"invalid_arguments"`、`"busy"`），属于既有局部结果协议。
   按 `AGENTS.md` 三层失败规约，局部请求错误与服务于 Runtime Bridge 的模块边界失败枚举应当分离。

### 2.2 `web` 与 `resource` 启动配置与依赖失败归属错位

1. 所有权错位：
   - `tinysoul/plugins/capabilities/web/plugin.py:32-37` 与 `tinysoul/plugins/capabilities/resource/plugin.py:31-36` 在 `PluginConfig` 中传入 `RuntimeActionBridge().from_config_error`，使 `capabilities.web.*` 与 `capabilities.resource.*` 的配置解析错误在启动期被标记为 `module="action"`、`kind="action.configuration_failed"`，与 `ExecutionPlugin`（`module="execution"`）、`ExpandPlugin`（`module="expand"`）、`SubagentPlugin`（`module="subagent"`）不一致。
2. 校验时机与热激活链路错位：
   - `WebPlugin.build_generation` 与 `ResourcePlugin.build_generation` 未在世代构建阶段检查启用态依赖与凭据，而是推迟到 `ProfileAssembly.prepare`（`tinysoul/agent/composition/actions.py:236-243`）激活 `user`、`home_reflection`、`memory_reflection` 三个情景时在 `register_web_actions` / `register_resource_actions` 内重复执行三次。
   - `ProfileAssembly.prepare` 第 242-243 行捕获 `ConfigError` 后无条件转换为 `RuntimeActionBridge().from_config_error(exc)`：
     - 冷启动（`AgentBuilder.build().build_runtime()`）时，缺失 Web/Resource 依赖或缺失 `KIMI_SEARCH_API_KEY` 被吞入 `module="action"`；
     - 运行期配置激活（`ConfigController.apply` / `reload` -> `AgentBuilder._prepare_generation_activation` -> `_build_generation(candidate, map_config_errors=False)`）时，`EndpointConfigurationEngine.apply`（`tinysoul/gateway/endpoint/engine/configuration.py:53-65`）本应捕获 `ConfigError` 返回 422 配置校验错误，却因 `ProfileAssembly.prepare` 提前抛出 `RuntimeException` 而落入 500 `config.activation_failed`。
   - 不把这两个 capability 的运行准备塞进静态 `PluginConfig.validate`：`AgentBuilder.build()` 冻结组成定义，Web/Resource 宿主依赖与凭据就绪属于候选世代物化。Development 模板的静态装配不能因本机尚未准备其可选运行资源而失败；Execution 在 `build_generation` 检查解释器可执行文件提供了既有模式。本次不改变 LLM 或 MCP/ACP 已有静态凭据/绑定校验规则。
3. 诊断键前缀映射缺口：
   - `require_web_dependencies`（`web/dependencies.py:80`）与 `require_resource_dependencies`（`resource/dependencies.py:65`）抛出的 `ConfigError.key` 形如 `capabilities.dependencies.web.<id>` 与 `capabilities.dependencies.resource.<id>`；Resource 有一处精确诊断键断言，未发现仓库内前端消费这些精确旧键。
   - `AgentBuilder._map_owned_config_error`（`tinysoul/agent/composition/builder.py:876-892`）当前仅匹配 `error.key == item.section` 或 `error.key.startswith(item.section + ".")`，无法命中 `capabilities.dependencies.<capability>.*`，会回退到 `RuntimeAgentBridge`（`module="agent"`）。
4. 直接复现已确认冷启动缺失 Kimi 凭据归为 Action，成功世代中两个 dependency helper 各调用三次，真实 ConfigController 经 EndpointConfigurationEngine 的 apply/reload 均返回 500。失败后旧世代仍然保留；本次不是修复激活事务丢失旧世代，而是修正失败分类与归属。

### 2.3 全仓 `Runtime*Bridge` 实现形态差异

核查全仓现有 16 个 `runtime_bridge.py`：

- `action`、`agent`、`archive`、`context`、`endpoint`、`home`、`llm`、`loop`、`memory`、`reflection`、`session`、`workspace` 共 12 个 Bridge 使用 `@dataclass(frozen=True)` 与显式映射，并按实际入口使用公共诊断 helper。Archive / Endpoint 没有 `from_config_error`，不使用 `config_error_payload` 是合理差异；Archive 的原因表名为 `ARCHIVE_RUNTIME_REASONS`，不为变量拼写扩大修改范围。
- 以下 4 个 Bridge 存在偏差：
  1. `tinysoul/plugins/execution/runtime_bridge.py`：缺少 `@dataclass(frozen=True)` 与映射表，手拼 `payload={"error_type": type(error).__name__, "key": error.key}`，未使用 `config_error_payload(error)`；
  2. `tinysoul/plugins/capabilities/expand/runtime_bridge.py`：缺少 `@dataclass(frozen=True)` 与映射表，手拼 payload，未使用 `config_error_payload` / `exception_payload`；
  3. `tinysoul/plugins/capabilities/subagent/runtime_bridge.py`：缺少 `@dataclass(frozen=True)` 与映射表，手拼 payload，未使用 `config_error_payload` / `exception_payload`；
  4. `tinysoul/kernel/jobs/runtime_bridge.py`：已有 `@dataclass(frozen=True)` 与 `_REASONS`，但 `from_config_error` 与 `from_error` 仍手拼字典，未复用 `config_error_payload` / `exception_payload`，且消息选择用内联三元表达式而非显式消息表。

### 2.4 已核实的死抽象、未读私有状态与未使用导入

经全仓 AST 与引用检索逐项核实（已排除跨父类读取属性与公开门面重导出的伪阳性）：

1. **无生产消费者的聚合配置模块**：
   - `tinysoul/plugins/capabilities/config.py`（`CapabilitiesSettings`、`parse_capabilities_settings`）及 `tinysoul/plugins/capabilities/__init__.py` 重导出在 `tinysoul/` 下零生产调用。
   - `[capabilities]` 容器未知子键检查已由 `PluginDefinitions.configure`（`tinysoul/kernel/registration.py:384-390`）通用完成，四个能力插件各自通过 `PluginConfig("capabilities.<name>", ...)` 解析自身子树。
   - 仅 5 个测试文件仍引用 `parse_capabilities_settings`：`tests/plugins/capabilities/test_external_config.py`、`tests/plugins/capabilities/resource/test_resource.py`、`tests/plugins/capabilities/web/test_web.py`、`tests/plugins/capabilities/web/test_real_web_api.py`、`tests/plugins/capabilities/web/backends/test_discovery.py`。
2. **未读私有字段与无消费者构造参数**：
   - `tinysoul/kernel/context/engine.py:1057, 1067`：`ContextEngine.end_turn` 与 `abort_turn` 设置 `self._preparing_turn = False`，该属性未在 `__init__` 初始化且全仓无任何读取。
   - `tinysoul/plugins/capabilities/web/actions.py:140, 144, 266, 315, 324`、`tinysoul/plugins/capabilities/web/plugin.py:59`、`tinysoul/plugins/capabilities/resource/actions.py:63, 67, 141, 166, 176`、`tinysoul/plugins/capabilities/resource/plugin.py:57`：`WebFetchExecutor` 与 `ResourceConversionExecutor` 接收并存储 `self._runtime_bridge`，但 `execute()` 内直接调用 `RuntimeWorkspaceBridge().from_workspace_error(exc)`，`self._runtime_bridge` 从未读取，且测试无任何 `runtime_bridge=` 传参；同文件的 `KimiSearchExecutor`、`WebDiscoveryExecutor` 及其他 capability executor 均不携带该冗余参数。
   - `tinysoul/kernel/loop/phases/phase1.py:56` 与 `tinysoul/kernel/loop/phases/phase2.py:70`：`self._bus = bus` 仅在构造器默认创建 `ContextSignalConsumer(context, bus)` 时使用参数 `bus`（注意 `Phase3Unit._bus` 在 `phase3.py:121` 传给 `ActionExecutionContext.signal_bus`，属于有效字段，保留不动）。
   - `tinysoul/kernel/loop/phases/phase3.py:34, 62, 73`：`Phase3Unit` 不直接捕获 `ContextError`，构造参数 `context_bridge: RuntimeContextBridge | None = None` 与 `self._context_bridge` 全仓无任何传入或读取。
   - `tinysoul/plugins/reflection/turn/entry.py:32-36`：`kind` 仅参与校验和赋值，不参与执行、不核验 runner 与情景是否匹配。唯一构造调用方是 `ReflectionBuilder._build_turn` 和一个 transfer 测试；实际情景选择及非法 kind 拒绝已由 builder 与 `reflection_turn_guidance` 承担。测试保护的是外层 transfer 展开，不是 Entry 的 kind 校验。
3. **非门面模块的未使用导入（10 个文件，12 处）**：
   - `tinysoul/gateway/endpoint/engine/runtime.py:8`：`to_json_object`
   - `tinysoul/infra/config/descriptors/loader.py:6`：`field`
   - `tinysoul/kernel/action/config.py:6`：`field`
   - `tinysoul/plugins/capabilities/expand/actions.py:6, 19`：`dumps_json`、`RetrievalRequest`
   - `tinysoul/plugins/memory/documents/codec.py:9`：`re`
   - `tinysoul/plugins/memory/retrieval/catalog.py:6, 15`：`Mapping`、`MemoryContractError`
   - `tinysoul/plugins/memory/retrieval/models.py:11`：`MemoryKind`
   - `tinysoul/plugins/memory/retrieval/query.py:10`：`MemoryContractError`
   - `tinysoul/plugins/reflection/schedule.py:17`：`ReflectionRuntimeBridge`
   - `tinysoul/plugins/workspace/engine.py:14`：`atomic_write_text`
4. **明确排除的伪阳性（不改动）**：
   - `OpenAIChatAdapter._api_mode` / `OpenAIResponsesAdapter._api_mode`：由基类 `OpenAIAdapter.api_mode`（`tinysoul/llm/adapter/openai/base.py:33`）读取；
   - `UpdatingSessionSegment._source`：由基类 `SessionSegment.inspect`（`tinysoul/plugins/session/projection.py:134`）读取；
   - `tinysoul/llm/config/loader.py`：显式列入 `__all__` 的公开配置门面重导出。

### 2.5 服务共享与静态检查的进一步核对

- `WebCapabilityService` / `ResourceConversionService` 只保有配置、Workspace service、staging 与进程 runner 等依赖；`JoinedOperations`、取消 control、请求与结果按调用传入或创建。`ControlledProcessRunner.run` 的 handle 是局部变量，`ManagedProcessRunner` 只保留进程选项，不保留当前执行 handle。
- 当前三个 profile 的 registrar 已经接收同一个 generation Workspace service；将 capability service 共享到世代不会新增权限，也不会把 profile Context 合并。执行期读取 Workspace 与 staging，不把当日路径或本轮 control 缓存在共享 service。
- Web service 构造会解析 defuddle 可执行文件位置。所有动作关闭时不构造 service，保留不探测可选依赖的行为；服务没有新增长驻连接，因此不添加无事可做的 close callback 或公开 service export。
- 只比较“扫描出的 `*FailureKind` 导入集合均已登记”会放过空集合，例如当前 `ExpandFailure` 导入。新的守卫必须先检查每个 bridge 的归属与非空实际引用，再做集合完整性校验。

---

## 3. 详细改进设计

### 3.1 分离 `expand` 与 `subagent` 的局部请求失败与 Runtime Bridge 失败枚举

参照 `tinysoul/plugins/execution/failures.py` 的清晰分层：

1. `tinysoul/plugins/capabilities/expand/failures.py`：
   - 新增服务于 `RuntimeExpandBridge` 的 `ExpandFailureKind(StrEnum)`：
     - `CONFIGURATION_FAILED = "expand.configuration_failed"`
     - `EXECUTION_CLOSE_FAILED = "expand.execution_close_failed"`
   - `ExpandFailure(StrEnum)` 仅保留 `ExpandRequestError` 实际使用的 9 个局部失败原因（`INVALID_REQUEST`、`UNAVAILABLE`、`SCHEMA`、`ARGUMENTS`、`REMOTE`、`RESULT_UNKNOWN`、`INPUT_REQUIRED`、`CAPACITY`、`SELECTION`），不再包含 `CONFIGURATION_FAILED` 与 `EXECUTION_CLOSE_FAILED`。
2. `tinysoul/plugins/capabilities/subagent/failures.py`：
   - 新增服务于 `RuntimeSubagentBridge` 的 `SubagentFailureKind(StrEnum)`：
     - `CONFIGURATION_FAILED = "subagent.configuration_failed"`
     - `EXECUTION_CLOSE_FAILED = "subagent.execution_close_failed"`
   - `SubagentFailure(StrEnum)` 仅保留 `SubagentRequestError` 实际使用的 3 个局部失败原因（`INVALID_REQUEST`、`UNAVAILABLE`、`BUSY`），移除 Bridge 专用的两个成员及无消费者的 `PROTOCOL`。

外部与跨模块契约影响核对：

- `ExpandAction` 与 `SubagentAction` 捕获 `ExpandRequestError` / `SubagentRequestError` 生成的 `ActionLocalFailure.reason` 字符串完全不变；
- `tinysoul/gateway/endpoint/http/app.py:237` 的 `code=f"expand.{error.reason.value}"` 完全不变；
- `RuntimeExpandBridge` 与 `RuntimeSubagentBridge` 调用 `runtime_exception(...)` 时满足 `kind.value.startswith(f"{module}.")`，产出合法的 `RuntimeException`（`payload["module"]` 为 `"expand"` / `"subagent"`，`payload["kind"]` 为 `"expand.configuration_failed"` 等）。

### 3.2 补齐 `web` / `resource` 启动失败所有权与世代级依赖校验

1. **新增最小 owner `failures.py` 与 `runtime_bridge.py`**：
   - `tinysoul/plugins/capabilities/web/failures.py`：定义 `WebFailureKind(StrEnum)`，仅包含 `CONFIGURATION_FAILED = "web.configuration_failed"`（局部执行失败继续由 `web/errors.py` 与 `ActionLocalFailure` 表达，不进入 Bridge）。
   - `tinysoul/plugins/capabilities/web/runtime_bridge.py`：定义 frozen dataclass `RuntimeWebBridge`，提供映射表与 `from_config_error(error: ConfigError) -> RuntimeException`（映射至 `RUNTIME_STARTUP_FAILED`）。
   - `tinysoul/plugins/capabilities/resource/failures.py`：定义 `ResourceFailureKind(StrEnum)`，仅包含 `CONFIGURATION_FAILED = "resource.configuration_failed"`。
   - `tinysoul/plugins/capabilities/resource/runtime_bridge.py`：定义 frozen dataclass `RuntimeResourceBridge`，提供映射表与 `from_config_error(error: ConfigError) -> RuntimeException`（映射至 `RUNTIME_STARTUP_FAILED`）。
   - 两个 `PluginConfig.failure` 分别绑定对应 Bridge；配置 parser、静态 `validate` 与 `build_generation` 不自行转换 ConfigError。
2. **将依赖诊断键归回 owner 命名空间**：
   - Web：`capabilities.dependencies.web.<id>` → `capabilities.web.dependencies.<id>`。
   - Resource：`capabilities.dependencies.resource.<id>` → `capabilities.resource.dependencies.<id>`。
   - `DependencyRequirement.id` 仍为 `web.http`、`resource.markitdown` 等原值；各 owner 从自身 requirement id 去掉已知 owner 前缀得到后缀，不在 Infra 中解释 capability，不产生 `capabilities.web.dependencies.web.http`。
   - `ConfigError` 的 message、expected 与缺失项数据保持原职责，不重新分类依赖结果；凭据错误键仍是 `capabilities.web.search_by_kimi.api_key_env`。
   - 新键自然匹配现有 `PluginConfig.section`，不修改 `kernel/registration.py` 或 `AgentBuilder._map_owned_config_error`。
   - 这是诊断协议调整，不新增实际 TOML 字段、catalog 项或配置容器。既有 parser 仍拒绝用户写入不支持的 `dependencies` 子树。
3. **世代准备一次，profile 纯注册**：
   - `WebPlugin.build_generation` 对已启用能力调用一次 `require_web_dependencies`，解析一次 Kimi 凭据，然后构造一个 `WebCapabilityService`；Resource 同理检查一次并构造一个 `ResourceConversionService`。
   - 任一动作启用时准备对应 service；全部关闭时不探测可选依赖、不构造 service。启用态来自 capability settings，不由 profile visibility 决定。
   - service 由 generation 的 profile factory 闭包持有；三个 profile 只创建 executor 绑定，不重新解析凭据、查依赖或创建 service。不增加 registry/export；不捕获 profile Context、Turn control 或日路径。
   - 每次 apply/reload 构造新候选时重新准备 service。旧世代继续持有原配置与 service；不增加跨世代缓存或失效状态。
   - registrar 收敛为显式 `builder + settings + service` 输入。`service` 参数无默认值，类型为对应 service 或 `None`；`None` 只表达“该能力全部关闭”，不是请求 registrar 回退构造的模式。已启用却无 service 是 Action 装配契约错误，不重新检查或补建。
   - registrar 只标记 disabled actions 为 unsupported、为 enabled actions 注册 executor。删除其 `workspace`、`staging`、`runtime_env`、`network`、`dependency_checker`、`runtime_bridge` 等旧装配参数及失去用途的导入；实际执行仍通过 service 使用所需依赖。
   - 直接测试 registrar 时显式给出 service 或关闭态 `None`；缺失依赖/凭据的测试转到 dependency helper 或插件世代准备，不为保留旧测试继续支持旧入口。
4. **保持调用入口对失败出口的决定权**：
   - 删除 `ProfileAssembly.prepare` 中将 `ConfigError` 无条件转成 Action RuntimeException 的分支及无用导入；保留真正的 ActionError、RegistrationError 与 ContextError 分类。
   - 冷启动由 `AgentBuilder._build` / 静态编译的既有捕获边界调用 owner Bridge。
   - 热激活中候选构建抛出 ConfigError，沿既有资源回收和 `handle.fail_activation()` 路径传播到 ConfigController，再由 Endpoint 映射为 422。
   - 不在 Endpoint 捕获所有 RuntimeException 并改成 422；非配置激活失败仍是 500 `config.activation_failed`。

修改后各入口的目标行为：

| 入口 | Web/Resource 就绪检查 | 配置失败出口与状态 |
| --- | --- | --- |
| `AgentBuilder.build()` | 只解析静态配置，不检查这两个 capability 的宿主依赖或运行凭据 | 静态配置非法由对应 owner 表达启动失败 |
| 初次 `build_runtime()` | 每个启用 capability 准备一次 | `runtime.startup_failed`，payload 标明真实 owner |
| `PATCH /v2/config` | 保持候选静态校验，不新增这两个 capability 的运行就绪检查 | 可保存待激活配置；不更换当前世代 |
| `POST /v2/config/apply` | 新候选世代准备一次 | 422 `config.invalid`；准备失败不保存本次修改，旧世代与原有 pending 配置保留 |
| `POST /v2/config/reload` | 对已保存配置准备新候选一次 | 422 `config.invalid`；旧世代保留，已保存候选仍留在磁盘待处理 |

此表仅规定本次 Web/Resource 检查，不更改 LLM 等其他 owner 的静态校验政策，也不重写 ConfigController 的事务、来源恢复和退休清理。

### 3.3 统一全仓 `Runtime*Bridge` 标准形态

对齐 `RuntimeActionBridge` / `RuntimeLLMBridge` 参考实现，统一以下 6 个 Bridge（4 个既有 + 2 个新增）：

- `tinysoul/plugins/execution/runtime_bridge.py`（`RuntimeExecutionBridge`）
- `tinysoul/plugins/capabilities/expand/runtime_bridge.py`（`RuntimeExpandBridge`）
- `tinysoul/plugins/capabilities/subagent/runtime_bridge.py`（`RuntimeSubagentBridge`）
- `tinysoul/kernel/jobs/runtime_bridge.py`（`RuntimeJobsBridge`）
- `tinysoul/plugins/capabilities/web/runtime_bridge.py`（`RuntimeWebBridge`）
- `tinysoul/plugins/capabilities/resource/runtime_bridge.py`（`RuntimeResourceBridge`）

统一规范：

1. 上述六个 Bridge 声明为 `@dataclass(frozen=True)`，模块顶层提供显式原因与消息映射；新改映射采用 `*_RUNTIME_REASON_MAP` / `*_FAILURE_MESSAGES` 名称，不机械重命名其他已合格模块。
2. 实际存在的 `from_config_error` 入口统一使用 `config_error_payload(error)`，输出有界 `{"key": error.key[:256], "expected": error.expected[:256]}`，不复制 source、value 或异常原文。此 helper 是字段选择和截断，不是任意字符串脱敏器；key/expected 仍由 owner 保证适宜投影。
3. 普通异常入口（如 `close_failed`、`from_error`）使用 `exception_payload(error)` 记录 `error_type`；不增加没有消费者的动态字段或公共入口。ConfigError 投影不为兼容手拼字典继续保留重复 `error_type`。
4. 原有 reason 和失败摘要语义不变；不扩展失败种类，不把单次 Action 局部失败纳入 Bridge。
5. 必要执行停止失败仍映射到现有 `runtime.agent_end`；generation 退休/关闭继续使用既有 cleanup diagnostics 路径。修复 Bridge 构造不代表任意 close callback 都能越过清理边界强制进入 Trap，不改变主结果与附属关闭诊断的优先级。

### 3.4 闭合 `tests/test_architecture.py` 静态守卫

1. 在 `test_runtime_failure_kind_values_are_module_qualified` 参数列表中新增：
   - `("expand", ExpandFailureKind)`
   - `("subagent", SubagentFailureKind)`
   - `("web", WebFailureKind)`
   - `("resource", ResourceFailureKind)`
2. 提取共享常量元组 `REGISTERED_RUNTIME_FAILURE_KINDS`，保留 `(module, enum_type)` 为单一测试登记源：
   - 根据枚举完整 Python 模块身份定位所属 `runtime_bridge.py`，与 `tinysoul/` 实际发现的 bridge 文件集合比较；新增未登记 bridge、悬空登记和重复归属都失败。
   - 复用现有 `_source_tree` 缓存和相对导入解析方式；按完整模块、原符号与本地 alias 解析实际引用，不只匹配短类名或名称后缀。
   - 每个 bridge 必须非空引用所属登记枚举，且该枚举在 AST 中有实际使用；只有 `ExpandFailure` 之类局部枚举、空导入集合或借用其他 owner 枚举均失败。
   - 枚举值必须属于登记 owner 的非空命名空间；不允许只导入一个无使用的合格枚举来让旧错误路径混过守卫。
   - `infra` / `runtime` 下不得出现 owner bridge；继续保留既有依赖方向守卫。
3. 为上述发现/匹配逻辑补少量合成 AST 反例：无合格枚举、仅导入未使用、错误 owner，以及相对导入/alias 的正例。测试 helper 留在架构测试内，不建立生产注册平台。
4. 静态检查不能证明每个分支都构造正确异常；新增及改动 Bridge 的公开入口还须用行为测试验证 `module/kind/reason`、JSON 安全与配置诊断边界。不以冻结声明、表名或固定消息全文快照替代这些测试。

### 3.5 清理死抽象、未读字段与未使用导入

1. 删除 `tinysoul/plugins/capabilities/config.py`，并将 `tinysoul/plugins/capabilities/__init__.py` 收敛为纯包说明（不导出已删除的聚合配置符号）；将 5 个测试文件中的 `parse_capabilities_settings(...)` 直接替换为对应子能力的 `parse_expand_settings`、`parse_resource_settings`、`parse_web_settings`（对 `ConfigEnvironment` 使用 `parse_section("capabilities.<name>", parse_<name>_settings)`）。
2. 移除未读私有字段与无消费者参数：
   - `ContextEngine`（`tinysoul/kernel/context/engine.py`）：删除 `end_turn` 与 `abort_turn` 中的 `self._preparing_turn = False`；
   - `WebFetchExecutor`、`register_web_actions`、`WebPlugin`（`tinysoul/plugins/capabilities/web/{actions,plugin}.py`）：删除未读的 `runtime_bridge` 参数与 `self._runtime_bridge` 属性（`WebPlugin` 同步移除不再需要的 `RuntimeWorkspaceBridge` 导入）；
   - `ResourceConversionExecutor`、`register_resource_actions`、`ResourcePlugin`（`tinysoul/plugins/capabilities/resource/{actions,plugin}.py`）：删除未读的 `runtime_bridge` 参数与 `self._runtime_bridge` 属性（`ResourcePlugin` 同步移除不再需要的 `RuntimeWorkspaceBridge` 导入）；
   - `Phase1Unit`、`Phase2Unit`（`tinysoul/kernel/loop/phases/{phase1,phase2}.py`）：保留构造参数 `bus: SignalBus`（用于默认构造 `ContextSignalConsumer(context, bus)`），删除后续未读取的 `self._bus = bus`；
   - `Phase3Unit`（`tinysoul/kernel/loop/phases/phase3.py`）：删除无任何调用方传入且内部不使用的 `context_bridge` 参数、`self._context_bridge` 属性及 `RuntimeContextBridge` 导入；
   - `ReflectionTurnEntry`（`tinysoul/plugins/reflection/turn/entry.py`）：删除无消费者的 `kind` 参数、局部校验、`self._kind` 及无用异常导入；同步修改 `ReflectionBuilder._build_turn` 和 transfer 测试的构造调用。Entry 继续展开非 Turn 的外层 transfer；Home/Memory 的真实选择与校验留在 builder/`reflection_turn_guidance`，不改提示词与情景策略。
3. 删除 §2.4 第 3 点列出的 10 个文件中的 12 处未使用导入。上述接口调整产生的无用导入同轮清理，不将“无消费者”扩大为未使用整个模块的推断。
4. 聚合 parser 删除后保留通用容器未知子键拒绝测试；不把该契约复制到每个子能力。公开 registrar 名称可以继续由能力包导出，但旧签名不保留兼容包装。

---

## 4. 文件与改动范围

### 4.1 新增文件（4 个）

| 文件路径 | 职责说明 |
| --- | --- |
| `tinysoul/plugins/capabilities/web/failures.py` | 声明 `WebFailureKind`（`web.configuration_failed`） |
| `tinysoul/plugins/capabilities/web/runtime_bridge.py` | 声明 `RuntimeWebBridge`，映射 Web 配置、依赖与凭据启动失败 |
| `tinysoul/plugins/capabilities/resource/failures.py` | 声明 `ResourceFailureKind`（`resource.configuration_failed`） |
| `tinysoul/plugins/capabilities/resource/runtime_bridge.py` | 声明 `RuntimeResourceBridge`，映射 Resource 配置与依赖启动失败 |

### 4.2 删除文件（1 个）

| 文件路径 | 删除依据 |
| --- | --- |
| `tinysoul/plugins/capabilities/config.py` | 无任何生产消费者；容器未知子键校验已由 `PluginDefinitions.configure` 统一承担 |

### 4.3 修改生产文件（30 个）

| 文件路径 | 改动要点 |
| --- | --- |
| `tinysoul/plugins/capabilities/expand/failures.py` | 拆分 `ExpandFailureKind`（带 `expand.` 前缀）与局部 `ExpandFailure` |
| `tinysoul/plugins/capabilities/expand/runtime_bridge.py` | 改用 `ExpandFailureKind`、frozen dataclass、显式映射表、`config_error_payload` 与 `exception_payload` |
| `tinysoul/plugins/capabilities/subagent/failures.py` | 拆分 `SubagentFailureKind`（带 `subagent.` 前缀）与局部 `SubagentFailure`，移除无消费者的 `PROTOCOL` |
| `tinysoul/plugins/capabilities/subagent/runtime_bridge.py` | 改用 `SubagentFailureKind`、frozen dataclass、显式映射表、`config_error_payload` 与 `exception_payload` |
| `tinysoul/plugins/execution/runtime_bridge.py` | 统一为 frozen dataclass、显式映射表与 `config_error_payload` |
| `tinysoul/kernel/jobs/runtime_bridge.py` | 统一显式消息映射表，复用 `config_error_payload` 与 `exception_payload` |
| `tinysoul/agent/composition/actions.py` | `ProfileAssembly.prepare` 移除对 `ConfigError` 的 `RuntimeActionBridge` 拦截（及无用 `ConfigError` 导入） |
| `tinysoul/plugins/capabilities/web/plugin.py` | 绑定 `RuntimeWebBridge`；世代内检查一次并构造共享 service，profile 仅注册 |
| `tinysoul/plugins/capabilities/web/actions.py` | registrar 改为 settings + 显式 service 输入；删除检查、构造、冗余参数及 executor 的未读 bridge |
| `tinysoul/plugins/capabilities/web/dependencies.py` | 依赖诊断键改为 `capabilities.web.dependencies.*`，不改 requirement id |
| `tinysoul/plugins/capabilities/resource/plugin.py` | 绑定 `RuntimeResourceBridge`；世代内检查一次并构造共享 service，profile 仅注册 |
| `tinysoul/plugins/capabilities/resource/actions.py` | registrar 改为 settings + 显式 service 输入；删除检查、构造、冗余参数及 executor 的未读 bridge |
| `tinysoul/plugins/capabilities/resource/dependencies.py` | 依赖诊断键改为 `capabilities.resource.dependencies.*`，不改 requirement id |
| `tinysoul/plugins/capabilities/__init__.py` | 移除已删除的 `CapabilitiesSettings`、`parse_capabilities_settings` 导出 |
| `tinysoul/kernel/context/engine.py` | 移除未读的 `self._preparing_turn = False` |
| `tinysoul/kernel/loop/phases/phase1.py` | 移除未读的 `self._bus = bus` |
| `tinysoul/kernel/loop/phases/phase2.py` | 移除未读的 `self._bus = bus` |
| `tinysoul/kernel/loop/phases/phase3.py` | 移除无消费者的 `context_bridge` 参数、`self._context_bridge` 属性与 `RuntimeContextBridge` 导入 |
| `tinysoul/plugins/reflection/turn/entry.py` | 删除 `kind` 参数、冗余校验、未读属性与无用导入，保留 transfer 传播 |
| `tinysoul/plugins/reflection/builder.py` | 不再向 `ReflectionTurnEntry` 传 kind，保留真实 profile 选择 |
| `tinysoul/gateway/endpoint/engine/runtime.py` | 清理未使用导入 `to_json_object` |
| `tinysoul/infra/config/descriptors/loader.py` | 清理未使用导入 `field` |
| `tinysoul/kernel/action/config.py` | 清理未使用导入 `field` |
| `tinysoul/plugins/capabilities/expand/actions.py` | 清理未使用导入 `dumps_json`、`RetrievalRequest` |
| `tinysoul/plugins/memory/documents/codec.py` | 清理未使用导入 `re` |
| `tinysoul/plugins/memory/retrieval/catalog.py` | 清理未使用导入 `Mapping`、`MemoryContractError` |
| `tinysoul/plugins/memory/retrieval/models.py` | 清理未使用导入 `MemoryKind` |
| `tinysoul/plugins/memory/retrieval/query.py` | 清理未使用导入 `MemoryContractError` |
| `tinysoul/plugins/reflection/schedule.py` | 清理未使用导入 `ReflectionRuntimeBridge` |
| `tinysoul/plugins/workspace/engine.py` | 清理未使用导入 `atomic_write_text` |

以上为 30 个现有生产文件修改项（20 个接口/装配/字段清理文件、10 个仅清理导入的文件），另新增 4 个、删除 1 个。`kernel/registration.py`、`agent/composition/builder.py`、两个 capability 的 service 实现及 Endpoint 路由/错误映射无需为本方案修改；如实施发现必须扩展这些边界，应先记录原因并复核设计，不顺手扩张范围。

### 4.4 修改测试与设计文档

| 文件路径 | 改动要点 |
| --- | --- |
| `tests/test_architecture.py` | 单一枚举登记、非空/完整身份/实际引用守卫及最小反例测试 |
| `tests/agent/composition/test_build_failures.py` | 四个 capability 的冷启动归属；静态构建不探测 Web/Resource；世代准备一次和 visibility 不绕过检查 |
| `tests/kernel/test_registration.py` | 补齐通用容器未知子键在 owner parser 前被拒绝的回归 |
| `tests/plugins/capabilities/expand/test_engine.py` | `from_config_error` / `close_failed` 契约，局部短原因不变 |
| `tests/plugins/capabilities/subagent/test_engine.py` | `from_config_error` / `close_failed` 契约，局部短原因不变 |
| `tests/kernel/jobs/test_registry.py` | 改动 Bridge 的配置载荷与各 Job 边界失败映射，不重复完整监督场景 |
| `tests/plugins/execution/test_engine.py` | Execution 配置 Bridge 的有界诊断契约 |
| `tests/plugins/capabilities/test_external_config.py` | 迁移 `parse_capabilities_settings` 至 `parse_expand_settings` |
| `tests/plugins/capabilities/resource/test_resource.py` | parser 与 registrar 迁移、owner Bridge、依赖新键、关闭态无准备 |
| `tests/plugins/capabilities/web/test_web.py` | parser 与 registrar 迁移、owner Bridge、依赖新键；原 registrar 凭据校验测试迁移到真正准备边界 |
| `tests/plugins/capabilities/web/test_real_web_api.py` | 迁移 `parse_capabilities_settings` 至 `parse_web_settings` |
| `tests/plugins/capabilities/web/backends/test_discovery.py` | 迁移 `parse_capabilities_settings` 至 `parse_web_settings` |
| `tests/plugins/reflection/test_turn_boundaries.py` | 移除 Entry.kind 传参，保留外层 transfer 不降级的断言 |
| `tests/gateway/endpoint/test_agent_protocol.py` | 真 Agent + ASGI HTTP 的 apply/reload 422 回归、候选文件/旧世代状态、修复候选后可重新激活 |
| `tests/gateway/endpoint/test_endpoint_api.py` | 保留并按需补齐非配置激活失败仍返回 500、Expand 局部错误码未双重加前缀 |
| `docs/design/capabilities.md` | 各 owner 失败归属、世代准备和纯注册职责 |
| `docs/design/agent.md` | 区分静态装配与能力运行就绪，说明 profile 复用世代服务及配置失败出口 |
| `docs/endpoint/configuration.md` | 422/500 分类、依赖诊断新键、PATCH/apply/reload 的候选与旧世代状态 |

核对发现 `tests/kernel/test_registration.py` 原先覆盖声明归属、但没有 configure 容器未知子键的直接用例，因此补一个 owner 回归，不新增不存在的 `error_prefixes` 测试。`docs/design/runtime.md` 已复核与既有三层失败契约一致，无需添加重复条款。Expand/Subagent 的轻量 Bridge 测试进入 Fast，原真实 MCP/ACP 测试改为逐项 integration 标记，不改变其套件归属。不新增测试文件或生产框架。

---

## 5. 分阶段执行步骤

P0 为 §0 已完成的分析与准入检查。每阶段的代码、相关测试与受影响文档一起推进，实际完成情况如下。

### P1：失败枚举与 Bridge 契约（已完成）

- [x] 拆分 `expand/failures.py`（`ExpandFailureKind` vs `ExpandFailure`）与 `subagent/failures.py`（`SubagentFailureKind` vs `SubagentFailure`，移除 `PROTOCOL`）。
- [x] 新增 `web/{failures,runtime_bridge}.py` 与 `resource/{failures,runtime_bridge}.py`。
- [x] 对齐六个 Bridge 的形态和按入口选择的诊断 helper，不扩展 reason、空接口或无消费者字段。
- [x] 补公开入口行为测试与局部短原因回归，同时完成枚举登记和 AST 非空/归属/使用守卫。
- [x] 复核 Runtime 设计，运行对应聚焦测试与 Fast；记录结果，不将绿色结构测试代替后续装配验收。

### P2：世代准备与配置失败出口（已完成）

- [x] 调整两个 dependency helper 的诊断键，保留 requirement id；更新精确断言，不修改插件配置协议或 Agent 归属映射。
- [x] Web/Resource 接入自有 Bridge，在世代内检查和构造 service 一次；全部关闭不构造。
- [x] 将 registrar 改为纯注册并迁移调用方；不保留旧签名、回退构造或跳过检查开关。
- [x] 移除 `ProfileAssembly.prepare` 中将 `ConfigError` 强制包装为 `RuntimeActionBridge` 的分支。
- [x] 完成静态构建、准备次数、visibility、冷启动与真实 HTTP apply/reload 回归；覆盖 422/500 分类和候选失败后可重新激活。
- [x] 同步 Capabilities、Agent 设计与 Endpoint 配置协议，运行聚焦测试与 Fast。

### P3：死抽象与冗余状态清理（已完成）

- [x] 删除 `tinysoul/plugins/capabilities/config.py`，收敛 `tinysoul/plugins/capabilities/__init__.py`，并将 5 个 capability 测试文件迁移至各子能力 `parse_<name>_settings`。
- [x] 清理 Context、Phase1/2/3 的指定未读字段/参数；核对 P2 已删除 Web/Resource 冗余 bridge。
- [x] 删除 Reflection Entry.kind 的参数、校验与属性，更新 builder/test；保留实际情景校验和外层 transfer 传播。
- [x] 清理 10 个非门面模块中的 12 处未使用导入，以及本轮接口调整产生的无用导入。
- [x] 核对门面、继承属性及通用容器校验未受破坏；运行聚焦测试与 Fast。

### P4：交付核对与计划归档（已完成）

- [x] 逐项复核 §7 验收矩阵、实际文件差异与同期文档；不使用“全仓零死抽象”代替本计划的有限清理范围。
- [x] 运行完整 Full 本地门禁与 `ty check`；记录报告、失败及解决证据，不跳过用例或放宽业务断言换取通过。
- [x] 检查 Endpoint 诊断键变更和已删除 Python 接口无残留引用；检查无前端、固定模型文案或无关结构变化。
- [x] 全部验收项通过后，将本计划条目更新为已完成，状态改为 `done`，重命名为 `20261123-done-Runtime失败桥接统一与死抽象清理执行计划.md` 并移入 `docs/analysis/done/`。

---

## 6. 验证安排与本地门禁命令

### 6.1 测试分工与真实风险

| 契约 | 主要覆盖位置 | 必须区分的行为 |
| --- | --- | --- |
| Bridge 转换 | 六个 owner 对应测试 | 合法输入返回 RuntimeException；配置有界 key/expected；close 保留 Agent end；不泄漏异常原文/配置值；局部 reason 不变 |
| 依赖诊断 | Web/Resource owner 测试 | 新 owner 键正确，requirement id 不变，关闭态无可选依赖探测 |
| 静态与世代边界 | Agent composition | build 不检查这两个 capability 的运行就绪；成功世代各启用 capability 准备一次而非三/四次；隐藏 action 不跳过检查 |
| 服务/注册分工 | capability 与 composition 测试 | 构造一次，profile 注册不构造；启用但缺失 service 是契约错误；关闭态没有 service 仍正确标记 unsupported |
| 冷启动归属 | Agent composition | Expand/Subagent 配置错误；Web 配置/凭据/依赖错误；Resource 配置/依赖错误准确归属 |
| 热激活 | Endpoint Agent 集成 | apply 和 reload 均走真实 ConfigController、候选构建与 HTTP 映射，不只伪造一份异常响应 |
| 保留既有失败边界 | Endpoint API / Reflection / Loop | 非配置 Runtime 激活错误仍 500；外层 transfer 不降级；有效字段不误删 |
| 架构守卫 | tests/test_architecture.py | 未登记、空匹配、仅导入、错误 owner 被拒绝；relative import / alias 可正确识别 |

热激活用有区分力的代表路径覆盖 Web 缺失凭据和 Resource 缺失依赖，各覆盖 apply/reload；穷尽依赖分类由 owner 单测承担。使用 FakeLLM 和受控 dependency checker，不触网、不读取真实凭据、不依赖本机是否安装可选工具。资源启用参数使用测试自有有效配置，避免无关依赖先行失败。

HTTP 集成除状态码外还核对：

- `details.key` 指向预期 owner；返回中不包含配置原值或凭据。
- apply 准备失败时磁盘保持调用前状态，原有 pending 配置不丢失；reload 失败时已保存候选仍存在。
- 当前 generation 身份和既有服务保持有效，不只是返回一句“旧世代仍有效”。
- 失败激活解除占用；修正候选后可成功激活新世代。沿既有 cleanup 机制释放测试资源。
- Agent/ConfigController 的 project root 与 ConfigEnvironment 的根保持一致，不能因 fixture 根不匹配产生 `config.include` 而误判为目标回归通过。

### 6.2 开发与交付命令

1. **聚焦验证（按阶段运行；集成用例显式选择 Full）**：

```powershell
uv run --locked --extra dev python scripts/test.py tests/test_architecture.py tests/kernel/test_registration.py tests/kernel/jobs tests/plugins/execution tests/plugins/capabilities tests/plugins/reflection/test_turn_boundaries.py tests/kernel/loop/phases
uv run --locked --extra dev python scripts/test.py --suite full tests/agent/composition/test_build_failures.py tests/gateway/endpoint/test_agent_protocol.py tests/gateway/endpoint/test_endpoint_api.py tests/gateway/project/test_initializer.py
```

2. **日常 Fast 回归**：

```powershell
uv run --locked --extra dev python scripts/test.py
```

3. **交付前完整本地门禁（必须全部通过）**：

```powershell
uv run --locked --extra dev python scripts/test.py --suite full
uv run --locked --extra dev ty check
```

`test_real_web_api.py` 的 parser 迁移通过导入、收集与类型检查核对；真实 provider 用例仍需显式 external 开关及凭据，不为本计划运行公网测试。完整 Full 不包含 External，不得把 external skip 声称为真实调用通过。

### 6.3 已有证据与后续记录

| 阶段 | 证据 | 能支持的结论 |
| --- | --- | --- |
| 审阅复现，基线 `b4f91b95` | 四个 MCP/ACP Bridge 调用均抛 RuntimeContractError | 失败枚举与 Runtime 命名空间契约确实冲突 |
| 审阅复现，同基线 | Web/Resource 静态配置归 Action、旧依赖键路由归 Agent；一次成功世代 dependency helper 各调用三次 | 所有权错位与重复检查属实 |
| 审阅复现，同基线 | 隔离项目 + FakeLLM + 受控依赖检查：EndpointConfigurationEngine apply/reload 缺失 Kimi 凭据均返回 500，旧世代保留 | 热激活分类错误属实；当时未执行 HTTP 传输，实施期已补 ASGI 回归 |
| 审阅聚焦测试，同基线 | `uv run --locked --extra dev python scripts/test.py --suite full tests/test_architecture.py tests/agent/composition/test_build_failures.py`：41 passed，1 个 pytest cache 写入权限 warning | 既有测试通过但未覆盖缺陷；不是修复后的验收结果 |
| 准备轮分析 | 服务/进程局部状态、关闭态构造、测试与配置事务路径进一步静态核对 | 方案具备实施条件；当时尚未修改生产代码 |
| 准备轮文档验证 | `git diff --check` 通过；清单脚本核对新增 4、删除 1、修改 30 个生产文件，现有文件/文档链接/测试命令路径有效 | 准备状态为 ready，不替代业务测试与完整门禁 |
| P1 聚焦 | Full 选择架构、Jobs、Execution、Expand/Subagent owner 文件，`-k 'bridge or runtime_failure_kind'`：33 passed；报告 `7536dc7f8d604b4c87007967e7847786` | 四个既有 Bridge 修复和命名空间守卫通过；当时 Web/Resource owner 测试随后补齐 |
| P1–P3 聚焦 | §6.2 第一条命令：193 passed / 30 deselected；报告 `02b008f7feff4313bf7b55d3d2c208f6` | capability、Phase、Reflection、registration 与架构主线通过 |
| Agent/HTTP/初始化聚焦 | §6.2 第二条命令：69 passed；报告 `5f660a0fcd04451e917179b052f608bc` | 真 Agent + ASGI 的 422/500、旧世代/文件保留、再次激活、初始化通过 |
| 默认 Fast | `uv run --locked --extra dev python scripts/test.py`：1386 passed / 155 deselected；报告 `3820ebe615024993a6584bbfafa6ce3c` | 包含补充的容器未知子键守卫及已进入 Fast 的 MCP/ACP Bridge 测试 |
| 类型检查 | `uv run --locked --extra dev ty check`：All checks passed | 未使用宽泛忽略或新增 Any 掩盖边界 |
| External 收集 | `uv run --locked --extra dev python scripts/test.py --suite external --collect-only tests/plugins/capabilities/web/test_real_web_api.py`：1 test collected；报告 `32190527521b414abadee969f912eabd` | parser 迁移后可导入与收集；未执行真实 Web 调用 |
| P4 差异与 AST 核对 | 35 个生产文件操作与 §4 完全一致；18 个 owner Bridge 为 frozen dataclass；12 处指定导入、7 个未读属性及旧接口引用清理完毕 | 无 Runtime 内核、通用注册/归属映射、模型固定文案或前端改动 |
| 完整 Full | `uv run --locked --extra dev python scripts/test.py --suite full`：1538 passed / 3 deselected，185.33s；报告 `9e5923e2ff2347879438378d15a3dbdf` | 全部非 External 本地门禁通过，包含真实本机 MCP/ACP、进程、Agent/HTTP、初始化和 wheel 验收 |

报告位于 Git 忽略的 `.local-test/reports/<报告 ID>/`。实现中曾发现测试构造的 unavailable DependencyCheck 未填写缺失项、测试误依赖正式模板关闭态、HTTP 动态 kwargs 不满足具体参数类型；分别修正测试输入、显式关闭无关 adapter、改用具名 json 参数。没有修改业务断言、跳过测试或加入类型忽略。审阅阶段的 cache warning 未在上述通过的实施检查中出现。

---

## 7. 完成标准与规约核对

以下验收项均已对照实现、文档与 §6 实测结果核对。

- [x] **A1（Bridge 与局部协议）**：六个新增/改动 Bridge 的合法输入返回正确 RuntimeException；Expand/Subagent 不再因缺少前缀触发 RuntimeContractError。局部短原因及 `expand.<reason>` HTTP 错误码不变。
- [x] **A2（owner 诊断归属）**：Web/Resource 配置及新依赖诊断键在冷启动准确归属对应 owner；不保留旧诊断键 alias，不新增配置范围声明或实际 dependencies 配置字段。
- [x] **A3（唯一准备路径）**：Web/Resource 静态 build 不做运行就绪检查；每个启用 capability 每个候选世代准备一次，三个 profile 纯注册；全部关闭不探测/构造，visibility 不绕过就绪检查。
- [x] **A4（激活分类与状态）**：apply/reload 的能力配置失败经 HTTP 返回 422；真正非配置 Runtime 激活失败仍 500。旧世代/服务有效、磁盘候选语义正确，失败后可再次激活；不新增恢复状态机。
- [x] **A5（Bridge 形态与载荷）**：改动 Bridge 使用 frozen dataclass、显式映射和适用的公共 helper；消息保持摘要语义，载荷有界且 JSON 安全。无空配置入口、通用基类或变量名清理扩散。
- [x] **A6（架构守卫）**：所有 owner bridge 纳入枚举登记核对；空匹配、未使用导入、错 owner、漏登记不能通过，Infra/Runtime 无反向 bridge；行为测试验证真实转换而非只验证源码形态。
- [x] **A7（有限清理完整）**：聚合 parser、指定未读字段、冗余 bridge 参数、Reflection Entry.kind 和 12 处导入清理完成；有效 bus 参数、Phase3 bus、继承读取、真实情景校验与公开有效门面保留。
- [x] **A8（文档与门禁）**：Capabilities/Agent 设计及 Endpoint 协议与实际行为同步；Runtime 设计复核完成；聚焦、Fast、完整 Full 和 ty 均有实际结果记录，交付门禁通过后才标记 done 并归档。

## 8. AGENTS.md 与实际实现逐项复核

| 规约/计划项 | 实际实现与核对证据 |
| --- | --- |
| 三层失败与 owner 所有权（A1/A2） | Expand/Subagent 分离局部枚举；六个 Bridge 的入口测试核对 module/kind/reason 和诊断字段；Web/Resource 插件绑定自有 Bridge。冷启动参数化覆盖四个 capability，旧局部 Action reason 与 Expand HTTP code 保留 |
| 唯一世代生命周期（A3） | 两个 `plugin.py` 完成一次准备；registrar 只消费 settings/service。composition 测试同时观察 dependency helper、service 构造与三个 profile 注册，关闭态零准备，启用态一次准备。执行 service、进程资源和 profile Context 的实现未复制或改写 |
| 失败分类不重建激活状态机（A4） | `ProfileAssembly.prepare` 仅移除 ConfigError 的越权分支。AgentBuilder、PluginDefinitions、ConfigController、Endpoint 生产映射均未修改；真实 HTTP 回归验证失败前后 generation 身份与 Workspace service 有效、磁盘字节保持、pending 仍在、修正后激活成功 |
| 明确类型、有限诊断与控制原因（A5） | 新失败标识为 StrEnum；Bridge frozen；配置 helper 不携带 source/value/message。新增缺失 service 拒绝使用 ActionContractError，属于装配契约，不抛裸内置异常；没有新增 broad except、Runtime reason、Trap handler 或恢复链 |
| 测试保护真实风险（A6） | AST 守卫用完整身份、文件集合和成员使用检查；合成反例覆盖局部枚举、未使用导入和错 owner。轻量 Bridge 用例在 Fast，真实 MCP/ACP 仍 integration；容器未知子键只在 registration owner 补一次 |
| 死抽象与误删防护（A7） | 删除聚合 parser 和冗余注入，不保留 alias。保留 Phase1/2 bus 参数、Phase3 bus 使用、真实 Reflection kind 选择/校验、外层 transfer 传播及继承读取字段；AST 与引用检索核对指定清单 |
| 文案、依赖方向及接口同步（A8） | 新错误文案只用于 Runtime/装配诊断，不进入模型固定提示包。Capabilities/Agent 设计和 Endpoint 配置协议已同步；Runtime 设计契约原文仍适用。无新依赖、锁文件变化、前端或通用基础设施扩张 |

实际范围与计划无生产边界偏离。唯一测试范围补充是 `tests/kernel/test_registration.py` 的未知容器子键回归；轻量测试 marker 调整用于落实 AGENTS.md 的套件语义。完整门禁已通过，计划在逐项核对后完成归档；未运行真实 provider 或公网 External 测试，未执行 Git 提交或推送。
