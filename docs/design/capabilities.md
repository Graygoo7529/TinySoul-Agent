# Capabilities 设计

## 定位

Capabilities 承载通过 Action 使用的外围业务能力，不拥有独立持久化或 Link namespace。能力可以持有连接、协议会话和派生目录，由 Agent 的 Turn、日与世代生命周期管理；它不建立独立调度器，也不复制 Workspace、Home、Memory、Session 的业务事实。

一个 capability 负责自身的业务配置、依赖需求、service/client/converter 和 Action executor 适配。Action 继续拥有 Catalog、Phase2 工具协议、Phase3 调度、超时和结果回放；Infra 提供配置、依赖检查、标准 schema 校验和受控传输；Agent 组合 owner 的装配和关闭顺序。

## 组织原则

```text
tinysoul/plugins/capabilities/
  <capability>/
    config.py
    dependencies.py
    errors.py
    models.py
    service.py
    actions.py
```

只有存在真实能力时才建立 capability 包。目录可以按实际复杂度增减文件，不为未来扩展保留空 client、provider 或 plugin 抽象。

`actions.py` 是 capability 接入 ActionEngine 的边界，只包含 ActionExecutor、参数解析、ActionResult 映射、Workspace/Signal 协作和 registrar。转换、检索、计算等核心业务逻辑保留在 service/converter/client 中。

## 配置

Capabilities 共用 `[capabilities]` 顶层命名空间，但项目文件按能力拆分：

```text
configs/capabilities/
  resource.toml
  web.toml
  expand.toml
  subagent.toml
```

文件拆分只影响维护位置，不改变 TOML section identity。每个 capability parser 只解释自己的子树并拒绝未知键。Infra 的 ConfigEnvironment 负责 include、合并、来源诊断和环境覆盖，不拥有 capability 业务字段。

项目 Action Catalog 的 visibility 负责情景选择，capability 配置负责后端、adapter、依赖、凭据与资源上限。registrar 显式注册获授动作，缺少支持的动作标为 unsupported；最终有效集合为 grants、情景选择和 backend 支持的交集。关闭动作可见性不跳过已启用后端的依赖检查。

## 依赖需求与可用性

依赖需求由 capability 代码根据 effective settings 生成，项目配置只表达启用的 action、adapter 和 feature，不手工重复 Python package 名称。这样配置不能通过漏写 requirement 把不完整环境伪装为可用。

Infra 提供通用、无业务知识的 DependencyChecker：

- `DependencyRequirement` 描述稳定 requirement id、distribution、import module 和可选 executable；
- `DependencyCheck` 描述检测到的版本、module 可导入性、executable 解析路径和稳定失败原因；
- checker 使用 `importlib.metadata`、`importlib.util` 与 `shutil.which` 检查当前解释器和进程环境，不执行安装、不读取业务配置、不改变进程环境；
- capability 可以在基础检查后执行 adapter-specific probe，但 probe 仍由 capability 自己拥有。

可用性规则固定为：

```text
capability enabled=false
  -> 不检查该 capability 的可选依赖、不注册 executor、标记对应 Action unsupported

capability enabled=true + dependencies available
  -> 注册 executor，Action 获得 runtime support

capability enabled=true + dependencies unavailable
  -> Agent 启动失败，报告 action、requirement、distribution/module/executable 和原因
```

后端 support 与 Action visibility 分别计算。若 capability 仍启用，其依赖与凭据错误必须使候选 Generation 失败。

启动检查不能替代执行期防御。环境在启动后被修改、worker 导入失败或外部二进制不可运行时，单次 action 仍返回局部失败；配置形态错误和 capability 装配不变量失败保留模块边界语义。

## Action 与实现依赖

Action 名称由用户可区分的行为决定。通常不应只因实现库不同而复制同义 action；但当不同 adapter 具有明确的格式范围、输出结构、失败模式和选择倾向时，可以在同一 domain 暴露多个具名 action，并通过 Catalog semantic 与 domain skill 说明选择规则。

Capability 不重复实现 Action backend。需要硬停止的第三方解析、外部程序或不受信任输入处理必须复用 Action 的受控 process 原语；业务 executor 只负责运行前 staging 和完成后业务提交。

## 执行与临时资源

独立进程能力位于 `plugins/execution`，由 `kernel/jobs` 统一监督，不属于 capabilities。详见 [execution](execution.md)。Web/resource 的有界 worker 继续通过 Action 子进程适配器执行，与 execution 共用 `infra/process` 的进程原语。

需要产生中间文件的 capability 共用 Agent 按项目根装配的 `runtime/.staging/`，由 Infra 的 staging manager 提供启动清理、唯一 action 子目录和作用域结束清理。该目录是无业务身份的短期执行设施，不属于 Workspace、Session、Home、Memory 或 archive；capability 不自行创建平行 temp root。原子写同目录临时文件、subprocess 输出捕获和项目 initializer staging 具有不同语义，不纳入此 capability staging 根。

ActionResult 是否包含正文由 action 的交互语义和明确上限决定，而不是 capability 全局固定为 metadata-only。生成长期或可继续处理 artifact 的 action 只返回 Link、状态和有界摘要；本来就属于当前交互的短搜索结果可以直接进入 TurnTrace，但必须先规范化并受 action 专属上限约束，超限正文写入 Workspace 后只返回保持稳定 shape 的预览和 Link。图片字节、base64、原始供应商响应、未规范化网页正文和无界诊断始终不能进入 ActionResult。

当前具体能力设计：

- Resource conversion：`docs/design/capabilities/resource.md`；
- Web search/fetch：`docs/design/capabilities/web.md`。
- [MCP expand](capabilities/expand.md)：四个有界 Action 共用一个目录 owner，长结果进入 Workspace。
- [ACP subagent](capabilities/subagent.md)：连接/session 与共享 JobRegistry 分工，权限请求经父 Agent 回应，Turn 收尾释放执行与 session。

## 失败语义

Capability 失败分为三层：

1. 参数不满足 action schema、输入格式不支持、目标冲突、内容损坏、资源超限和 worker 非零结果属于局部 ActionResult；
2. capability 配置非法、启用能力缺少依赖和 registrar/Catalog 装配矛盾属于模块/Agent 启动边界失败；
3. Runtime transfer、Agent/Turn/Cycle 控制和全局恢复继续由 RuntimeException 表达，capability 不吞掉或降级。

worker 的非零退出、格式错误或无效输出属于当前 action 的局部失败；它不能破坏宿主 Workspace，也不能把 worker traceback、绝对路径或原始输出带入模型反馈。宿主内部对象关系被破坏时仍按 Action 模块的公共失败边界处理。

局部失败只返回稳定 reason、资源 Link 和有界诊断。原始文件内容、worker traceback、绝对路径和敏感环境值不能进入模型反馈。

## 测试要求

每个 capability 至少覆盖：

- settings 解析、未知键和依赖需求推导；
- enabled/disabled/effective Catalog 行为；
- service/converter 的正常、部分成功、限制和损坏输入；
- executor 的 Link 边界、ActionResult 和 Runtime transfer；
- Agent 装配与隔离项目工作流；
- package template、wheel package data 和无仓库路径依赖。
