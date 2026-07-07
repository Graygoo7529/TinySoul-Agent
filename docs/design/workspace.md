# Workspace 设计

## 状态

本文描述 Workspace 模块的当前设计。代码已包含独立 Workspace 模块，并完成 `workspace:` 链接解析、workspace 根目录配置、manifest 读写、资源扫描、单资源摘要刷新、`workspace.scan` / `workspace.describe` action、Context WorkingPatch 同步和 Runtime bridge 接入。

当前实现覆盖 Workspace 的资源发现、语境投影和单资源摘要刷新切面。`WorkspaceEngine` 提供有界 UTF-8 文本读取能力，供后续复合 action 或临时 task prompt 使用；该能力当前不暴露为模型侧 `workspace.read` action，避免文件正文通过 ActionResult 持久进入 TurnTraceContext。写入、patch、删除和日终归档仍未实现，后续应继续在本模块内扩展，而不是回到 app 装配层或具体 action 中散落实现。

## 定位

Workspace 模块负责 TinySoul 当日工作区的资源管理，是 `workspace:` 链接的唯一语义归属方。

Workspace 不维护语境状态，不执行模型调用，不解释外部输入命令，也不读取 Agent Home。它向 action 模块提供 native action 或 executor 注册材料，通过 context 信号同步资源摘要，并通过自身门面处理 workspace 链接解析、路径边界、资源扫描、manifest 更新和文件读写。

## 设计目标

1. `workspace:` 链接有唯一解析和校验入口，避免路径规则散落在 app、action 或具体工具函数中。
2. WorkingContext 只保存 workspace 资源句柄和摘要，不保存文件正文、图片字节或长内容。
3. workspace 文件内容只在具体 action 执行期读取，并作为 action 内部输入或临时 task prompt 使用。
4. `workspace.scan` 保持现有外部行为，但扫描规则、摘要格式和 WorkingContext patch 构造迁入 Workspace 模块。
5. workspace 根目录、忽略规则、manifest 损坏、路径越界和读写失败有清楚的失败语义。
6. App 只负责装配 Workspace 门面，不再直接扫描目录或解释 `workspace:` 链接。

## 边界

Workspace 的核心职责：

- 管理当日 workspace 根目录；
- 解析和规范化 `workspace:` 链接；
- 校验文件路径是否位于 workspace 根目录内；
- 扫描资源并维护 manifest；
- 生成 WorkingContext 可消费的资源摘要；
- 为 action 模块提供 workspace action 的 native handler 或 executor；
- 在需要时读取、写入或删除 workspace 文件；
- 在日级生命周期中归档 workspace。

当前实现已经承担扫描、manifest、链接解析、单资源摘要刷新、Engine 内部有界文本读取、`workspace.scan` handler 和 `workspace.describe` executor；写入、删除和归档仍是待扩展职责。

Workspace 不负责：

- 把文件正文写入 BackgroundContext 或 TurnTraceContext；
- 决定 Phase1/Phase2 的行动策略；
- 维护 Agent Home 的 WHAT、WHY、HOW 或 MEMORY；
- 解析终端、HTTP、WebSocket 等外部输入；
- 直接修改 Context 内存状态。

跨模块协作只通过四类边界完成：workspace link、action 调用、context signal、builder 注入。

## 链接语义

`workspace:` 链接表示工作区内资源句柄，格式为：

```text
workspace:<relative-posix-path>
```

链接规则：

- 路径必须是相对路径；
- 路径分隔符使用 `/`；
- 不允许空路径、绝对路径、盘符、反斜杠、`.` 段或 `..` 段；
- 解析后的真实路径必须位于 workspace 根目录内；
- 符号链接若指向根目录外，应按越界处理；
- 链接只表达资源位置，不承诺资源当前一定存在。

Workspace 模块应提供 `WorkspaceLink` 或等价值对象，在 `__post_init__` 中完成格式校验。模块内部不应使用裸字符串拼接构造路径。

## 资源模型

Workspace manifest 记录资源摘要，而不是资源内容。一个资源记录至少表达：

- `link`：`workspace:` 资源链接；
- `path`：workspace 内相对路径；
- `kind`：文本、二进制、图片、目录或未知；
- `summary`：给 WorkingContext 和模型看的短摘要；
- `size`：字节大小；
- `mtime`：修改时间；
- `digest`：可选内容摘要，用于变更检测。

投影到 Context 时只提交轻量信息。当前 WorkingContext 已有 `WorkspaceResource(link, summary)`，Workspace 模块可以先投影为这两个字段；后续如需 size、kind、mtime，应先扩展 Context 的资源摘要协议，而不是把完整 manifest 塞进 trace。

## Manifest

Manifest 是 workspace 的当前资源索引。它用于：

- 避免每次 Phase 都扫描全目录；
- 识别资源新增、修改、删除；
- 为 WorkingContext 提供稳定摘要；
- 支持日终归档和调试。

Manifest 读写属于 Workspace 模块。Manifest 文件应放在 workspace 根目录的框架子目录中，或放在 runtime 元数据目录中；无论采用哪种位置，都不应暴露为普通 `workspace:` 资源，避免模型误把框架索引当作用户资源。

Manifest 损坏属于 Workspace 模块边界失败。启动或装配阶段发现 manifest 损坏时映射为启动失败；运行期扫描发现 manifest 损坏时可以重建，若重建失败再进入 Runtime。

## 目录与生命周期

Workspace 具有当日属性。目标运行结构为：

```text
runtime/
  archive/
  workspace/
  home/
```

Workspace 模块只管理 `runtime/workspace` 或配置传入的 workspace root。日终归档由 workspace 门面提供归档能力，但调度归档的 Program 同级任务不属于 Workspace 自身。

当前实现默认把项目根目录作为 workspace root，也支持通过配置传入 `workspace.root` 和 `workspace.manifest_path`。AppBuilder 只负责解释配置并构建 `WorkspaceEngine`，不直接扫描目录。

## Action 接入

Workspace action 继续走 action 模块的既有机制：TOML 描述模型可见工具和框架配置，Workspace 模块提供后端 handler。

当前已实现的 `workspace.scan` 行为：

1. 扫描 workspace 根目录；
2. 应用忽略规则和数量限制；
3. 更新 manifest；
4. 发出 `context.working.patch` 信号同步资源摘要；
5. 返回 compact JSON payload，包含资源数量和链接摘要。

当前已实现的 `workspace.describe` 行为：

1. 解析并校验一个 `workspace:` 链接；
2. 刷新该资源的 manifest 记录；
3. 发出 `context.working.patch` 信号同步该资源摘要；
4. 返回 compact JSON payload，包含链接、摘要、大小、mtime 和 digest，不包含文件正文。

后续可增加的 action：

- `workspace.read` 或等价复合读取能力：读取文本资源片段时必须限制大小，并保证正文只进入临时任务输入或 action 内部处理，不直接作为普通 ActionResult payload 持久写入 TurnTraceContext；
- `workspace.write`：写入或覆盖资源；
- `workspace.patch`：基于 diff 或结构化 patch 修改资源；
- `workspace.delete`：删除资源；

这些 action 的执行失败应优先收敛为 `ActionResult`，例如链接不存在、参数非法、文件过大、编码不支持、写入失败。只有 workspace 门面不变量破坏、配置不可解释或需要全局恢复时，才进入 Runtime。

## Context 接入

Workspace 不直接持有或修改 ContextEngine。同步资源摘要时，Workspace action 通过 `SignalBus` 发出 `context.working.patch` 信号，由 ContextEngine 在边界批量消费。

Context 中不保存文件正文。Action 结果也不应默认把正文渲染为 tool result message；需要给模型继续处理的正文，应在 action 内部进行摘要、切片或转化为临时 task prompt，再把摘要和资源链接写回 trace。

## Infra 依赖

Workspace 可以复用 infra 的基础文件能力，但 infra 不应了解 `workspace:` 业务语义。适合放入 infra 的能力包括：

- 安全相对路径解析；
- 根目录边界检查；
- 文本和二进制读写；
- JSON/TOML 稳定序列化；
- 原子写入；
- 文件摘要计算。

忽略规则、manifest 字段、resource summary 和 `workspace:` 链接仍属于 Workspace。

## 失败与 Runtime 桥接

Workspace 失败分三层：

1. 局部 action result：链接不存在、文件过大、编码失败、写入失败、参数不符合 workspace 规则；
2. 模块边界异常：workspace root 不可用、manifest 无法解释、路径沙箱不变量破坏、模块调用契约错误；
3. Runtime 语义异常：启动阶段配置失败映射为 `runtime.startup_failed`，运行期不可继续失败默认映射为 `runtime.turn_end`。

Workspace 应定义自己的 `WorkspaceFailureKind`，并通过 `tinysoul/runtime/bridge/` 下的专门 bridge 转换为 Runtime 通用原因。Runtime payload 只携带模块名、失败类型、资源链接、路径摘要和错误类型，不携带文件内容或 traceback。

## 组装入口

当前目录：

```text
tinysoul/workspace/
  __init__.py
  engine.py
  config.py
  links.py
  manifest.py
  actions.py
  errors.py
  failures.py
```

`WorkspaceEngine` 是上层唯一门面，提供扫描、链接解析、manifest 投影、单资源摘要刷新和内部有界文本读取。`WorkspaceEngineBuilder` 负责接收已解析设置、校验 root、装配忽略规则和 manifest store。后续文件写入、patch、删除和正文进入临时任务输入的能力应继续挂在 `WorkspaceEngine` 或其 action executor 上，保持 AppBuilder 不理解 workspace 路径语义。

AppBuilder 的目标职责是：

1. 构建 `WorkspaceEngine`；
2. 把 Workspace 提供的 native handler 注册到 `ActionEngineBuilder`；
3. 不直接调用 `os.walk`，不构造 `WorkspaceResource`，不解释 `workspace:`。

## 测试与验收

验收点：

- `workspace.scan` 和 `workspace.describe` 行为测试位于 `tests/workspace/`；
- AppBuilder 不包含 workspace 扫描闭包；
- `workspace:` 链接解析和越界防护有单元测试；
- manifest 扫描和更新有单元测试；
- Engine 内部有界文本读取不会通过模型侧 action 把正文写入 Context；
- action 执行失败应收敛为 `ActionResult`；
- workspace 配置错误和 manifest 不变量错误经 Runtime bridge 映射；
- Context 测试继续证明 WorkingContext 只保存链接和摘要。

仍需补充的验收点包括：删除资源检测、workspace write/patch/delete 的局部失败结果、正文临时任务输入路径、日终归档以及更完整的运行期 Runtime bridge 覆盖。
