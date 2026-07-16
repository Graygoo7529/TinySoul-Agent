# Capabilities 设计

## 定位

Capabilities 承载不拥有独立持久化、Link namespace 或 Runtime/Trap 生命周期的轻量业务能力。它把真实用户能力接入 Action，而不建立与 Workspace、Home、Memory、Session 平行的状态模块。

一个 capability 负责自身的业务配置、依赖需求、service/client/converter 和 Action executor 适配。Action 继续拥有 Catalog、Phase2 工具协议、Phase3 调度、超时和结果回放；Infra 只提供配置和依赖检查等通用机制；App 只完成装配。

## 组织原则

```text
tinysoul/capabilities/
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
configs/capabilities.resource.toml
configs/capabilities.web.toml
configs/capabilities.utility.toml
```

文件拆分只影响维护位置，不改变 TOML section identity。每个 capability parser 只解释自己的子树并拒绝未知键。Infra 的 ConfigEnvironment 负责 include、合并、来源诊断和环境覆盖，不拥有 capability 业务字段。

Action Catalog 是 wheel 内只读静态定义，不保存项目 `enabled`、格式白名单、依赖版本或资源上限。Capability 配置决定某个真实 action 在当前项目是否启用；禁用 action 在 ActionEngine build 时从 effective Catalog 显式移除，没有有效 action 的 domain 同时移除。App 随后只根据 effective Catalog reconcile Home prompt mounts，因此禁用 action 不向模型暴露，也不保留伪可用 mount。

## 依赖需求与可用性

依赖需求由 capability 代码根据 effective settings 生成，项目配置只表达启用的 action、adapter 和 feature，不手工重复 Python package 名称。这样配置不能通过漏写 requirement 把不完整环境伪装为可用。

Infra 提供通用、无业务知识的 DependencyChecker：

- `DependencyRequirement` 描述稳定 requirement id、distribution、import module 和可选 executable；
- `DependencyCheck` 描述检测到的版本、module 可导入性、executable 解析路径和稳定失败原因；
- checker 使用 `importlib.metadata`、`importlib.util` 与 `shutil.which` 检查当前解释器和进程环境，不执行安装、不读取业务配置、不改变进程环境；
- capability 可以在基础检查后执行 adapter-specific probe，但 probe 仍由 capability 自己拥有。

可用性规则固定为：

```text
enabled=false
  -> 不检查、不注册、从 effective Catalog 移除

enabled=true + dependencies available
  -> 注册 executor 并暴露 action

enabled=true + dependencies unavailable
  -> App 启动失败，报告 action、requirement、distribution/module/executable 和原因
```

启动检查不能替代执行期防御。环境在启动后被修改、worker 导入失败或外部二进制不可运行时，单次 action 仍返回局部失败；配置形态错误和 capability 装配不变量失败保留模块边界语义。

## Action 与实现依赖

Action 名称由用户可区分的行为决定。通常不应只因实现库不同而复制同义 action；但当不同 adapter 具有明确的格式范围、输出结构、失败模式和选择倾向时，可以在同一 domain 暴露多个具名 action，并通过 Catalog semantic 与 domain HOW 说明选择规则。

Capability 不重复实现 Action backend。需要硬停止的第三方解析、外部程序或不受信任输入处理必须复用 Action 的受控 subprocess 原语；业务 executor 只负责运行前 staging 和完成后业务提交。

ActionResult 是否包含正文由 action 的交互语义和明确上限决定，而不是 capability 全局固定为 metadata-only。生成长期或可继续处理 artifact 的 action 只返回 Link、状态和有界摘要；本来就属于当前交互的短搜索结果可以直接进入 TurnTrace，但必须先规范化并受 action 专属上限约束，超限正文写入 Workspace 后只返回保持稳定 shape 的预览和 Link。图片字节、base64、原始供应商响应、未规范化网页正文和无界诊断始终不能进入 ActionResult。

当前具体能力设计：

- Resource conversion：`docs/design/capabilities/resource.md`；
- Web search/fetch：`docs/design/capabilities/web.md`。

## 失败语义

Capability 失败分为三层：

1. 参数不满足 action schema、输入格式不支持、目标冲突、内容损坏、资源超限和 worker 非零结果属于局部 ActionResult；
2. capability 配置非法、启用能力缺少依赖和 registrar/Catalog 装配矛盾属于模块/App 启动边界失败；
3. Runtime transfer、Program/Turn/Cycle 控制和全局恢复继续由 RuntimeException 表达，capability 不吞掉或降级。

worker 的非零退出、格式错误或无效输出属于当前 action 的局部失败；它不能破坏宿主 Workspace，也不能把 worker traceback、绝对路径或原始输出带入模型反馈。宿主内部对象关系被破坏时仍按 Action 模块的公共失败边界处理。

局部失败只返回稳定 reason、资源 Link 和有界诊断。原始文件内容、worker traceback、绝对路径和敏感环境值不能进入模型反馈。

## 测试要求

每个 capability 至少覆盖：

- settings 解析、未知键和依赖需求推导；
- enabled/disabled/effective Catalog 行为；
- service/converter 的正常、部分成功、限制和损坏输入；
- executor 的 Link 边界、ActionResult 和 Runtime transfer；
- App 装配与隔离项目工作流；
- package template、wheel package data 和无仓库路径依赖。
