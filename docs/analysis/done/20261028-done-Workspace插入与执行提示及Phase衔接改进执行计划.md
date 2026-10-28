# Workspace 插入、执行提示与 Phase 衔接改进执行计划

- 日期：2026-10-28。
- 状态：`done`；实现、文档、测试及 AGENTS.md 逐项复核已完成，归档于 2026-10-28。
- 依据：当前 `AGENTS.md`、Workspace / Execution / Action / Loop / TaskPrompt 的实际实现，以及本轮维护者确认。
- 目标：提供直接的文本位置插入能力，让模型知道实际可用的解释器，明确整轮指导与阶段任务的层次，传递 Phase1 已生成的 Cycle 意图，并适度扩大 Workspace 分析容量。

## 1. 范围与现状

本计划从运行现象提炼可复用的问题，不把真实文件、任务内容、Cycle 编号或某个模型的输出写入生产逻辑和测试条件。

| 项目 | 当前实现 | 目标 |
| --- | --- | --- |
| Workspace 插入 | edit 可以用短锚点模拟插入；append 只在末尾追加 | 新增按行定位的 `workspace.insert`，减少复制原文的需要 |
| Execution 可用性 | 静态 interpreter enum 完整；Engine 掌握实际可用名单；模型说明未提供名单 | run/start 描述附加当前 owner 提供的短信息，失败时提供可用选择 |
| TaskPrompt 层次 | Phase 指导之后追加通用 Turn 指导，失败混在 guide 中 | Turn guidance → 当前 Phase → 本次输入 → Expected Output |
| Phase 意图 | select_action_domains 声明可选 intent，但 normalize 后只保留域名 | intent 经 Phase1Outcome 进入 Phase2 Task Input |
| 阶段失败 | 局部失败结束 Cycle，写入 Trace 并反馈给下一 Cycle；提示主要描述拒绝原因 | 保留流程，补充本阶段职责与下一步方向 |
| Workspace analyze | 单来源 12k、来源合计 24k、回答 4k 字符 | 单来源 32k、来源合计 64k、回答 8k 字符 |

已核对的正常主线仍然成立：Phase1 只提交 Context controls 和域选择，Phase2 只生成已选域内的 ActionCall，Phase3 执行；模型生成越界工具名不表示框架开放或执行了该工具。Workspace.edit 的字符串参数错误与 old_text 匹配失败是不同问题，insert 不作为修改参数校验规则的理由。

本计划不调整 provider 的 tool choice 协议，不增加阶段内部重试、不接受越界响应的部分调用。Context 窗口、token 估算和压力恢复使用已有机制；正在进行的《模型升级与统一上下文窗口执行计划》负责其相应改动。

## 2. workspace.insert

### 2.1 对外语义

新增确定性 Action：

```json
{
  "target_ref": "workspace:docs/notes.md",
  "after_line": 12,
  "text": "新增内容\n"
}
```

- `target_ref`：已存在的 UTF-8 Workspace 文本资源；沿用其它 mutation 的目标引用解析，不增加片段定位方式。
- `after_line`：必填整数。正数使用与 read 相同的 1-based 行号，表示该行之后；0 表示文件开头。
- `text`：插入的明确文本，包含所需空格、分隔符和换行；与 append 一样不自动格式化。允许空文本，不为 insert 单独建立不同的文本规则。
- 文件正文先沿现有 `_editable_text` 读取和换行规范化；行边界以规范化后的 `\n` 为准，与 `read_text_range` 一致。定位点在该行已有换行符之后；末行没有换行符时，定位点是 EOF。
- 空文件只接受位置 0。对于非空文件，合法位置为 0 到实际行数；末尾换行不额外制造一条可插入的空行。超出行数返回局部请求失败，不自动钳制到 EOF。
- 插入前后的完整文件仍受 `workspace.max_write_chars` 限制。新增能力不承诺编辑无限长文件。

举例：`A\nB\n` 在 after_line=1 插入 `X\n`，得到 `A\nX\nB\n`；`A` 在 after_line=1 插入 `\nX`，得到 `A\nX`。文件开头、中间和 EOF 共用同一位置语义。

三类 mutation 的职责保持容易理解：

| Action | 职责 |
| --- | --- |
| append | 在文件末尾追加明确文本 |
| insert | 在指定行后插入明确文本 |
| edit | 用唯一匹配的原文进行替换或删除 |

行号解释执行时的当前内容。Agent 可以先 read/inspect 定位，再 insert；文件变化后应重新判断位置。沿用 Workspace 的受信共写语义，不增加 read-set、revision 或 CAS。

### 2.2 owner 实现与发布

1. 在 `WorkspaceMutations` 增加 `insert_text(ref, text, *, after_line)`。在已有锁内读取当前正文、校验位置、构造完整结果，再复用 `write_text(..., overwrite=True)` 提交一次。
2. `WorkspaceEngine.insert_text` 使用 `_change`；`WorkspaceChangeOperation` 增加 `INSERT`，并将其纳入 `_change` 的正式 written_refs 分支。成功变更按现有提交 → 索引 → 事件链路发布。
3. `WorkspaceService.insert_text` 复用 `scope.local(..., after=owner.events.flush)`，使 SDK、Action 和 Endpoint 使用同一个 owner 方法，复用日 lease、取消 join 与事件发布。
4. `WorkspaceExecutor` 新增 insert 分支；`WORKSPACE_ACTIONS` 登记 identity。成功结果沿用写入类 Action 的资源元数据，不返回整份文件正文，也不新增结果格式。
5. INSERT 不使用 LLM，不新增 model-use，不复制文件写入或事件状态机。

### 2.3 局部失败反馈

普通 Action schema 错误继续由 Action 归一化反馈。owner 必须独立校验 SDK/Endpoint 入口的 after_line 类型及范围；bool 不作为行号。

位置错误提供自然语言，例如：

> Cannot insert after line 80: the file has 24 lines. Use 0 for the beginning or a line number from the current file.

实现采用既有 `WorkspaceContractError` 的轻量扩展：增加默认空字符串的可选 `feedback` 参数，表达 owner 明确整理过的安全文本；原来的异常 message 继续只承担诊断。新插入位置错误填写此字段，Workspace Action 边界在存在 feedback 时使用它，否则保留现有通用反馈。`WorkspacePromptReferenceError` 复用同一字符串字段，专门 reason/payload 流程继续由原分支处理。

这样不必新增 insert 专属异常树，也不把全部 `str(exc)` 暴露给模型。固定反馈函数归 `prompts/plugins/workspace.py`，只接收已校验的数值；Action 的 reason、scope、disposition 沿用 `request_conflict`、`workspace.action`、`CHANGE_REQUEST`。I/O 错误和取消仍走现有边界，不能一律包装成可重试的请求错误。

### 2.4 Catalog 与 Home 文案预览

新增 `assets/common/configs/action/catalog/workspace/actions/insert.toml`：

```toml
name = "workspace.insert"
domain = "workspace"

[tool]
description = "Insert exact UTF-8 text after a line in an existing Workspace text resource. Use after_line=0 for the beginning."

[tool.schema]
type = "object"
required = ["target_ref", "after_line", "text"]
additionalProperties = false

[tool.schema.properties.target_ref]
type = "string"
description = "Existing Workspace text resource ref."

[tool.schema.properties.after_line]
type = "integer"
minimum = 0
description = "Insert after this 1-based line in the current file; 0 inserts at the beginning."

[tool.schema.properties.text]
type = "string"
description = "Exact text to insert, including any required separator or newline."

[semantic]
use_when = ["Insert content at a line located through read or inspect"]
avoid_when = ["Need to replace existing text; use workspace.edit", "Only adding at the end; use workspace.append"]
effects = ["modifying"]
examples = ["Insert a note after line 12 of workspace:docs/notes.md"]

[runtime]
parallel_policy = "serial"

[execution]
executor = "workspace.insert"
```

对现有文案仅作必要补齐：

```diff
# workspace DOMAIN.md，替换原文中的对应一句，其余内容保留
-Use workspace.write for exact content, workspace.edit for ordered unambiguous replacements, and workspace.append for exact additions.
+Use workspace.write for exact content, workspace.edit for ordered unambiguous replacements, workspace.insert for additions after a known line, and workspace.append for additions at the end.

# append.toml 的 avoid_when
-"Need to insert in the middle; use workspace.edit"
+"Need to insert at a known line; use workspace.insert"
```

append 的 Action Skill 可以补上 insert 的选择入口；不为简单 insert 新建一份重复 Catalog 的 Action Skill。edit 的参数保持原数组协议，只补齐直接有用的字段说明：edits 是按顺序提交的替换数组，old_text 是当前文本中的唯一片段，new_text 是明确替换内容。可在 examples 保留一个简短的短锚点插入用法，不添加与真实轨迹绑定的长示例。

### 2.5 SDK / Endpoint

SDK 已通过 WorkspaceService 导出日级服务，增加方法即可，不新增另一套 SDK Workspace 类型。

新增 `POST /v2/workspace/insert`：

```json
{"ref":"workspace:docs/notes.md","after_line":12,"text":"新增内容\n"}
```

HTTP request 沿用其它 Workspace mutation 的 `ref` 命名，Action 沿用 `target_ref`；Endpoint 只做协议映射。请求 schema 拒绝额外字段，after_line 为非负严格整数；响应复用 `{record, manifest}`。资源冲突返回既有 409/code，能够使用 owner 提供的安全反馈；资源缺失、I/O 失败保留既有映射。

同步 `docs/endpoint/workspace.md` 的请求、行号、换行及容量语义，`docs/endpoint/events.md` 如列举 operation 则补入 insert。前端可沿通用 Action 结果展示工作；本轮不新增编辑器按钮或页面。

## 3. Execution 运行时解释器提示

### 3.1 唯一事实来源

`ExecutionEngine` 已在 generation 初始化时根据配置检查 executable，并把成功解析的解释器保存在 `_executables`。新增只读 `available_interpreters` 投影，返回按声明顺序排列的 `tuple[Interpreter, ...]`；命令解释器由此排除 Python 得到，不重复维护状态。

可用信息来自当前 Engine，而非模板默认值、操作系统名称、未激活的配置草稿或每次调用时重新探测 PATH。配置 reload 后的新 Engine 自然生成新名单；全部关闭时仍沿现有 unsupported-action 路径。

### 3.2 工具描述装配

`register_execution_actions` 在注册 run/start 时把 owner 投影转换为短提示，附加到这两个 Action 的 effective description。

Python、PowerShell、cmd 可用时：

> Available in this runtime: python, powershell, cmd. Inline commands use powershell or cmd; Python uses source_ref.

仅 Python 可用时：

> Available in this runtime: python. Use source_ref; inline commands are unavailable.

仅 bash 可用时：

> Available in this runtime: bash. Inline commands use bash.

列表和措辞由当前数据生成，不能将开发实例的名单硬编码进 Catalog、Home 或通用 Turn guidance。Python 是否列入最后一句也由真实可用性决定。`source_ref` 对其它已启用脚本解释器的支持仍由原 schema/说明表达。

接入复用现有 `ActionEngineBuilder` 的 effective Catalog 构造位置，增加一个窄的 `with_action_hint(action_name, hint)` 装配方法：

- 每个 Action 保存一条由装配者提供的非空说明；build 时在已有 profile semantics override 之后附加。
- 保留 Catalog 原始 description 和 semantic，不要求插件读取 builder 私有 catalog，也不复制可编辑文案。
- 只影响 effective model-facing Catalog；configured Catalog 和编辑接口保持配置原文，提示不被写回 TOML。
- 复用现有未知 Action 名称的装配校验；不引入动态回调、提示注册平台或新的 ToolSpec 字段。

固定措辞放入 `prompts/plugins/execution.py` 的纯文本函数；函数只接收 owner 已验证的解释器名称/命令名称。

### 3.3 执行失败

解释器已知但未启用时，沿 `ExecutionRequestError.feedback` 返回，例如：

> The bash interpreter is not enabled in this runtime. Available interpreters: python, powershell, cmd.

保持已有 240 字符反馈边界，以及 `invalid_request`、`execution.action`、`CHANGE_REQUEST`。名单来自与工具描述相同的 Engine 投影，避免提示与实际执行分叉。

未知枚举仍主要由 Catalog schema 拒绝；Engine 的直接调用校验保留。Python inline command 的拒绝继续明确要求 source_ref，不增加隐藏的解释器替换、脚本落盘或自动补参数。静态 enum 和 command/source_ref 分支不变。

## 4. Turn guidance 与 Phase TaskPrompt 层次

### 4.1 文案与结构

保留 `USER_TURN_GUIDANCE` 现有全文，包括 inspect/search、core.ask/core.answer 等直接行动措辞及重复的小步探索理念。Phase 指导也不在本轮进行大规模删改。补充以下桥接句：

> Apply this Turn guidance through the tools available in the current phase.

该句由 `prompts/kernel/loop.py` 提供，在存在 turn_guidance 时由 Loop 装配在 Turn guidance 后；它同样适用于 Reflection 等 TurnProfile 的指导。Agent 继续提供情景文案，Kernel 不导入 User 专属提示。

复用现有 TaskPrompt 的三类块，形成以下顺序：

```text
guide_blocks:
  # Turn Guidance                 有情景指导时呈现
  [原有 Turn guidance 全文]
  Apply this Turn guidance through the tools available in the current phase.

  # Task Guide
  [本次 Phase 的原有指导]

  # Domain Skill                  仅当前 Phase2 的已选域 Skill，保持现有 owner/ref

input_blocks:
  # Task Input
  [Phase1 可选域 / Phase2 已选域与可选 Cycle intent]

  Previous cycle feedback:        有本次注入的失败反馈时呈现
  [当前已有的有界反馈]

output_blocks:
  # Expected Output
  [本次应生成的 controls 或 Action calls]
```

Turn guidance 使用独立 `task_prompt:guide:turn` block；已有 `task_prompt:guide:phase1/phase2` 标签仍表示当前阶段。反馈移至 `task_prompt:input:feedback`。没有情景指导、intent 或反馈时不渲染空块。

保留 user role，不修改 Background/Trace/Working 顺序，不把 TaskPrompt 变成持久 Context 段。Domain Skill 保持在阶段指导之后、本次输入之前。Trace 导出能从实际请求读取这些块；无需增加平行导出字段。

### 4.2 Expected Output 的局部补强

Phase1 保留现有 controls 和必选域选择协议，已有三阶段说明保留。Phase2 的输出说明补明当前工具作用域：

```diff
-# Expected Output
-Return one or more action tool calls with valid arguments.
+# Expected Output
+Return one or more action tool calls from the current tool definitions, with valid arguments for the selected domains and this Cycle's intent.
```

intent 缺省时依旧根据当前请求和 Context 生成行动；它不构成新增的必选字段或执行授权。

## 5. 消费 select_action_domains.intent

### 5.1 数据流

```text
select_action_domains(domains, intent?)
  → ActionDomainSelection(selected_domains, intent, feedback)
  → Phase1Outcome(selected_domains, intent, ...)
  → CycleRunner
  → Phase2Unit.run(..., intent=...)
  → phase2_task_prompt
  → Task Input / Cycle intent
```

在两个现有 frozen dataclass 中增加 `intent: str = ""`。域选择 normalizer 从工具参数读取、校验和规范化一次，Loop 传递已有类型化结果，不从历史文本或 Observation 中重新提取。

- 未提供、空字符串或纯空白：视为没有补充意图，省略展示。
- 已提供但不是字符串：返回域选择的局部协议反馈，Phase1 按现有流程结束当前 Cycle；不强转成字符串。
- 有效字符串仅去除首尾空白，保留内部表达；不增加独立配置、字符截断策略或新的必填要求。
- 域选择不被接受时，其 intent 不传入 Phase2。
- intent 只说明本 Cycle 的行动方向，不增加可用工具，不等于行动已执行或 todo 已完成。
- 新 Cycle 使用新选择的 intent，不继承上一次的临时意图。必要长期进展仍由现有 milestones/todos/Trace 承担。

参数说明同步为：

```diff
-Brief reason for the selected action domains.
+Brief intent for this Cycle, passed to Phase2 with the selected action domains.
```

Phase2 输入示例：

```text
# Task Input
Selected domains: workspace
Cycle intent: Write the script for execution in a later Cycle.
```

不另存 intent 日志；实际 Phase2 request 已是可检查的交接证据。

## 6. 阶段失败后的行动提示

保持三层失败边界：LLM 提供本次任务的协议原因，Loop 提供阶段语义，Runtime 仅在真正需要控制转移时参与。只修改现有 phase feedback 的自然语言与必要参数，不根据异常文本做字符串分支。

Phase1 的 LLM task 失败反馈拟为：

> Phase1 did not complete; this response's Context controls were not applied. Cause: {feedback} Select the needed action domains in Phase1; concrete action calls are generated in Phase2.

这比统一断言“required domain selection was not accepted”更准确：响应可能已经含有 selection，但另一个越界工具使整个 task 失败。

Phase1 域选择失败反馈拟为：

> Phase1 did not complete; this response's Context controls were not applied. Cause: {feedback} Call select_action_domains with the domains needed for this Cycle; use the available Context controls when needed.

Phase2 的 LLM task 失败反馈拟为：

> Phase2 did not complete; no Action from this response was accepted or executed. Cause: {feedback} Selected domains: {domains}. In the next Cycle, select the domains needed for the intended actions and use their current tool definitions in Phase2.

这些文案只用于当前已有的“task/selection 尚未接受”分支，不扩大为所有失败都未发生任何事实。已经接受的 Context controls、Action 参数级局部结果和实际执行结果仍由自己的路径准确描述。

反馈继续进入原有 phase note / Trace，并由现有上一 Cycle 反馈传递给下一个 Phase1。Phase2 继续读取正常 Trace；不再引入一份跨阶段失败状态或把整个历史重复复制到 TaskPrompt。

## 7. Workspace analyze 容量

### 7.1 配置目标

k 统一按 1024 字符计算；生成 token 预算独立管理。

| 配置字段（workspace.analysis） | 当前默认 | 目标默认 | 含义 |
| --- | ---: | ---: | --- |
| max_intent_chars | 2048 | 2048 | 本次分析目标的字符上限 |
| max_reference_refs | 8 | 8 | 显式来源数量上限 |
| max_chars_per_reference | 12288 | 32768 | 单个完整 UTF-8 来源的字符上限 |
| max_source_chars | 24576 | 65536 | 所有来源正文的字符总量上限 |
| max_answer_chars | 4096 | 8192 | 返回分析正文 answer 的字符上限 |

32k 单来源与 Workspace 的 32k 完整写入容量对齐；64k 总来源允许组合多个文档；8k 回答为比较、推理和来源说明保留适度空间。它们都是上限，不要求模型装满或写满。

### 7.2 实现与说明

- 同步 `plugins/workspace/config.py` 的 owner 默认值和 development/standard 的 `configs/workspace.toml`。
- `WorkspaceAnalysisPromptBuilder` 已动态注入 max_answer_chars，输出校验也读取相同 settings；继续使用此唯一配置来源。
- 来源仍经 `prepare_analysis_references` 完整读取和预算检查；超限在模型调用前返回局部结果，不静默截断。
- 仍默认携带当前 Context、局部来源和 domain/action Skill；answer/source_ids 的内部协议及 answer/sources/coverage 的 ActionResult 保持现状。
- 现有 Workspace 配置接口和设置字段可以直接编辑这些数值。配置描述可澄清“完整来源”“总来源正文”“输出字符”，不把默认数字复制进固定提示词或前端常量。
- 现有已初始化项目中的显式值不会被模板自动覆盖；需要通过已有配置保存及 apply/reload 流程应用新值。实施交付应明确区分模板更新与实际实例激活，不隐式改写个人配置。

analyze 的来源预算不包含已有 Context 和工具/消息开销；模型窗口检查仍针对完整请求。统一窗口计划启用后，继续服从该计划的有效窗口，不因来源字符上限提高而绕过检查。当前 UTF-8 字节保守估算可能使大量中文提前触发容量恢复，这是现有总容量语义，本计划不同时引入 tokenizer、在线计数或分块分析器。

## 8. 预计改动位置

以下按职责列出，实施时仅修改实际受影响的文件，不以文件数量作为完成指标。

| 范围 | 主要位置 | 内容 |
| --- | --- | --- |
| Workspace mutation | plugins/workspace/storage/mutations.py、engine.py、services.py、events.py | insert、正式写入发布和服务调用 |
| Workspace Action / 失败 | plugins/workspace/actions/operations.py、actions/__init__.py、errors.py、prompts/plugins/workspace.py | 参数接入、可读位置错误、现有结果投影 |
| Workspace HTTP | gateway/endpoint/http/schemas/workspace.py、http/routes/workspace.py、engine/workspace.py | insert endpoint、同源 owner 反馈 |
| Catalog / Home | common/configs/action/catalog/workspace/actions/insert.toml、append.toml、edit.toml；对应 Workspace Domain/append Skill | 新工具定义和必要选择提示 |
| Execution | plugins/execution/engine.py、actions.py、prompts/plugins/execution.py | 可用名单与请求失败短反馈 |
| Action 装配 | kernel/action/engine.py | 配置原文之上的一次 effective description hint 合成 |
| Phase 衔接 | kernel/action/planning/scope.py；kernel/loop/phases/contracts.py、phase1.py、phase2.py、cycle.py | intent 校验、传递和消费 |
| Phase 文案装配 | kernel/loop/prompts.py；prompts/kernel/loop.py、prompts/kernel/action.py | 指导顺序、输入块、失败后行动提示 |
| analyze 配置 | plugins/workspace/config.py；development/standard/configs/workspace.toml；infra/config/catalog/context.toml 的对应字段说明 | 三个默认容量值及语义说明 |
| 设计与接口文档 | docs/design/workspace.md、execution.md、action.md、loop.md、prompts.md；docs/endpoint/workspace.md | 当前事实和新接口说明 |

`prompts/agent/user.py` 的 USER_TURN_GUIDANCE 全文保留。本轮不要求修改 visualization；若通用 Action 展示或 Trace 导出检查发现依赖旧固定块位置，应先明确真实影响，再处理必要协作。

## 9. 验证与验收

### 9.1 Workspace owner 和服务边界

在现有 `tests/plugins/workspace/storage/test_mutations.py` 覆盖一次完整位置契约：开头、中间、EOF、空文件、末尾有/无换行、CRLF 读取规范化；验证插入文本按约定保存且原有文本顺序正确。保持少量可区分行为的参数化样例。

位置越界、非整数/布尔值、非文本目标及完整结果超预算均不提交文件或索引变化。失败反馈包含真实行数/有效方向，不能泄漏诊断异常。容量测试使用测试自有小数值，不把可调默认值固化为机器协议。

在现有 Workspace engine/events 测试覆盖代表性链路：Service 操作完成时文件、manifest 和正式 INSERT 事件一致；Action 结果是既有成功元数据，错误通过已有 local failure 反馈。日 lease、取消 join 与其它写入操作复用既有测试，只补入新增接线所需的验证。

Endpoint 测试验证请求转发到同一个服务、返回 record/manifest，以及代表性越界的既有错误 envelope。HTTP 验证不得把字符串或 bool 隐式转换为行号。

### 9.2 Execution / Action 装配

- 用测试自有配置和可执行文件解析替身验证完整名单、仅 Python、仅 shell、全部关闭。
- Phase2 的 run/start ToolSpec 含来自 owner 的名单和对应输入方式；其它 Action 不附加这段提示。
- 原 Catalog 文案与 semantic 保留；configured Catalog 不包含运行时追加文本；profile override 与 hint 可以组合。
- 禁用解释器的局部失败携带可用名称，保持 reason/scope/disposition，不启动进程、不创建 Job。
- 文案函数测试注入不同名单并检查动态信息，不快照整段可编辑文字；有效执行主线复用 `tests/plugins/execution/test_engine.py`。

### 9.3 Phase 消息与 intent

在 `tests/kernel/action/planning/test_action_scope.py` 验证 intent 的正常、缺省、空白与类型错误。只测试当前可修正协议，不增加供应商异常分类。

在 `tests/kernel/loop/phases/test_task_context.py` 用测试自有 marker 验证真实 message 顺序：Turn → Phase → Skill → Input/feedback → Output；同时保留 Skill owner/ref 和 user role，缺省可选块不产生空消息。旧测试中固定“Phase 在 Turn 前”“反馈属于 guide”的断言应替换为新的稳定顺序语义，不能为旧测试保留平行装配方式。

在 Cycle/Phase 代表性协作测试中捕获 Phase2 的 TaskCall，验证 Phase1 工具参数中的 intent 完整到达 Task Input，下一 Cycle 没有旧 intent 残留。正常没有 intent 的调用仍可运行。

在 `tests/kernel/loop/phases/test_failures.py` 覆盖：Phase1 已含 selection 但夹带越界 Action、Phase2 返回域外 Action。验证无非法执行/未接受 controls 不安装，失败传到下一完整 Cycle，后续可以用正常工具继续。测试同时检查当前域名与阶段恢复方向；不要求任意真实 LLM 必然遵守文案。

### 9.4 analyze 与资源装配

复用 Workspace analyze 的已有测试验证：来源预算内调用模型、超限不调用模型、answer 长度使用同一动态设置、未知 source_id 仍拒绝。新增代表性较长来源/回答用例时使用自有容量配置，避免用巨型固定正文增加测试成本。

资源/初始化测试检查 insert Catalog 被加载、绑定、符合 schema，并检查模板可解析；不以固定 Action 总数、文件总数或默认数字快照代替验收。

### 9.5 本地门禁

先运行相关模块的聚焦测试，再运行 Fast；完成实现前运行 AGENTS.md 要求的 Full 与类型检查：

```powershell
uv run --locked --extra dev python scripts/test.py --suite full tests/plugins/workspace tests/plugins/execution tests/kernel/action tests/kernel/loop/phases tests/gateway/endpoint tests/gateway/project
uv run --locked --extra dev python scripts/test.py
uv run --locked --extra dev python scripts/test.py --suite full
uv run --locked --extra dev ty check
```

门禁覆盖协作接口与实际行为。真实模型轨迹可以用于后续观察提示效果，不作为离线测试必须调用外部服务的条件，也不以提示词改进承诺零失败。

## 10. 实施顺序与进度

- [x] 重新阅读 AGENTS.md，确认 owner、三阶段、失败与配置边界。
- [x] 核对现有代码、可复用服务及正在进行的模型/窗口修改，形成方案和预览。
- [x] 实施前重新读取 git 状态和涉及文件，保留维护者的其它修改，按最新实现更新接入点。
- [x] 完成 insert 的 owner → Service → Action → Endpoint 主线及必要测试，同步 Workspace 文档。
- [x] 完成 Execution 可用名单、effective description hint 和失败反馈，验证 configured/effective 分离。
- [x] 完成 TaskPrompt 层次与 intent 的 Phase1 → Phase2 消费，更新阶段失败提示与协作测试。
- [x] 提高 analyze 三项默认容量，核对现有设置接口、动态提示和输出校验。
- [x] 同步 Catalog、Home、设计与 Endpoint 文档，检查模型请求和 ActionResult 的可读性。
- [x] 运行必要门禁，记录实际结果，逐项对照本计划和 AGENTS.md 复核。
- [x] 完成后改为 `done`，文件名加入 `-done-` 并移入 `docs/analysis/done/`。

## 11. 可行性核对与实施状态

方案有现成的 owner 和接入位置：insert 复用 Workspace mutation 与服务；解释器提示复用 Engine 已持有事实；TaskPrompt 已支持 guide/input/output 分层；intent 在现有工具定义中已经存在；analyze 的各项限制已经动态读取。

新增公共面只有一个 Workspace Action/服务方法及对应 Endpoint，以及 Action builder 的一条装配提示入口。现有对象增加必要字段，不建立新的 scheduler、Context 段、持久日志或配置系统。错误反馈使用已有结果语义和 owner 文案，不扩大结构化模型叙事。

实施未发现与已确认设计或维护者并行修改的冲突。行号定位、精确文本、运行时解释器名单、临时 Cycle 意图以及 32k/64k/8k 分析容量均已落实，无遗留决策项。

## 12. 实施结果与核对记录

实施基于提交 `711d784b`，开始时工作区干净；此前模型升级与窗口修改已经提交，本轮没有修改其配置或算法。

| 验收项 | 实际实现与核对 |
| --- | --- |
| 位置插入 | WorkspaceMutations → Engine → Service → Action/Endpoint 共用同一操作；开头、中间、EOF、空文件、CRLF、无末尾换行和 LF 行边界已验证。位置错误、非文本及结果超限均在提交前拒绝，文件和索引不变 |
| 提交与反馈 | INSERT 使用正式 written_refs 和既有事件发布；Service 返回前受理事件，空文本写入也保留提交事实。Action 沿用元数据结果；位置反馈到达模型和 HTTP，IO 与取消边界复用原实现 |
| 解释器说明 | Engine 的只读枚举进入 run/start 有效描述；全开、仅 Python、仅 shell、全关闭均覆盖。原 description/semantic/schema、profile override 与 configured Catalog 分离已经验证；禁用解释器的 Action 仍返回 invalid_request / execution.action / CHANGE_REQUEST，且不创建 Job |
| Phase 输入 | Turn → Phase → Skill → Input/feedback → Output 顺序和 Skill 来源经实际 message 验证。intent 从选择工具经 CycleRunner 到达 Phase2，缺省不渲染，下一 Cycle 不遗留；USER_TURN_GUIDANCE 全文保留 |
| 失败后继续 | 真实 ResponseInterpreter 结合 Phase/Cycle 验证 Phase1 夹带 Action、Phase2 域外 Action：整次响应拒绝，未接受的 controls 不安装，Action 不执行；下一完整 Cycle 收到原因及方向，使用合法工具可以继续 |
| 分析容量 | owner 默认值和 development/standard 模板统一为单来源 32768、合计 65536、回答 8192；来源完整读取和完整请求窗口检查保留。测试自有回答上限同时进入提示及结果校验，来源超限不调用模型 |
| 资源与文档 | insert Catalog 已加载、校验并执行；append/edit 与 Domain/append Skill 只补必要选择说明。Workspace、Execution、Action、Loop、prompts 设计文档及 Workspace Endpoint 文档已同步 |

### 验证记录

使用 AGENTS.md 当前规定的 uv 仓库 `.venv` / Python 3.13 环境。uv 可执行文件通过主机安装位置调用，缓存使用 `B:/tmp/tinysoul-uv-cache`；未把这些机器路径写入项目配置。

| 验证 | 结果 | 报告目录（仓库相对路径） |
| --- | --- | --- |
| 相关模块聚焦 Full | 375 passed | `.local-test/reports/30b93d59b04948748e3431e7c8f10809` |
| Fast | 1303 passed，133 deselected | `.local-test/reports/7df6b476b7894c1abf36eaeb17f388dc` |
| 最终 Full（包含后续补齐的缺省 intent 和 Action 反馈验证） | 1434 passed，3 deselected | `.local-test/reports/06d6ac73c33e4d1ba60eda95d9eb916f` |
| ty check | All checks passed | 命令输出 |
| git diff --check | 通过 | 命令输出 |

门禁包含 owner、协作边界、Endpoint、真实本机进程、初始化及 wheel 资源验收；没有调用真实外部模型。它验证提示和数据流正确装配，不承诺模型不再产生协议错误。

### AGENTS.md 与使用边界

重新阅读规约后核对：持久事实、生命周期和失败解释仍归原 owner；新增文案留在所属 prompts 包，配置文案留在 Catalog/Home；未增加 CAS、阶段内部重试、持久 intent 或平行日志。任务提示仍使用 user role，Background/Trace/Working 不变。

Trace 导出按 `task_prompt:` 标签处理并按标签去重，不依赖旧固定块位置。前端未知 Action 使用通用视图，因此 insert 的调用、参数和结果可展示；本轮没有增加编辑器插入按钮，也没有更改前端分类表。Endpoint 能力及参数已提供文档，后续可由前端按需求接入专门视图。

已初始化实例需要同步新增 `configs/action/catalog/workspace/actions/insert.toml`；正式注册会校验 Catalog 是否包含该身份，不静默忽略缺失定义。分析容量及 Home/Catalog 文案的模板更新不会覆盖已有实例的显式设置；使用已有保存、apply/reload 或重启流程激活。实施未改写个人实例数据。
