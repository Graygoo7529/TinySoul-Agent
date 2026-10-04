# 固定模型文案

这里保存随代码维护的模型可见固定文案。按业务 owner 导航，先看对应文件中的消费位置注释，再到消费端查看何时、以什么载体进入模型。内容模块只提供字符串、不可变 tuple 和参数明确的纯文本函数。

## 导航

下表路径相对于 `tinysoul/`；每个内容文件的注释继续定位具体消费函数。

| 内容文件 | 模型可见位置 | 主要消费端 |
| --- | --- | --- |
| [agent/user.py](agent/user.py) | User Turn 的 Phase1/Phase2 情景指引 | `agent/user/builder.py` → `kernel/loop/prompts.py` |
| [kernel/loop.py](kernel/loop.py) | Phase TaskPrompt 的 guide/input/output，以及后续 Cycle 的局部反馈 | `kernel/loop/prompts.py`、`phases/`、`turn.py` |
| [kernel/context.py](kernel/context.py) | Phase1 Control Tool 描述、参数说明，以及 Context 操作反馈 | `kernel/context/control/tools.py`、`engine.py`、`actions.py`、段 owner |
| [kernel/action.py](kernel/action.py) | 域选择工具说明、域与 Action 语义包装、Action 内部任务和局部结果反馈 | `kernel/action/planning/`、`tasks.py`、`builtins/core/actions.py`、参数归一化与执行边界 |
| [kernel/retrieval.py](kernel/retrieval.py) | 选择/排序 LLM 请求、JEV 问题及有序等级、检索工具说明和局部反馈 | `kernel/retrieval/selection.py`、请求与管道 owner |
| [kernel/jobs.py](kernel/jobs.py) | Job Action 的修正反馈 | `kernel/jobs/actions.py` |
| [plugins/reflection.py](plugins/reflection.py) | Reflection 初始输入、Phase 情景指引和该情景的 answer 语义 | `plugins/reflection/{home,memory}/task.py`、`turn/prompts.py`、`actions.py` |
| [plugins/workspace.py](plugins/workspace.py) | Workspace describe/compose/analyze 的 TaskPrompt、资源包装、资源状态说明和局部反馈 | `plugins/workspace/prompts.py`、`actions/`、`projection.py` |
| [plugins/home.py](plugins/home.py) | Home 操作与 review 的局部反馈 | `plugins/home/actions/`、`engine.py` |
| [plugins/memory.py](plugins/memory.py) | Memory 背景入口标题/说明，以及活动记忆和持久文档操作反馈 | `plugins/memory/background.py`、`actions/`、`engine.py` |
| [plugins/session.py](plugins/session.py) | Session Organize 校验与来源引用反馈 | `plugins/session/annotations/models.py`、`engine.py`、`views/inspection.py` |
| [plugins/execution.py](plugins/execution.py) | shell/script Action 的局部反馈 | `plugins/execution/actions.py` |
| [plugins/capabilities/web.py](plugins/capabilities/web.py) | Kimi worker 独立请求的 system 提示，以及 Web Action 反馈 | `plugins/capabilities/web/backends/worker.py`、`actions.py` |
| [plugins/capabilities/resource.py](plugins/capabilities/resource.py) | Resource Action 的局部反馈 | `plugins/capabilities/resource/actions.py` |
| [plugins/capabilities/subagent.py](plugins/capabilities/subagent.py) | ACP 委派引用包装和本地请求反馈 | `plugins/capabilities/subagent/engine.py`、`actions.py`、`acp/connection.py`、`jobs/backend.py` |
| [plugins/capabilities/expand.py](plugins/capabilities/expand.py) | MCP expand 本地请求、连接和能力范围反馈 | `plugins/capabilities/expand/actions.py`、`engine.py`、`mcp/client.py` |
| [llm.py](llm.py) | 输出解释的可修正反馈；禁用原生工具时的工具结果 user context 包装 | `llm/protocol/responses.py`、`execution/task.py`、`provider/openai_sdk/payloads.py` |

TaskPrompt 的 guide/input/output 使用既有 user role；角色和实际消息由消费端设置。retrieval/JEV、Web worker、ACP 委派和 provider 包装各有真实出口，不都经过 TaskPrompt。

## 修改方式与边界

- 固定段落使用常量或 tuple；插入动态值时使用参数具体的函数。日期、资源正文、限制、候选和引用由 owner 准备，函数只格式化，不读取业务状态或解释异常。
- 消费端显式导入自己的 owner 文案模块。新增或移动用途时同步定义旁的消费注释；相似措辞不代表相同职责，不跨 owner 合并成通用错误字典。
- schema 字段、工具名、稳定 ref/Link、label、失败 reason、状态、输出解析和序列化仍在原 owner。修改涉及这些协议的文案时，应同时核对真实 schema 和解释器。
- `kernel/context/prompts.py` 是 TaskPrompt 协议；`kernel/loop/prompts.py`、`plugins/workspace/prompts.py` 和 `plugins/reflection/turn/prompts.py` 仍负责装配、解析或情景选择。这些模块有业务职责，不能作为纯文本文件搬入本包。
- `MessageOrigin` 继续表达业务来源。此目录是源码位置，不是模型资源，不建立 `prompt:` Link、注册表、模板加载器、配置入口或 Runtime bridge。
- 仅用于 SDK、存储校验、日志、Observation 和 Runtime 的诊断留在原模块。共享校验若也产生可修正模型反馈，可以消费此包；错误类别与传播仍由原 owner 决定。

## 其它模型内容来源

[Action Catalog](../assets/common/configs/action/catalog/) 的 domain/action 描述、选择提示、示例及参数说明属于可配置能力定义。项目中的实际 Catalog 经 `kernel/action` 装载，供 Phase1 域选择和 Phase2 Action Tools 使用。本包只保存代码中的固定包装，不复制或覆盖 Catalog 文案。

Home 的身份、偏好、通用 Skill 和 domain/action Skill 由 `plugins/home` 管理。用户输入、资源正文、模型生成内容及远端 MCP/ACP 定义也由各自 owner 提供，均不作为本包常量。详细边界见[固定模型文案设计](../../docs/design/prompts.md)。
