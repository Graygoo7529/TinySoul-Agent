# Phase 协议、模型生成预算与失败反馈执行计划

状态：`pending`，分析及设计草案，等待讨论确认。2026-10-12。

本计划独立于已经归档的 Trace 导出工作。目前仅将“生成预算服务能力与灵活性”的原则补入 AGENTS.md；下述配置、LLM、Loop 和 Observation 改动均未实施。

## 目标和设计依据

给正常推理、工具参数和完整回答留下充足生成空间，让 Phase 的输出协议更容易正确表达，并让失败反馈准确说明原因和已经发生的效果。保持 Agent → Turn → Cycle → Phase 的唯一运行内核；LLM 解释模型输出，业务 owner 提交控制或执行 Action。局部协议失败结束当前 Cycle，下一完整 Cycle 读取反馈，不新增 Phase 内重试、自动补全 Action 或并行状态机。

需要分别解决两个问题：生成空间不足会使模型尚未形成有效输出就停止；Phase1 的多工具结果则需要同时表达必需的域选择和可选的 Context 控制。提高 token 上限有助于前者，但不能保证后者不再遗漏域选择。

## 已核对的现状

### 生成预算

| 位置 | 当前事实 | 影响 |
| --- | --- | --- |
| standard/development `configs/llm/tasks.toml` | frame_stage1、frame_stage2、llm_action 均为 2048 | 理解、工具选择和 Action 内生成均继承偏小默认值 |
| `infra/config/catalog/models.toml` task 创建模板 | 2048 | 新建任务仍会恢复小额度 |
| Action model-use bindings | 标准绑定未另设额度，通常继承 llm_action | core.answer/reason、Workspace 生成、检索模型任务都会受影响 |
| `ActionTaskCallBuilder.create` | 把 max_output_chars 转为 token 数，并与 binding token 值取小 | 工件字符限制混入生成预算；workspace.compose 无显式 binding 时用 12000 覆盖 profile，调高 profile 仍可能被它压低 |
| `LLMTaskRunner` | model.request_overrides 优先于合并后的 task/单次调用设置 | 实施时须核对模型覆盖，不能只改任务文件 |
| Context window guard | 有效 max_output_tokens 同时计入输出预留；None 按 0 预留 | 直接删除上限并不等于语义完整的“自由生成” |
| Web 的供应商生成额度 | 默认 8192，属于独立 capability 用途 | 需要独立评估，不能靠调 llm_action 顺带改变 |
| Workspace max_write_chars | 默认 12000，是文件提交/工件边界 | 与 Inspect 页、Trace 摘录、LLM reasoning token 分别属于不同职责 |

真实记录中 Phase2 有四次 output_limit，completion 均为 2048，reasoning 分别为 2048、2048、2033、2048。它证明该运行的生成空间确实被耗尽，不能据此断言模型本身不适合工具调用，更不应默认降低推理强度或更换首选模型。

### Phase1 工具语义

`ToolSelection.allowed_names` 是可见工具筛选；`forced_name` 是“返回结果必须包含这个工具，仍允许同批其它工具”的内部约束。目前只有一个必需名称，不存在必需名称列表。`ResponseInterpreter` 在返回 TaskResult 前统一校验该约束。

Phase1 合并 Context 的 set/remove milestone、set/remove todo、按需 load/evict background，以及 Action 的 select_action_domains。TaskPrompt 已明确要求域选择及同批控制，不是完全没有提示。当前 OpenAI SDK behavior 对 required 输出 `tool_choice=required`，保留其它可见工具；DeepSeek thinking 分支甚至不发送 required 参数，仍由本地解释器校验。这些是仓库当前适配事实，不把它们推断为供应商所有版本的能力承诺。

因此，不能把 `forced_name` 改为供应商“只能调用这个函数”的 named choice。那会把 TinySoul 的“必含且允许其它”改成“只能选它”。此前混合草案提出这种映射是不成立的，本独立方案撤回该建议。

真实记录中五次 Phase1 只返回计划控制，没有域选择；解释器返回 invalid_output_protocol，Loop 尚未进入 normalize_controls，因此那些计划更新没有应用。下一 Cycle 再提出相似更新并不必然是忘记之前已执行的操作。

### 当前失败反馈

- LLM 已有 TaskFailure.reason/scope/constraint/model_feedback，输出上限也保存了实际 max_output_tokens；反馈文本目前只说达到 token 上限。
- Phase1/2 只提取 model_feedback，使用统一的 framework_task_failure 记录；反馈没有说明本次控制或 Action 是否已生效。
- task 的 Observation completed 只有 status，Phase completed 只有 failed 等阶段事实，没有失败原因和短反馈。研究轨迹常需到下一次请求的 phase_note 中寻找解释。
- Phase1 的 task failure 在任何控制提交前发生；但域名参数归一化失败路径可能已经消费合法 Context 控制。两条路径不能都说“本阶段所有变更均未应用”。
- `docs/design/llm.md` 仍有允许 Phase 内有界重试、临时收窄工具的旧句，与当前 AGENTS、Phase1/2 代码和测试冲突，需要修正文档。

## 方案一：放宽生成预算，分清实际限制

建议三个默认 task 和任务创建模板统一以 **32768 output tokens** 作为讨论起点，保持现有模型优先级及 reasoning 设置。这个数字是建议的配置默认值，不是供应商能力结论；实施时核对绑定模型/端点可接受的额度，确有更低上限时用已有 model.request_overrides 表达，不新增能力注册平台或失败后逐层减半机制。必要的模型特殊覆盖仍是显式配置。

预算流继续为：task 默认 → 单次调用/Action binding 覆盖 → 模型固定覆盖 → 同一个有效值进入 provider 与 Context 输出预留。移除 `ActionTaskCallBuilder.create(max_output_chars=...)` 将字符数当成 token 上限的转换；Workspace 继续在 TaskPrompt 和 ActionTaskOutput/提交 owner 校验工件字符限制。这样提高生成额度不会被字符数悄悄覆盖，也不会令长 reasoning 被等同于长文件。

本计划不统一放大 Inspect 页、Trace 摘录或持久工件尺寸。它们与模型生成能力是不同边界。Workspace 12000 字符的真实文件额度、Web 8192 的用途额度在本次清单中明确暴露，若维护者希望同时放宽，分别按文件/搜索用途决定数值，不借生成预算改动隐含更改其它资源契约。

不建议直接设置所有 task 为 None：当前它同时表示不发送 provider 上限、Context 预留为零。若将来选择 provider 自动上限，应先明确输出预留来源；目前显式宽裕值更一致，也无需引入独立自适应预算系统。

提高预留可能使长语境更早触发现有 Context 回收，这属于同一容量账本的正常结果。验证应同时检查正常长输出和长 Context，不以“配置数值成功解析”代替可用性验证。

## 方案二：Phase1 的两条可选路线

### A：保留当前多工具协议

继续要求 select_action_domains，可同批返回其它 Context 工具。保留通用 required 适配和解释器校验，改进下节的效果反馈。扩大预算后再观察正常任务中的遗漏情况。

优点是工具定义、控制归一化、provider-neutral 协议均延续现有设计。限制也明确：provider 的 required 只能保证“至少某个工具”，不能保证“指定工具必含”；当前提示已表达要求，继续重复或加重措辞不能构成结构性保证。这条路线接受偶发缺项造成一个失败 Cycle，不能宣称已从协议结构上消除问题。

### B：Phase1 一次提交完整阶段意图（倾向推荐，需确认）

由 Loop 组装一个 Phase1 专用 Control Tool，例如 `submit_phase1`。模型一次返回必需的 domains、可选 intent 和可选 controls 列表；controls 可为空，也可包含多个更新。概念示例：

```json
{
  "domains": ["execution"],
  "intent": "Collect finished work",
  "controls": [
    {"name": "set_todo", "arguments": {"key": "run", "content": "Run background work", "status": "done"}}
  ]
}
```

模型仍能选择全部现有 Context 能力，但“域选择”成为同一次阶段结果的必需字段，不再需要在多个独立 tool call 中额外记住一次必需调用。只暴露这个阶段工具时，供应商 required 与 TinySoul 单一阶段提交更加接近；仍不要求所有 provider 原生支持 required，也不假定模型必然返回合法参数。

所有权和数据流：

1. Loop 只拥有阶段结果的组合结构；domains 枚举和解释继续来自 Action 门面，controls 的可用名称、说明和参数 schema 继续来自 Context 门面。由这些现有声明组合嵌套 schema，不在 Loop 复制业务字段说明。
2. controls 是当前 Context 提供的有限操作集合，参数与名称在 schema 中关联；不能退化为任意 name 加无约束 JSON 的万能工具入口。按现有顺序归一化并 prepare/install，不扩展到 Action 或 Job 调度。
3. 外层必需字段、重复阶段提交及域选择先校验；阶段结构不成立时不提交其中控制。合法阶段结果内的控制错误继续由现有 ControlResult 表达；不把单个控制失败扩大为新事务或整轮回滚。
4. 解包后复用现有 Context normalization/signal 路径，嵌套控制通过父调用 id 与位置建立可追踪关联，不能伪造成额外的 provider 原生 tool calls。
5. 通用 LLM ToolSelection 仍保留“必含但非排他”的语义。这个方案只调整 Phase1 的业务输出形态，不改成所有 LLM 任务都使用阶段信封。

成本是修改 Phase1 组装、Action 域选择的门面输入、控制投影关联以及相应测试和设计文档。嵌套参数 schema 需要核对当前适配器支持，不强制启用供应商 strict 模式，也不建立通用 schema 编译器。名称、参数形式和控制失败后的继续语义均需在实施前确定。

不推荐把 Phase1 拆成“更新 Context”与“域选择”两个模型调用：每个 Cycle 增加一次大语境请求，还引入两个 Task 之间的提交边界。也不建议自动为缺失域选择补默认域、从 raw_response 挑部分工具强行执行，或把每次更新计划都变成一个独立 Cycle。

## 方案三：短反馈明确失败原因和实际效果

复用现有 TaskFailure、PhaseFailure 和 ControlResult，不引入新的失败分类树。分层表达：

- LLM 的反馈负责本次调用为何不合格；输出上限反馈包含 owner 已知的有效额度，必需工具缺失反馈明确“需包含该调用，允许同批其它可见工具”。数据从现有约束输入，不靠匹配异常字符串猜测原因。
- Loop 根据失败发生的位置补充效果。例如 TaskFailure 导致 Phase1 提前返回时：本次 Context 控制未应用；Phase2 TaskFailure 时：未接受/执行本次 Action。合法控制已经提交后的域选择错误按实际 ControlResult 描述，不能套用“全部未应用”。
- 反馈沿现有 phase_note 与下一 Cycle 路径进入 Context，不复制模型返回的大段文本，也不携带 traceback。模型无需阅读内部的 constraint/frame_data JSON 才能理解失败。
- 保留 framework_task_failure 作为阶段原因，不为每种 LLM reason 新增 Loop 原因；机器诊断通过所属 LLM 事件保存已有稳定字段。

示意反馈（最终英文固定文案由所属 prompts owner 维护）：

> Phase1 未完成：本次输出需要包含域选择；本次 Context 控制尚未应用。

> Phase2 的生成达到 32768 token 上限，本次没有 Action 被执行。

它们说明可核对的事实，不强令模型减少思考、只执行一个 Action 或必须把任务拆成固定步骤。配置不足由配置解决，业务参数错误由现有局部反馈修正。

## 方案四：让现有观察事件能说明失败

为了在失败发生处就能定位原因，扩展原有事件的有限投影，而不是新增日志链路：

- `llm.task.completed` 在 TaskResult 失败时投影已有 reason、scope、constraint 和短 feedback。成功仍只是成功，不把 provider.completed 当 task 成功。
- `loop.phase.completed` 在有 PhaseFailure 时附已有 reason 和短 feedback；控制效果仍使用已有 control_results。
- `llm.model.request` 记录本次计算后的有效 max_output_tokens；导出 attempt meta 展示它，避免只凭 completion usage 猜配置。模型覆盖可能随 attempt 变化，所以它属于调用元数据，不混入共享 messages。
- 消费这些字段的前端导出器将 task 失败投影到 task.json，概览可直接在该事件位置显示反馈；没有字段的旧窗口仍保留缺失事实。Endpoint/Observation 设计同步记录新增字段。

这些字段是研究本次问题的真实消费者所需，不增加重试建议枚举、诊断树、原始 provider 报文或第二套持久事实。导出计划已经完成的语义仍是“导出当前确实留存的数据”；这里是后续业务事件解释能力的改进。

## 预计改动范围

| 所属模块 | 改动 | 预期效果 |
| --- | --- | --- |
| assets / infra config catalog | 三类 task 及创建模板预算；检查模型覆盖 | 新实例和新建任务不再继承 2048 |
| kernel/action/tasks、Workspace 调用处 | 删除字符额度转 token 额度，保留 owner 工件校验 | 推理空间与文件长度相互独立 |
| llm / prompts.llm | 有效预算和有限失败反馈的投影 | 失败时可直接看到真正的限制 |
| kernel/loop / prompts.kernel.loop | 效果反馈；若选 B 则调整阶段结果组装与解包 | 清楚区分未执行与已提交，并减少必需调用遗漏 |
| Context / Action 门面（仅 B） | 复用定义和归一化，提供组合所需的明确输入 | 同一业务语义保持唯一 owner |
| Observation / visualization | 消费已有事件上的新增诊断摘要 | 失败不必等下一次请求才能解释 |
| docs/design、docs/endpoint、tests | 当前协议、预算、失败路径和协作契约 | 文档与代码一致 |

AGENTS.md 的预算原则已按本轮授权补充。其它设计文档在代码实施时同步；尤其移除 llm.md 的 Phase 内重试旧描述，不保留与现行规约矛盾的兼容语义。

## 实施与验证顺序

1. 确认预算默认值和 Phase1 路线；选 B 时核对当前所有 provider adapter 能否传递对应嵌套 schema，先完成正常数据流的类型与门面设计。
2. 更新 task/template 预算，分离 Action 字符/token 约束；验证继承、调用覆盖、模型覆盖与 Context 输出预留使用同一有效值。
3. 实施确认的 Phase1 路线和短反馈；保持 PhaseFailure 结束 Cycle，验证失败前未提交与合法控制已提交的区别。
4. 同步 Observation 有限诊断、前端导出投影及设计/Endpoint 文档。测试既有工具定义和真实数据流，不固定可编辑提示词全文。
5. 定向覆盖：域选择加多个控制、无控制、缺域/无效域、控制局部失败；输出上限不能放行不完整 Action；Phase2 多 Action 和 Phase3 LLM 仍正常。
6. 测试正常长脚本/回答生成，以及较长 Context 下的容量恢复；保留 provider/model fallback 现有语义，不把 protocol failure 改为供应商重试。
7. 完整本地 Fast/Full/ty 与受影响前端测试/build。真实 provider 验证使用显式授权的代表任务；本地测试不能证明实际模型遗漏率已经降低。实际生效配置应核对到运行实例，不能把 package assets 更新误认为已修改所有用户实例。

## 待讨论的决定

1. 是否采用 32768 作为三个 task 的共同默认输出额度，并保持当前模型顺序与 reasoning 强度？若希望更高，可以提高默认，但需核对模型/端点实际接受值和 Context 预留。
2. Phase1 是否采用 B 的“单次完整阶段提交”，还是选 A 保留现有多工具结果并接受偶发局部失败？倾向 B，因为它将阶段的必需部分放回同一结构，保留可选控制的能力；它是协议调整，需要维护者确认，不作为 Trace 修复顺带实施。

预算与反馈改动的边界已经明确，Phase1 输出形态仍待选择。本计划保持 pending，不把方案讨论或配置建议标为完成。
