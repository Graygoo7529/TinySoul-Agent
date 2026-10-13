# Phase 协议、模型生成预算与失败反馈执行计划

状态：`pending`，2026-10-13 按当前代码重新核对；新增设计项待讨论确认，未修改运行代码或配置。

本计划独立于已完成的 Trace 导出工作。AGENTS.md 已有“项目更关注 agent 能力和灵活性”的原则；本次落实到生成额度、阶段提交和失败反馈，不增加新的执行内核或恢复状态机。

## 目标与已确认方向

1. frame_stage1、frame_stage2、llm_action 的默认输出额度采用维护者提出的 **65536 tokens（64 × 1024）**。保留现有模型选择和 reasoning 设置。
2. 生成 token 预算与文件字符限制分开：前者由 LLM 配置及调用设置决定，后者由内容 owner 决定。
3. Phase1 必须选择行动域，可以同时进行多个独立 Context 控制；不同工具保留自己的意图与参数定义。推荐继续采用独立工具协议，不把 controls 包入一个联合工具。
4. 局部协议失败结束当前 Cycle，下一完整 Cycle 读取反馈；不在 Phase 内重试，不以不完整输出继续执行。
5. 模型反馈只说明失败原因、实际效果和必要修正信息；结构化诊断供框架与轨迹研究使用。

## 当前实施核对

| 位置 | 当前事实 | 需要解决的问题 |
| --- | --- | --- |
| standard/development 的 `configs/llm/tasks.toml` | 三类 task 均为 2048 | 推理、工具参数和正式输出共享的生成空间偏小 |
| `infra/config/catalog/models.toml` | task 创建模板同样是 2048 | 只修改已有模板实例，仍会使新建 task 使用旧额度 |
| `kernel/action/tasks.py` 的 `ActionTaskFactory.create` | 将 max_output_chars 当作 token 数；有 binding 值时取小，否则作为调用覆盖 | workspace.compose 的 12000 字符额度会覆盖 task 预算；它目前可以高于 2048，调高 profile 后又会压低 65536 |
| `llm/execution/task.py` | task/调用设置合并后，model.request_overrides 优先；有效额度同时传给 provider 和 Context guard | 应保持同一有效值，不能只改 provider 参数 |
| 内置模型配置 | 本次核对未设置 max_output_tokens 模型覆盖；配置的 context window 为 262144、1000000 或 1048576 | window 足够大不代表 endpoint 接受同样大的输出上限，部署额度仍需核对 |
| `llm/protocol/responses.py` | forced_name 要求结果包含一个指定工具，允许其它可见工具 | 这是本地协议约束，不是 provider 原生必含保证 |
| `kernel/loop/phases/phase1.py` | 缺域选择在 LLM 解释阶段失败；域选择参数错误却在消费其它控制之后返回失败 | 两种相近的无效阶段输出，目前有不同的提交效果 |
| `kernel/loop/turn.py` | 连续失败的反馈去重累积，直到一个完整 Cycle 成功才清空 | 旧失败仍被称为“Previous cycle”，可能与后续已经生效的状态混淆 |
| `kernel/loop/phases/phase2.py` | TaskFailure 会停止 Cycle；scope 准备失败只返回 phase_results 和空 normalization | 后一种路径仍会进入 Phase3，与 AGENTS 的阶段失败语义不一致 |
| LLM/Phase completed Observation | task 仅记录 status；phase 记录 failed 等状态及控制结果 | 失败发生处缺少短原因，要到后续 Context 才容易解释 |
| `docs/design/llm.md` | 仍描述 Phase 内有界重试、临时收窄 scope | 与当前规约和主要实现冲突 |

此前真实记录中，四次 Phase2 output_limit 的 completion 均为 2048，其中 reasoning 分别为 2048、2048、2033、2048；五次 Phase1 返回了计划控制却缺少 select_action_domains。前者支持扩大生成空间，后者支持澄清多工具输出协议及未提交效果。它们是问题证据，不是代码分支、测试数据或预算选值的唯一依据。

## 一、生成预算与内容长度各归其主

### 生成额度

更新 standard/development 三类 task 和配置编辑器的 task 创建模板为 65536。调用仍可通过已有 Action model binding 显式选择不同额度，模型固定要求仍通过已有 request_overrides 表达。

预算流保持为：

```text
task 默认额度
  → 单次调用 / Action binding 覆盖
  → model.request_overrides 覆盖
  → 有效 max_output_tokens
      ├─ provider 请求参数
      └─ Context 容量核算的 reserved_output_tokens
```

删除 `ActionTaskFactory.create(max_output_chars=...)` 参数及其字符转 token 逻辑，调整 workspace.compose 调用。ActionTaskOutput.text 和 Workspace 提交 owner 继续按字符校验完整工件，TaskPrompt 继续动态说明实际字符上限。无需另建预算服务或引入隐式换算系数。

“保持 Context 输出预留与实际生成额度一致”指与本次请求**允许的最大生成量**一致，不是提前知道模型最终会生成多少。当前核算是：估计输入 token + 有效输出额度，不超过 window × compression_trigger_ratio。工具定义也属于输入。

例如当前 262144 window 和 0.8 阈值，65536 输出预留之后，估计输入约有 144179 tokens 的空间；实际输入估算还包括消息/工具包装。上限宽裕不要求模型每次用满，但长 Context 会更早进入既有容量恢复。

当前估算器以 UTF-8 字节数作保守 token 估计，未按实际 tokenizer 计数。因此它可能比供应商实际用量更早触发回收。扩大输出预算时验证这条正常路径；本计划不同时更换 token 估算算法，也不通过缩小输出预留隐瞒压力。

不采用 None 作为本轮默认：当前 None 会同时省略 provider 上限并按零预留，无法表达这里需要的容量语义。配置额度不宣称是模型能力；实施时核对目标 endpoint，确有更低上限则显式配置，不建立自动减半重试链。

### 文件与其它字符限制

本次按真实消费者区分如下，数字单位均为字符，token 项单独注明。新建议的字符额度仍待维护者确认。

| 约束 | 当前值 | 本次建议及语义 |
| --- | --- | --- |
| Workspace 完整文本写入/compose | 12000 | **65536**；支持更完整的脚本、报告和文档 |
| Home 内容写入/改写 | 16000 | **65536**；支持完整 Skill/指导文档，仍遵守 overlay/review 所有权 |
| 活动 Memory.md | 12000 | 保留；它是常驻工作记忆的容量，不是通用生成额度 |
| 持久 Memory 文档 | daily 32000；entity/concept 16000；fact 4000；note 24000 | 本次保留；不同文档的内容组织语义独立于 Phase 输出预算 |
| Workspace/Home 一页读取 | 4000 | 保留分页；大文件不应自动全部常驻 Context |
| Memory/Trace/Session Inspect 一页读取 | 8000 | 保留渐进披露语义 |
| Workspace analyze | source 24000；每参考 12000；answer 4000 | 属于有界分析输入/反馈，列入核对，不随通用生成额度隐式改变 |
| Web | 专用供应商生成 8192 tokens；落盘输出 1000000 字符 | 独立 capability 配置，本次不顺带修改 |

Workspace/Home 的 Python 默认值、standard/development 配置须同步；相关动态 TaskPrompt/校验读取 owner 的值，不在固定文案复制 65536。Workspace compose 继续通过 ActionTaskOutput.text 检查字符数，在其现有超限反馈中带上实际额度，例如“生成文本超过 65536 字符，文件未写入”；不借本次额度调整重构其它 owner 的全部异常协议。

Workspace 的 max_write_chars 约束其正式文本操作，并非工作区磁盘文件的通用大小限制；execution 直接写入的文件不因此获得同一额度限制。更大的文件上限也不保证任意文档都能放入单次模型输入，读取和生成仍遵守各自容量协议。

## 二、Phase1 保留独立工具，统一必需意图的校验边界

### 多工具输出

继续提供独立工具：select_action_domains 必需，set/remove milestone、set/remove todo、load/evict background 按需调用。合法示意：

```text
select_action_domains(domains=["execution"])
set_todo(key="run", status="in_progress", ...)
set_milestone(key="input", ...)
```

模型可只返回第一项，也可返回包含它的一组调用。这里展示的是意图组合，不要求 provider 按展示顺序返回工具。域选择 schema 补齐 minItems=1，与现有“至少一个有效域”校验一致；工具定义仍由 Action/Context owner 提供。

OpenAI 官方文档区分 generic required（调用一个或多个函数）与 forced function（只调用一个指定函数）；allowed tools 只是缩小可选集合，不能同时表达“必含域选择且可选其它控制”。本次核对的仓库 behavior 已使用 generic required，并非错误地把 Phase1 锁成单个域选择工具。因此不修改成 named forced choice。[官方工具选择语义](https://developers.openai.com/api/docs/guides/function-calling#tool-choice)

保留 ToolSelection 的“指定工具必含但不排他”含义、各 provider 的现有映射和 ResponseInterpreter 最终校验。已有正常 TaskPrompt 已表达域选择要求，本次不靠追加反复提醒来假装获得协议保证。扩大预算和改进失败反馈之后，仍可能有遗漏并产生一个失败 Cycle，这是选择多工具方案的明确取舍。

若要求从输出结构上更强地约束 domains，只能另选输出形态或增加调用。单个 submit_phase1(domains, controls) 可以把 domains 变成必填字段，但把不同工具参数嵌套在联合 schema 中；拆成两个模型调用则增加每个 Cycle 的大语境请求与提交边界。本次均不推荐，不预先实现兼容分支。

### 提交顺序（本轮新增建议，待确认）

将完整域选择校验移动到消费本次 Context 控制之前：

```text
LLM 输出解释及域选择校验
  ├─ 失败 → 本次控制未提交 → PhaseFailure → 下一 Cycle
  └─ 通过 → Context 控制归一化及 prepare/install → Phase2
```

缺少调用、重复域选择调用、空域列表、无效域，都在提交本次控制之前收敛。LLM 解释器拥有工具作用域/必含约束，Action 拥有域选择有效性，Loop 只安排顺序，Context 继续拥有控制更新。

域选择成立后，单个可修正控制问题仍由已有 ControlResult 表达，合法控制遵循现有 prepare/install 规则；不把每个可选控制错误扩大成整个阶段回滚。Phase2 后续失败也不回滚已经完成的 Phase1 控制。

这改变了当前“无效域参数仍可能更新计划”的行为。依据是 Phase1 必需意图未成立时，该阶段响应尚不具备提交条件；移动校验即可保持两种域选择失败的一致性，不需要事务快照或补偿逻辑。若维护者希望保留独立提交控制的语义，应保留当前顺序并逐项说明效果，不能使用统一的“未应用”反馈。

## 三、局部失败明确原因、效果和下一次读取边界

复用 TaskFailure、PhaseFailure、ControlResult、ActionPhaseResult，不新增失败分类树。

| 失败位置 | 反馈与执行效果 |
| --- | --- |
| LLM 达到输出上限 | LLM 短反馈包含有效 max_output_tokens；不接受截断输出中的工具作为成功结果 |
| Phase1 缺少或无效域选择 | 说明需包含有效域选择、允许其它控制；按推荐提交顺序说明本次控制未应用 |
| Phase2 TaskFailure | 说明本次 Action 意图未接受/执行；不暗示之前完成的 Phase1 被回滚 |
| Phase2 无可用 Action scope | 保留 Action owner 的 scope 失败事实，同时返回 PhaseFailure，停止本 Cycle，不调用 Phase3 |
| 已进入业务 owner 的控制/Action 局部失败 | 继续使用所属结果及 disposition，不改造成 LLM 或全局 Runtime 异常 |

Phase2 scope 分支是对现有规约的落实：ActionScopePreparation 继续负责准备结果，Loop 从已有失败结果取得短反馈并返回 PhaseFailure；不重新定义一套 scope 失败协议，不制造 Action 执行结果。不要将这个修正扩展为“所有 normalization 局部拒绝都必须全批失败”。

模型可见示意（实施时英文固定文案由所属 prompts owner 管理）：

> Phase1 未完成：输出需要包含有效的 select_action_domains，仍可同时调用其它控制工具。本次 Context 控制未应用。

> Phase2 生成达到 65536 token 上限，本次 Action 未执行；已完成的 Phase1 更新保留。

额度由 LLM owner 传入文案函数；域选择原因由 Action owner 提供；提交效果由 Loop 按真实路径添加。Phase 仍可使用 framework_task_failure 作为粗粒度原因，LLM 的细分 reason 保留在 TaskFailure 与 Observation，不重复建立 Loop 枚举。

下一 Cycle 的临时 TaskPrompt **只携带最近一个失败 Cycle 的反馈**，替换当前“连续失败累积直到完整成功”的行为。每次失败仍按发生顺序写入 TurnTrace，历史可以回看；TaskPrompt 不再建立一份无 Cycle 归属的失败历史。阶段名称与短原因足以指导修正，Working 表达当前实际状态。其它已有 Turn 完成阻塞反馈继续按其真实边界生成，不把反馈管理泛化成新模块。

## 四、失败发生处即可定位的 Observation

扩展现有事件，所有字段直接投影既有类型化结果或当前有效配置：

| 事件 | 增加的信息 | 研究用途 |
| --- | --- | --- |
| llm.task.completed | 失败时提供 reason、scope、constraint 和短 feedback | 区分供应商正常返回与 Task 协议通过 |
| loop.phase.completed | PhaseFailure 的 reason、feedback | 当场解释哪个 Phase 未完成；控制结果继续使用现有 control_results |
| llm.model.request | 本 attempt 有效 max_output_tokens | 核对实际请求额度及模型覆盖，不依赖 usage 反推 |

Task/Phase 失败不复制整个结果、raw response 或异常正文。provider.completed 仍只表示供应商调用完成，不能当作阶段成功。

前端配套范围仅为消费这些摘要：task.json 保存任务失败原因；attempt/meta.json 保存有效额度（不同 attempt 可以不同）；turn.md 显示短原因和效果并链接原证据。共享 request 的 messages/tools 去重策略保持其职责，完整 response 仍留在 cycles 证据。主线故障一次可读解释即可，不把重复 completed 事件和 constraint JSON 再扩成模型叙事。

后端先更新 `docs/endpoint/events.md` 及相关契约示例；前端消费按前后端协作规约单独对接，不另开日志或查询协议，也不以客户端推测填补未记录的原因。

## 改动范围与预期效果

| 所属模块 | 预计改动 | 预期效果 |
| --- | --- | --- |
| assets / infra config catalog | 三类 task 和新建模板 65536；确认后更新 Workspace/Home 字符默认值 | 新实例与新建任务使用宽裕额度，资源限制可独立配置 |
| kernel/action/tasks、Workspace compose | 移除字符到 token 的覆盖；保留并解释字符校验 | 模型可以充分推理，最终文件仍符合 owner 约束 |
| Action scope、Loop Phase1 | domains 非空 schema；域选择先校验再提交控制 | 工具意图独立，域选择失败的提交效果一致 |
| Loop Phase2、Cycle | scope 失败返回 PhaseFailure | 失败停在实际发生的 Phase，不经过空 Phase3 |
| Loop Turn、prompts | 最近失败的临时反馈；原因与效果的短文案 | 下一 Cycle 能明确修正，不反复混入已经过时的失败指令 |
| LLM、Loop Observation | 失败摘要、实际生成额度 | 轨迹在失败位置就有证据 |
| visualization 对接 | task/attempt 元数据及 turn.md 短反馈 | 从概览定位到完整调用，不膨胀大规模 Turn 的叙事 |
| docs/design、docs/endpoint、tests | 当前协议与协作行为同步 | 文档、测试和运行语义一致 |

预计主要修改已有文件，不需要新增业务模块、通用预算平台或联合工具包装。设计文档重点同步 llm、loop、action-model-retrieval、workspace、agent_home；删除 llm.md 中 Phase 内重试的旧描述。AGENTS 已有相应原则，无需再加入具体预算数字或每个反馈字段。

## 实施与验收

1. 确认下方两项新增决策，再实施代码；65536 token 默认值沿用维护者要求。
2. 更新 task/template 与确认的内容额度，移除字符/token 混用。验证 task 继承、binding 覆盖、model 覆盖，以及 provider/Context 使用同一有效值。
3. 实施 Phase1 校验顺序、Phase2 scope 失败结束边界与最新失败反馈。正常域选择加多个控制、无控制、控制局部失败均保持清晰行为。
4. 更新短反馈与 Observation；后端协议文档和前端消费分别落实。验证失败发生位置即可定位原因，输出额度来自实际 attempt。
5. 核心行为测试：缺域/无效域时不提交控制；有效域且局部控制失败的现有语义；Phase2 Task/scope 失败不进入 Phase3；Phase1 已提交状态不因 Phase2 失败消失；连续失败只在临时 TaskPrompt 保留最近反馈、Trace 保留完整事实。
6. 预算测试覆盖长生成与文件长度分别失败的路径、显式模型覆盖、较长 Context 的容量恢复；不以配置解析成功代替协作验证，不固定可编辑文案全文或真实轨迹中的 Cycle 次数。
7. 按 AGENTS 执行聚焦测试、Fast、完整 Full 和 ty；前端消费修改另跑对应测试与构建。真实 provider 行为只用明确授权的代表调用验证，本地测试不承诺模型遗漏概率已经下降。
8. 核对实际运行实例的显式配置；package assets 更新不会自动改写已有实例。代码、文档、验证及前端消费逐项完成后才标记 done 并归档。

## 本轮待确认项

1. **Phase1 推荐独立工具 + 必需域选择先校验再提交控制。** 这保留多工具表达能力，但接受 provider 没有原生“必含且可选其它”的保证；相较旧计划，新增的是无效域也不提交本次控制。是否采用这一完整语义？
2. **Workspace/Home 完整文本额度均建议 65536 字符。** 其它常驻记忆、持久 Memory 文档和分页/分析额度按上表保留，不随 token 默认值一起改大。是否按此范围放宽？

可行性结论：推荐方案复用现有结果类型、owner、配置优先级与 Cycle 生命周期，主要是调整配置、校验顺序和结果投影。可以实施；其明确限制是多工具协议仍可能遗漏域选择，输出上限提高会占用更多 Context 预留。上述取舍确认前维持 pending，本次分析不视为代码实施完成。
