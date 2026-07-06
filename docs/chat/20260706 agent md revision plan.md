# AGENT.md 修改计划（2026-07-06，未定稿，操作化版本）

背景：infra、runtime、llm、action 四模块重构完成后，对照 AGENT.md 与现状（模块代码、docs/design 文档、tests、提交历史）逐节核对形成本计划。本文档只描述修改操作，不直接改动 AGENT.md。

修改原则（依维护者反馈确定）：

1. AGENT.md 只做局部调整、补充和修正，不做章节级重构，不重排现有条目，不迁移核心定义内容；
2. 「项目规划」定位为**随模块实现动态增加的运行方式规约**，供后续模块理解已实现模块的协作方式——因此不改写为进展地图，只补充缺失模块的规约条目；进度信息放「当前任务」；
3. 「当前任务」保留原有语言规约（"这次重构不是简单的改造原有代码……"），补充实现纪律约束，针对已观察到的编码偏差（如绕过三层失败语义、按习惯抛裸 ValueError）；
4. 修正阐述不准确、与实践不符的表述（如设计文档"不写具体类名"规则）。

每条计划的格式为：**定位**（引用现有原文片段）、**操作**、**新文本**（完整给出，可直接粘贴）。「核心定义」一节不由 AGENT 修改，相关观察列于 P9。

---

## P1 「项目规划」补充已实现模块的运行方式规约 `pending`

定位说明：本节现有 9 条全部是 LLM 层与工具语义的规约，缺少 infra、runtime、action 的同类条目；后续 context/loop 模块设计时需要理解这三个模块的运行方式。现有 9 条准确，全部保留不动。

**操作 1**：在「## 项目规划」标题之后、第一条"TinySoul 拥有独立的上层动作层"之前，插入一句节首定位说明：

````markdown
本节是已实现模块的运行方式规约，随模块实现动态补充，供后续模块设计时理解既有模块的协作方式；详细设计见 docs/design/ 对应文档。
````

**操作 2**：在现有最后一条"LLM 消息内容需要支持灵活的多片段结构……"之后，追加以下条目：

````markdown
- Infra 提供配置环境与 JSON 边界。配置显式加载、显式传递，模块不在导入时读取配置或创建全局单例；来自模型输出、配置文件或外部接口的动态 JSON 数据，在进入模块内部边界时转换为明确的 JSON 值结构。
- Runtime 提供运行位置（RunScope）、Runtime 语义异常、Trap 处理器表、运行转移和 SignalBus。控制流变化（结束 Turn/Cycle/Program、全局恢复）统一构造 Runtime 语义异常进入 Trap，Trap 返回指向运行位置栈 frame 的运行转移，由各级运行器消费；模块事件与状态变更请求通过信号表达，由信号处理器在明确边界批量消费。
- Action 模块通过 ActionEngine 向上层提供唯一装配与调用入口，承担 Phase1 域作用域、Phase2 动作作用域与归一化、Phase3 批次执行。每个模型侧 action tool call 在 Action 模块内恰好收敛为一个局部 ActionResult；无法归因到单个 call 的阶段性问题收敛为 phase-level result；执行输入自包含已解析的 action 定义，执行期不回查 catalog。
- Action 后端分工：native 运行在宿主线程，只能协作式响应取消；需要硬停止语义的动作使用 subprocess 或 script 后端。后端 options 属动态边界，在 catalog 加载期由按 handler 注册的校验器校验。
````

注：HOW 文档注入（现有第 6 条提及）与 llm_step 后端属于挂起接口，待 context/loop 起步时定型；是否在对应条目后加"（待 context/loop 定型）"标注，由维护者定。

---

## P2 「当前任务」保留原文并追加进度与实现纪律 `pending`

**定位**：「## 当前任务」下整段（"彻底地重构 reference\tinysoul_v1。注意，这次重构不是简单的改造原有代码……并优先考虑更清晰的设计思路。"）。

**操作**：原文一字不改，在其后追加：

````markdown
当前进度：infra、runtime、llm、action 已完成；下一模块为 context 或 loop，二者共同决定 how_action 注入、hook 服务上下文等挂起接口的定型。每完成一个模块，应同步补充「项目规划」中该模块的运行方式规约，并更新本节进度。

重构实现纪律：

- 实现必须遵守项目失败处理三层语义与 Runtime 异常体系。新增任何 raise 前，先归类该失败属于局部结果、模块边界异常还是 Runtime 语义异常（见「代码风格」）；不得按个人编码习惯随手抛出 ValueError、RuntimeError 等通用异常表达模块失败。
- 新模块的失败语义、组装入口、动态边界处理应对照已完成模块的既有模式（failures.py、bridge、Engine/Builder、加载期校验器），不自行发明平行机制。
````

---

## P3+P4 「运行环境」扩展为「运行环境与验证」`pending`

**定位**：从「## 运行环境」标题到 conda 代码块结束。

**操作**：整节替换为（原有内容全部保留，仅补充）：

````markdown
## 运行环境与验证

- 默认运行环境为 Conda 环境 `TinySoul`（Python 3.13）；默认 shell 为 Windows PowerShell。
- 依赖以 `pyproject.toml` 为准。
- 需要运行 Python、测试或开发命令前，优先使用：

```powershell
conda activate TinySoul
```

- 修改代码后、声明任务完成前，必须运行并通过：

```powershell
python -m pytest tests -q
ty check tinysoul
```

- 测试约定：
  - 测试按 `tests/<module>/test_<切面>.py` 组织，镜像模块结构；
  - 需要文件系统的测试使用 conftest 提供的 `local_tmp` fixture（`.test-tmp` 本地目录），不直接使用系统临时目录；
  - 触网或调用真实供应商的测试默认 skip，需显式开启。
````

注："依赖以 pyproject.toml 为准"需配合勘误 2（requirements.txt 取舍）一起决定。

---

## P5 「工作方式」追加提交约定 `pending`

**定位**：「## 工作方式」最后一条"在继续设计或实现时，如果发现实际代码……不要用敷衍的临时性补丁绕过冲突。"

**操作**：在该条之后追加：

````markdown
- 提交信息使用 `类型(范围)：中文摘要` 格式，类型收敛为 feat、fix、opt、refactor、doc、analysis。
- 提交前必须完成「运行环境与验证」中的验证命令。
- AGENT 默认不主动提交；提交由维护者执行或明确指示。
````

注：第三条与现状实践一致（历史提交均由维护者完成），写入前请确认。

---

## P6 「代码风格」原位插入新条目（不重排现有条目）`pending`

现有 19 条全部保留、不分组、不移动；只在语义相邻位置插入以下条目。

**操作 1**：在"错误处理、状态变更和副作用边界应显式表达，不依赖隐式约定或字符串拼接。"之后插入：

````markdown
- 稳定标识符（失败类型、执行阶段、状态、模式等）使用 `StrEnum`；核心数据对象使用 frozen dataclass，并在 `__post_init__` 中校验不变量。
````

**操作 2**：在"模块内部可以使用普通 Python 异常或模块私有异常表达内部失败；跨出模块边界……避免供应商、解析器或具体实现错误类型污染全局运行控制。"之后插入两条：

````markdown
- 模块私有异常至少区分调用契约错误与内部不变量错误（如 `XxxContractError` / `XxxInvariantError`）；注册表、目录类接口未命中应抛出模块契约错误，而不是裸 `KeyError`。
- 表达模块语义失败时，不直接抛出裸 `ValueError`、`TypeError`、`RuntimeError` 等内置异常；应使用模块私有异常，或转为局部结果。模块私有异常可以继承内置异常类型，但抛出点必须表达模块语义。
````

**操作 3**：在最后一条"增加新的 py 文件时要谨慎……避免架构模糊不清晰。"之后插入两条：

````markdown
- 模块对上层（Loop/Context）暴露单一组装门面（Engine/Builder 风格）作为装配与调用入口；模块内部散件默认只服务于模块内部与测试。
- 可扩展的动态边界（如 action backend options）应支持按 handler 注册加载期校验器，在入口尽早转换为明确类型；执行期可保留防御性校验，但防御失败应转为局部结果，而不是静默降级。
````

**存量冲突提示**：操作 2 的裸内置异常约束与存量代码不一致——llm（`messages.py`、`model_chain.py` 等）与 runtime（`trap/` 下）目前大量使用裸 `ValueError`/`TypeError` 表达不变量与契约失败，只有 action 模块使用了模块私有异常。写入该条后需维护者决定：（a）回溯整改 llm/runtime（建议另开一篇 analysis 笔记跟踪）；或（b）仅约束新代码，存量随后续模块工作顺带收敛。

---

## P7 「文档规则」修正不准确表述并补充命名约定 `pending`

**操作 1（修正，属"阐述不准确"）**：`docs/design/` 子列表中"不写具体类名、方法名、代码业务细节、具体类型字段或方法清单。"与现有实践不符——action.md、llm.md 均使用 `ActionResult`、`ActionEngine` 等核心类型名标识协议对象，且这种用法是合理的。建议替换为：

````markdown
  - 可以使用稳定的核心类型名标识模块协议对象，但不罗列类型字段清单、方法清单或代码业务细节。
````

**操作 2**：在 `docs/design/` 子列表"存放整体或模块级设计思路。"之后插入：

````markdown
  - 每个模块应有对应的 `docs/design/<module>.md`，在模块重构完成时创建。
````

**操作 3**：在 `docs/chat/` 子列表末尾插入：

````markdown
  - 文件名使用 `yyyymmdd 主题.md` 格式。
````

**操作 4**：在 `docs/analysis/` 子列表末尾插入：

````markdown
  - 文件名使用 `yyyymmdd 主题.md` 格式；全部条目完结后，可在文件名中加 `-done-` 标记。
  - 复查发现的新问题以追加小节（如 R 编号）记录在同一笔记或新笔记中；工作流为：分析 → 维护者实施 → 复查 → 状态更新。
````

---

## P8 「工作经验」追加 `pending`

**定位**：「## 工作经验」最后一条"不要把 `Mapping[object, object]` 当作……并在动态数据入口做字符串键校验。"

**操作**：在其后追加：

````markdown
- 全新代码同样会滋生兼容 alias、空壳类型、未消费字段与参数这类死抽象；review 时应把死抽象作为专项检查项，而不是只检查错误处理与类型。
- 编码中容易按习惯抛出裸 `ValueError` 等内置异常而绕过三层失败语义。新增或修改 raise/except 时，应显式对照三层语义归类；review 时把裸内置异常和过宽的 `except Exception` 作为检查项。
````

---

## P9 核心定义相关观察（仅供维护者决策，AGENT 不修改）`pending`

依"局部调整"原则，不再建议迁移核心定义内容，仅保留两项事实观察：

- **可观测性段落是"应然"**："tinysoul 可观测性：实现三个层级的终端显示……"描述的能力尚未实现，是核心定义中少数与现状不符的内容；待可观测性模块落地时由维护者核对该段与实现一致性。
- **核心定义含具体类名**："行动执行/Action"段现含 ActionEngine、ActionExecutionControl 等类名，类名重构时需维护者手工跟改；若希望降低维护耦合，可将类名改为职责描述（"组装门面""执行控制"），细节留给 docs/design/action.md。

---

## 勘误（顺带报告）`pending`

1. `docs/design/llm.md` 模型侧工具一节仍使用过时术语："Action Tool Call 被归一化为 Action Invoke Draft，之后由 Phase3 校验和执行。"——action 设计已明确 Phase2 输出就是规范化 ActionCall，不叫 draft。应改为"Action Tool Call 被归一化为 ActionCall，之后由 Phase3 装配执行。"
2. `pyproject.toml` 声明 `readme = "README.md"`，但仓库没有 README.md，打包构建会失败。操作二选一：补一份最小 README.md（项目简介 + 指向 AGENT.md 与 docs/design/）；或删除该行。
3. `requirements.txt` 与 pyproject dependencies 内容重叠。操作二选一：删除 requirements.txt，统一 `pip install -e .[dev]`；或保留并在文件头注明"仅作为 Conda 环境安装镜像，依赖清单以 pyproject.toml 为准"（与 P3+P4 表述保持一致）。

---

## 建议落地顺序

1. 事实性修正：P7 操作 1、勘误 1（术语与规则准确性）；
2. 低争议补充：P2、P3+P4、P7 其余操作；
3. 规约固化（需确认措辞）：P1、P5、P6（含存量冲突决策）；
4. 补充：P8；
5. 维护者决策项：P9、勘误 2/3。

除 P9 外，各条新文本均可直接粘贴执行；执行完成后请将对应条目标记为 `done`。
