# 双语界面收尾与 Cycle 术语统一执行计划

日期：2026-11-04

状态：done（2026-11-04 完成 P1–P5，按 AGENTS.md 和 A1–A10 逐项核对后归档）

核对基线：`1364e5d6`，`feat(visualization): 完成中英文界面收尾与文案治理`。建立计划前工作树干净。

依据：[AGENTS.md](../../../AGENTS.md)、当前模块实现，以及此前关于双语收尾和 Cycle 术语的讨论。

关联归档：

- [前端中英文界面与共享语言执行计划](20261102-done-前端中英文界面与共享语言执行计划.md)
- [前端双语界面收尾执行计划](20261103-done-前端双语界面收尾执行计划.md)

两份旧计划已经归档。本计划承接复核时发现的具体缺口，不重新建设语言配置和翻译框架，也不以旧计划的完成状态代替本次验收。

## 1. 目标与改动预览

本次统一处理三件相互关联的事：补齐双语文案与显示边界；统一 Cycle 的 Phase 术语；使 Trace 展示、测试夹具与真实 Action 协议一致。语言仍是后端项目共享的展示偏好，业务事实仍由原模块拥有。

| 当前情况 | 实施后的效果 |
| --- | --- |
| 中文 Context 设置中仍有整段英文说明，少量英文说明与现行行为不一致 | 两种语言均可读，预算、超时、语境说明与真实行为一致 |
| 三段 Cycle 已使用 `CyclePhase`，但文档、模板、任务标识仍混用 Stage1/2 | 同一执行层级统一称 Phase1/2/3 |
| Phase 绑定控件重复写死 `frame-stage1/2` | 默认选项显示“使用默认任务链”，实际任务 ID 来自后端配置投影 |
| 凭据按后端标题字符串分组，特殊分组也用英文句子判断 | 用稳定身份分组，标题只负责显示；改标题不改变分组身份 |
| Action 详情读取不存在的 `failure.stage`，部分夹具使用 `execution` | 从结果顶层读取 `stage`，与当前 `ActionResultStage` 保持一致 |
| 前端行动摘要用 `stage=plan/result` 表示展示种类 | 改用 `kind=plan/result`，与 Cycle Phase、Action 处理环节分开 |
| 部分测试仍锁定中文句子，浏览器脚本混用旧中英文选择器 | 使用稳定路由、协议值、当前字典和测试自有内容验证行为 |

运行层级维持：

```text
Agent
└─ Turn
   └─ Cycle（可重复）
      ├─ Phase1：更新语境、选择行动域
      ├─ Phase2：生成并归一化 ActionCall
      └─ Phase3：组装和执行 ActionBatch，反馈结果
```

一次 Action 的 `stage=normalize/prepare/hook/schedule/execute/timeout` 表示结果产生的处理环节。这些值不是另一组 Cycle Phase，也不表示每次调用都依次经过六个步骤。

## 2. 现有设计与已核实的问题

### 2.1 已有主线继续复用

- `gateway/presentation.py` 的 `PresentationService` 保存共享 Interface 配置，默认 locale 为 `zh-CN`，另支持 `en-US`；保存展示配置不触发 Agent generation 激活。
- `uiPrefsStore` 与 `presentationController` 管理服务端确认值、待提交 patch 和连接切换时的清理，不另外建立本地语言持久化。
- `i18n/core.ts` 提供纯翻译与 `UiText`；React 使用 `useI18n()`、`LocalizedText` 在显示时解析。需要跨渲染保存的固定提示保存 message 描述，外部正文保留字符串。
- Settings 的配置保存、校验和生效仍走原有草稿、Endpoint、Infra 与业务 owner 链路；翻译只处理显示投影。
- `CyclePhase`、`RunLevel.PHASE`、Phase 单元与 `CycleRunner` 已表达正确执行层级。`loop.phase.*` Observation 及其 `phase` 值也已统一，不需要重建内核。
- `ActionPhaseResult` 同时包含 `phase` 和 `stage`，分别描述 Cycle 位置与 Action 模块处理环节；这个区分本身合理。

### 2.2 本次需要处理的事实

| 范围 | 当前实现位置与事实 | 处理方向 |
| --- | --- | --- |
| 中文遗漏 | `i18n/messages/zh-CN/settings.ts` 的 Context、专用模型连接等说明仍为整句英文 | 对照页面与 owner 补齐，并简化说明 |
| 文案语义 | 英文预算说明仍称耗尽后直接结束，超时说明写成 per batch；另有 `owner&apos;s` 字面文本 | 按真实执行语义修正双语说明 |
| catalog 文案归属 | `i18n/catalog/index.ts` 内嵌 `choiceText` 中文表；`zh-CN.ts` 已管理其余 catalog 文案 | 文案表统一放语言资源，adapter 只做身份匹配与投影 |
| 凭据分组 | `collectionDrafts.ts` 只保留 `groupTitle`；`CredentialsPage.tsx` 以标题作为 Map/React key，并比较两条英文句子 | 分组身份与标题分开，不通过文案分支 |
| 默认任务链 | `TaskProfile.FRAME_STAGE1/2`、`CycleSettings`、两套模板和测试仍使用 `frame-stage1/2` | 一次同步改为 Phase 命名，不保留兼容别名 |
| 前端重复默认值 | `PhaseBindingsPage.tsx` 的 `ownerDefault` 写死后端默认任务名 | 删除这个重复事实，保留清除覆盖的原行为 |
| 固定文案 ID | 两个 Settings ID 含 `Stage2`，值也称 Stage 2 | 改成不包含旧术语的语义 ID |
| Trace 协议漂移 | `ActionDetailPanel.tsx` 读取 `failure.stage`；`facts.test.ts`、`panels.test.tsx` 等夹具使用 `stage: "execution"` | 按真实结果 envelope 展示和造数 |
| 展示类型 | `ActionGlimpseData.stage` 实际是 `plan/result` 分类 | 改成 `kind`，不与执行状态混用 |
| 测试遗漏 | `SettingsPage.test.tsx` 断言整组中文标题；`test/e2e/presentation.pw.ts` 混用旧英文入口和中文控件文本 | 调整受影响路径的选择器与逻辑断言 |
| 文档偏差 | `i18n.md` 声称 group/surface 有翻译投影，实际动态标题保留 source；浏览器验收范围记载不准确 | 当前设计文档按真实行为改写，历史勘误记在本计划 |

`CredentialsPage` 的问题是把标题当身份，并非已经证实的 locale 缓存冻结；动态后端标题直接显示 source 本身符合现行边界，不能把它误判为全部必须翻译。

## 3. 确认的设计边界

### 3.1 文案与业务事实

| 内容 | 身份与显示规则 |
| --- | --- |
| 前端固定按钮、说明、空态、提示 | 稳定 message ID；中英文资源同步维护 |
| 已知 ConfigCatalog 字段 | 按稳定 `field.path`，含既有通配路径，投影标题和说明 |
| 独立 document 字段 | 按 `documentSet/documentKind/path` 完整身份投影 |
| collection | 按 collection ID 投影 |
| 字段 choice | 按字段路径与原始 choice value 投影标签；提交值不变 |
| 动态 group/surface 标题 | 保留后端 source；其 ID 可参与分组，标题不参与业务判断 |
| 前端固定导航分组 | 使用已有 `settings.group.*` / `settings.page.*` 文案体系 |
| 模型、provider、任务链、action 名、用户正文、文件、ref | 保持原值，不通过自然语言匹配翻译 |
| 已登记协议值的显示摘要 | 依据原始 code/value 取标签；未知值显示原值，原始诊断保留 |

后端字段标题改写不会使中文映射消失，因为映射不匹配原句；新增路径、choice 或 collection 没有翻译时仍能显示 source 并正常编辑。若某个既有路径的业务含义改变，仍需同步审阅对应翻译，不能把稳定 ID 理解成自动保证语义正确。

保持 `UiText = string | message descriptor` 的现有轻量边界，不恢复 `settingsText/rawText`，不增加通用翻译服务、全量 catalog 镜像或后端双语状态。只在确需跨渲染保留固定提示的地方使用描述，不把即时显示文字全部包装成对象。

### 3.2 Phase 与 stage 的使用规则

| 概念 | 规范名称 | 本次动作 |
| --- | --- | --- |
| Cycle 的三个执行阶段 | Phase1、Phase2、Phase3；机器值 `phase1/phase2/phase3` | 清理 Stage1/2/3 同义残留 |
| UI 标签 | “阶段 1：更新语境”等通俗标签；英文可写 `Phase 1` | 沿用现有 Phase 文案入口，不要求所有显示空格形式一致 |
| Action 结果产生环节 | `ActionResultStage` / `stage` | 保留；详情中称“处理环节” |
| Action Phase 内部处理 | `ActionPhaseResultStage` / `stage` | 保留 scope/normalize/prepare/run 的局部含义 |
| Control 处理环节 | `ControlResultStage` | 保留 normalize/consume |
| Turn 资源释放顺序 | `TurnResourceStage` | 保留，不属于 Cycle |
| 检索覆盖与局部处理 | `SearchCoverage.stages/missing_stages`、请求 steps | 保留协议；说明中称检索环节或管道步骤 |
| 调度诊断中的局部 stage | availability、root_request、daily_rollover 等 | 保留，与根调度含义相符 |
| 配置暂存、事务 staging、事件 stage 操作 | stage 动词 | 保留 |
| 前端行动摘要的 plan/result 分类 | `ActionGlimpseData.kind` | 改名，值保持 plan/result |

不做全仓 `stage → phase` 替换，也不加禁止出现 `stage` 的源码扫描测试。逐项根据所属 owner 和消费者判断。

## 4. 详细实施设计

### 4.1 双语文案补齐与语义校正

集中检查 `settings.ts` 的以下显示路径：

1. Context 页面：背景组成、Trace 分段、可选固定 identity/journal、当前占用、加载中、无活动 Turn、关联模块限制。
2. Home/Session 页：跳往 Context 设置的只读说明。
3. 专用模型提供方页：Embedding 和 decision model 的连接与凭据说明。
4. Execution/Budgets 页：单次 Action 调用总时限、各类 Turn 的 Cycle 预算，以及用户轮等待补额或中断的行为。
5. 简短分类和字体选项：Actions、Compression、System、Serif、System mono 等按实际界面语义翻译；Inter、JetBrains Mono 等字体名保留。

文案以用户正在做的事为中心，例如“相关设置”“当前语境占用”“这项限制可在语境设置中调整”，避免把 owner、projection、MessageStack 等内部组织概念直接堆给用户。必要技术单位与实际限制应保留，例如字符数、图片字节数与 token 用量的区别。

英文预算说明不再笼统声称所有 Turn 耗尽即结束；明确用户轮可以等待补额或中断。超时说明对应 `ActionBatchRunner` 为每次 execution 管理的总时限，不说成整个 batch 共享一个总时限。这里只修正文案，不修改预算、等待或取消逻辑。

修复字典中的 HTML entity 字面残留。允许 API、JSON、TOML、Embedding 和专有名称在两种语言中相同；中英文值相同只用于一次性人工定位，不成为永久测试规则。

两个包含旧术语的 ID 统一调整：

| 旧 ID | 新 ID |
| --- | --- |
| `settings.candidateOriginsStage2MayCombineAtLeastOne` | `settings.search.sourcesHint` |
| `settings.constraintOperationsAvailableToStage2MayBeEmpty` | `settings.search.operationsHint` |

同步修改 `SearchPoliciesPage`、两份字典和实际测试消费者；删除旧 ID，不留转发。其他已有稳定 ID 不因句子润色而批量改名。

### 4.2 catalog 投影与凭据分组

将 `choiceText` 移至 `i18n/catalog/zh-CN.ts`，由 adapter 导入。复用已有文案类型，避免复制同义类型。adapter 保持原对象不变，不改 schema、path、choice value 或约束。

凭据分组使用最小的身份与标题结构：

- `CredentialReferenceSite` 保留引用 path、引用 kind，增加稳定分组 key，标题仍保留后端 source。
- 已解析 group 使用 `group:<id>`；回退 surface 时使用 `surface:<id>`；未找到描述时使用已声明 group 身份和原有可读回退。命名空间只防止两种已有身份冲突，不引入全局注册机制。
- 无引用与跨组共享使用明确的固定分组 kind/key，不再用英文句子作 sentinel。
- 分组计算以 key 去重。两个不同 ID 即使同名也不合并，同一凭据被不同组引用时归入共享组。
- 分组结果保存事实和固定标题的显示身份，在 React 渲染时用当前 locale 解析；动态组标题直接显示 source。去掉分组 helper 对隐式全局翻译函数的依赖。
- React key 使用稳定分组身份；排序可按显示标题，未引用组仍放最后，标题调整不造成凭据编辑器因 key 改变而重建。

此处不新增 group/surface 翻译表。它们与前端固定导航分组职责不同；当前需求由稳定分组身份和原始标题即可满足。

### 4.3 Cycle 任务标识与配置同步

| 位置 | 修改 |
| --- | --- |
| `llm/protocol/requests.py` | `FRAME_STAGE1/2` 改为 `FRAME_PHASE1/2`；值改为 `frame-phase1/2` |
| `kernel/loop/config.py` | Phase1/2 默认任务引用同步更新；可直接复用已有 TaskProfile 常量，依赖方向仍为 kernel → llm |
| development / standard 模板 | `configs/loop.toml` 引用与 `configs/llm/tasks.toml` 表名同步更新 |
| Python 夹具与 CLI fake provider | 任务声明与引用同步更新 |
| `visualization/test/e2e/backend_server.py` | 更新真实消费者 `TaskProfile.FRAME_STAGE1/2`，确保脚本模型仍能区分两次调用 |
| 前端 preset/trace 测试与当前配置说明 | 更新内置任务引用；任意自定义示例可改成测试自有的 custom-chain 名称 |

保留 `TaskProfile`：它有实际请求与测试 harness 消费者。任务 profile 仍允许自定义字符串，`LLM_ACTION` 不变；不因改名收窄模型路由能力。

`PhaseBindingsPage` 删除 `ownerDefault` 参数和两条硬编码任务名。空选项使用稳定 ID `settings.phaseBindings.useDefault`，显示“使用默认任务链” / “Use the default task chain”。选择空值仍调用 `api.clear()`，暂存删除当前来源的字段覆盖，保存并生效后使用下层来源或代码默认值；它不同于 `withdraw()` 撤销未保存草稿。显式配置值与任务候选继续来自现有快照、catalog 和草稿投影，前端不猜测协议未提供的默认 ID，不新增 Endpoint 字段。

**已有数据的影响：**模板更新不会自动改写已初始化项目。旧名称仍可作为普通自定义任务 ID 被显式引用；本次不提供旧内置名称的别名。若已有项目希望采用新的内置默认名，需要同步更新 tasks、loop 绑定以及引用这些任务的运行方案。特别是依赖代码默认值、却只定义旧 tasks 表的项目，不能只更新源码而保持该配置不动。实施不触碰个人运行数据，不调用 reset 代替配置核对，不加入迁移脚本；现有 init/reset 行为保持原意。

### 4.4 Action 摘要、Trace 与协议夹具

将 `ActionGlimpseData.stage` 改为 `kind`，一次更新 `presentation.ts`、`activityBuffer`、`ActivityGlimpse`、`ProcessPanel`、开发示例与测试。`executionState` 继续表示真实执行状态；既有外层 `action_plan/action_result` 消息种类不借此重构。动画与 `data-activity-gist` 的 plan/result 行为保持原意，不引入新的业务状态机。

`ActionDetailPanel` 从 `trace.result.stage` 读取结果环节，删除对 `failure.stage` 的读取。将“处理环节 / Processing step”作为结果元信息显示；Cycle 位置仍由 scope/phase 描述，两者不互相推导。

已知结果环节用现有 `i18n/protocol` 体系添加 `action.stage.<value>` 摘要；未知值回显原值。可读标签与原始导出分开：raw JSON、导出证据仍保留 `stage` 的机器值。failure 的 `reason`、`feedback` 与其他动态诊断继续保留，不增加插件失败原因的全量翻译表。

清理代表性夹具：

- 成功执行结果使用 `stage: "execute"`，不再伪造 `execution`。
- hook 拒绝等失败使用对应真实 stage；failure 包含 `reason/scope/disposition/feedback`，有必要时附 constraint，不嵌套 stage。
- 覆盖 `trace/facts.test.ts`、`trace/panels.test.tsx`、`AppShell` 相关夹具，并检索其余当前 test/dev 数据中的同类残留。
- 复用现有小型测试构造器；仅当多个消费者确有共享需求时提取局部夹具，不新建一套前端业务 schema 或跨语言生成框架。

后端 `ActionResultStage`、Action failure envelope、Observation 和 Endpoint 协议不因本次显示修复而改形。前端的未知值保留能力也不收紧为只接受当前枚举值。

### 4.5 当前文档与历史记录

同步以下当前说明：

- `AGENTS.md` 中三处将 Cycle Phase2 写成 Stage2 的内容。
- `docs/design/runtime.md` 对 Turn 的“3-stage 推理”表述：Turn 可包含多次 Cycle，每个 Cycle 包含三个 Phase；Phase3 包含执行，不笼统称为模型推理。
- `docs/design/action-model-retrieval.md`、`docs/design/agent_home.md` 的 Cycle 同义残留；核对 loop/action/llm 当前设计说明的关联段落。
- `visualization/README.md`、`docs/design/config-coverage.md` 的 phase stepper 和默认任务名；`ActivityStep` 等当前代码注释。
- `visualization/docs/design/i18n.md`：精确说明字段/document/collection/choice 的映射与动态 group/surface 的原文边界，以及凭据分组身份。

设计文档只说明稳定职责和协作语义，不塞入本次迁移文件清单。测试命令、实际结果和迁移风险留在本执行计划。

历史归档中的 Stage1/2、旧配置例子保留，不全仓重写历史。此前收尾计划及 `i18n.md` 的浏览器记录把图页面写为 Session graph；前轮复核对应的是 MemoryGraph。本计划登记这项勘误：该记录不能作为 Session graph 或真实 Tauri 桌面验收的证据。实施时纠正当前 `i18n.md`，旧计划正文保持历史记录；本次新增验收单独按实际页面、后端类型和运行方式记载。

## 5. 分步执行清单

### P1：统一 Cycle 术语与内置任务绑定

- [x] 更新 TaskProfile、CycleSettings、两套正式模板、测试自有配置与 E2E harness；声明与引用同时修改。
- [x] 改造 PhaseBindings 默认选项，删除前端重复的任务名默认值。
- [x] 更新 SearchPolicies 两个语义 ID 和 Phase 文案；清理当前代码注释中的同义残留。
- [x] 聚焦验证 Loop 配置、LLM 路由、模板装配、CLI fake provider 与任务绑定控件。
- [x] 同步受影响的当前术语、配置文档；检查自定义任务 ID 仍按普通引用处理。

### P2：完成双语与 catalog 显示边界

- [x] 补齐中文遗漏，校正英文预算、超时和 entity 字面文本；对照实际页面审阅易读性。
- [x] 将 catalog choice 文案移入语言资源，adapter 不承担内容管理。
- [x] 凭据按稳定身份分组，固定分类在渲染时翻译，后端标题继续作为动态内容。
- [x] 验证切换语言、标题变化时保留草稿与组件状态；更新 catalog 与 i18n 当前设计说明。

### P3：清理展示分类与 Trace 协议残留

- [x] `ActionGlimpseData.stage` 改为 `kind`，更新所有生产者与消费者。
- [x] Action 详情展示顶层 result stage，补充少量协议摘要；原始数据和导出保留原值。
- [x] 修正成功与失败夹具，覆盖正常执行和一条有代表性的局部失败路径。
- [x] 检查 Phase、Action stage、glimpse kind 在同一条过程展示中各有明确含义。

### P4：收口测试与浏览器验证入口

- [x] 受影响的 Settings/Trace/Chat/AppShell 测试移除旧文案字面断言与失真协议值。
- [x] 更新 `chat-flow.pw.ts`、`presentation.pw.ts` 中受本次语义和现有双语入口影响的选择器；固定 UI 标签从纯字典入口按明确 locale 获取，不通过“中文或英文都行”掩盖语言状态。
- [x] 复用现有后端 harness 验证任务路由与共享语言保存；仅模型输出脚本化，不要求真实 provider。
- [x] 记录代表性双语浏览器检查，区分 FakeEndpoint、真实后端 harness、浏览器和 Tauri。

### P5：规约核对与交付

- [x] 按下节运行最终门禁，并记录真实命令、结果与限制。
- [x] 复核依赖方向、单一 owner、UiText 边界、动态内容、局部 stage 保留范围及无兼容别名。
- [x] 复核当前文档、代码、模板、测试一致；剩余旧术语均能解释为历史或合法局部语义。
- [x] 逐项填写验收表；所有必要项完成后，将本计划标记 done，文件名加入 `-done-` 并移至 `docs/analysis/done/`。

P1 的任务绑定修改须作为完整单元验证；P2 与 P3 职责独立，但共享字典修改应集中核对。P4 在显示代码稳定后收口，P5 最后执行。不得用“测试数量未下降”或旧计划已归档替代验收。

## 6. 测试设计与验证方式

### 6.1 最小行为覆盖

| 契约 | 覆盖方式 |
| --- | --- |
| 两种语言资源有效 | 复用现有 ID/插值/重复 ID 测试，不锁定翻译句子 |
| catalog 按身份翻译 | 测试自有字段修改 source 后映射仍有效；未知字段/choice 原样可用；schema/value 不变 |
| 凭据分组不依赖标题 | 不同组同名仍区分；同一凭据跨组归共享；标题变化与 locale 切换保留编辑状态 |
| Phase 默认与任务声明一致 | 使用现有配置/装配测试验证引用可解析；正式模板只校验结构与引用，不锁定模型名单与默认策略值 |
| 默认选项只撤销覆盖 | 控件候选来自自有 catalog/草稿，清空调用原 clear 行为；自定义任务可选 |
| 展示分类与执行事实独立 | plan/result 摘要切换正常，执行状态和 Action 标识不变 |
| Trace 消费真实结果 | 一个成功 execute 和一个局部失败结果即可，失败结构与后端一致；未知显示值保留原文 |
| mounted 双语切换 | 复用并扩展 Settings Context、凭据或 Action 详情代表用例；保持草稿、payload、选中项，不重复读取 |
| 前后端协作 | 现有真实后端 E2E 的对话任务路由、Presentation 保存和新连接读取 |

机器协议精确值可以断言，如 `phase2`、`execute`、locale、字段路径和请求 payload。按钮文字通过当前字典定位，同时断言实际操作结果；不要把“调用 t 后等于 t”作为主要业务验证。测试自有的模型名、标题和正文可以使用明确字面量，但不锁定正式 assets/prompts 的可编辑内容。

不新增全仓文本禁用扫描、所有页面乘所有语言的测试矩阵，或针对假设异常增加层层恢复测试。现有 owner 测试完整覆盖的契约不在跨模块测试中重复枚举。

### 6.2 命令与顺序

实施时先确认已安装仓库 uv dev 环境与前端依赖；命令遵守项目标准入口，不提交个人解释器路径。工具不在 PATH 时可定位现有安装，本机路径只用于本次调用。

后端先运行与本次修改直接相关的测试；涉及初始化、CLI 或集成时使用 Full 筛选，不能把零选中作为通过。例如在仓库根目录运行：

```powershell
uv run --locked --extra dev python scripts/test.py --suite full tests/kernel/loop/test_loop_config.py tests/llm tests/gateway/project tests/gateway/test_cli_fake_provider.py
uv run --locked --extra dev python scripts/test.py
```

前端先运行受影响路径的 Vitest；最终在 `visualization/` 运行：

```powershell
pnpm test
pnpm build
```

`build` 已包含 TypeScript 检查。PowerShell 执行策略阻止 pnpm 脚本时可使用 `pnpm.cmd`。最终后端门禁在仓库根目录运行：

```powershell
uv run --locked --extra dev python scripts/test.py --suite full
uv run --locked --extra dev ty check
```

对真实后端 harness 的代表性浏览器协作检查，在 `visualization/` 使用既有配置：

```powershell
pnpm exec playwright test --config test/e2e/backend.config.ts
```

该命令需要本机 Playwright 浏览器运行条件。若入口或浏览器缺失，先修正当前可复用入口或使用现有浏览器完成对应检查，并记录替代证据；无法验证的必要项保持未完成，不用 Vitest、cargo check 或旧记录冒充端到端通过。

检查中文和英文的 Context 设置、Phase 绑定、凭据编辑、Action 详情，以及窄屏下的长说明。确认切换后输入不丢、已展开详情仍在、操作没有重复提交。具体检查页面逐项记录，不笼统写“全部 UI 已验收”。

本计划不预期修改 Rust、Tauri bridge 或依赖，因此不把重复 cargo 检查作为 UI 修复证据；若实施实际触及这些范围，再补相应检查。

所有新工件放在项目忽略目录 `.local-test/`，遵循现有隔离与清理流程。无需真实模型凭据、个人运行数据或公网 provider。

## 7. 完成验收与记录

| 编号 | 验收要求 | 核对结果与证据 |
| --- | --- | --- |
| A1 | 固定 UI 文案双语可读，预算/超时说明与当前执行语义一致 | 完成。Settings 两份字典及 Inspector 固定标签已修正；对照 Cycle 预算等待和 Action 调用时限；双语浏览器检查通过。 |
| A2 | catalog 文案与 adapter 职责分开，未知动态内容可用且原值不变 | 完成。choiceText 移入 catalog/zh-CN.ts；index.test.ts 验证改写 source 仍按身份匹配，未知字段/choice 回显，原对象不变。 |
| A3 | 凭据分组以稳定身份计算，标题与 locale 变化不丢编辑状态 | 完成。collectionDrafts 按 group/surface ID 分组；同名不同 ID、共享和无引用由 owner 测试覆盖；pages.test.tsx 验证输入节点、未提交值和最终 dotenv 操作保留。 |
| A4 | Cycle 统一 Phase，内置任务名声明/引用同步，无旧内置别名 | 完成。TaskProfile、CycleSettings、两套模板、夹具与 harness 同步；Full 验证配置装配、CLI、wheel；当前代码与设计文档检索无 Cycle Stage1/2/3 残留。 |
| A5 | Phase 绑定界面不重复写死默认任务名，自定义任务引用正常 | 完成。删除 ownerDefault；BehaviorPages 测试验证空选项暂存 delete；任务候选来自现有投影，Python 保留 str 自定义路由。 |
| A6 | 合法局部 stage 保留；glimpse kind 与 executionState 职责明确 | 完成。Chat/Trace 生产者与消费者统一 kind；Action/Control/retrieval/释放顺序及草稿 staging 保留原语义。 |
| A7 | Action 详情消费真实 result/failure 结构，原始诊断与导出不被翻译覆盖 | 完成。详情读取 result.stage；代表夹具使用 execute/hook/timeout 和规范 failure；mounted 测试保留诊断和展开参数，浏览器消费真实 workspace.read 结果。 |
| A8 | 测试保护行为与协议，受影响路径无旧文案快照、失真夹具和无效选择器 | 完成。相关 Settings/Chat/Trace/Inspector/E2E 固定标签由字典定位；保留测试自有正文，未增加正式模型清单或文案快照。 |
| A9 | 前后端最终门禁、代表性浏览器协作和双语检查完成并留证 | 完成。Full 1516、Fast 1374、Vitest 891 全部通过；ty/build 通过；真实后端 Chromium E2E 3 条通过；详见下方记录。 |
| A10 | AGENTS 与当前设计文档一致；历史勘误与配置更新影响已明确记录 | 完成。同步 AGENTS、runtime/loop/Home/retrieval 与前端当前文档；§4.3 记录配置影响，§4.5 记录旧浏览器页面勘误。 |

实施记录按每项填写：修改位置、验证方式、结果、实际限制。失败先区分实现问题、失真测试或环境问题，不能靠跳过测试、放松协议或吞掉异常换取通过。

旧计划的验证仅作历史基线。以下为本轮实施后实际执行的结果，没有复用旧结果作为完成证据。

### 7.1 实际实施与补充修复

- P1 完成内置任务命名及声明/引用同步；前端默认选项只表达恢复默认，未新增 Endpoint 字段或兼容别名。
- P2 完成 Settings 文案、choice 资源归属和凭据稳定分组。分组测试发现专用模型的 `object_list` 凭据引用原先未被收集；现由同一个草稿投影按 catalog 声明路径读取对象和 ID 列表，没有另建配置状态或反向写业务数据。
- P3 完成 glimpse kind、result stage 与真实失败夹具对齐。保留协议原值、动态诊断及未知值回显。
- P4 补齐 Action 详情抽屉的放大、复制标签，更新其既有交互测试。窄屏检查发现 SliderField 的固定宽度子项挤出卡片，改为在可用宽度内换行，保持单一输入和原提交行为。
- 浏览器 harness 固定读取仓库 `.venv`，删除 conda/个人解释器覆盖分支；Node 通过关闭 stdin 请求 Python 正常退出，随后等待进程完成。测试专用 WebSocket 心跳设为 1 秒，让断开的观察流及时结束。最终后端日志只有 ready 记录，无关闭超时诊断。
- 浏览器产物移至仓库 `.local-test/playwright-output-backend/`，避开 Vite 监听目录；截图禁用过渡动画，避免把视口切换过程误记为最终布局。前端 README 补充可复用的真实后端浏览器命令。

这些补充均来自本轮正常路径验证，沿用现有 owner、控件和测试入口。没有引入恢复状态机、通用配置遍历平台或新的 i18n 框架。

### 7.2 本轮验证记录

| 验证 | 实际结果 | 记录 |
| --- | --- | --- |
| Full 筛选 Loop 配置、LLM、project 初始化及 CLI fake provider | 282 passed，19.56s | `.local-test/reports/42576626364e4aab9f93125acc024479/` |
| 默认 Fast | 1374 passed，145 deselected，36.74s | `.local-test/reports/e7bb5bfc41294507b67af969147ee688/` |
| 最终 Python Full | 1516 passed，3 deselected，202.18s | `.local-test/reports/28f991c9dbe44c1ebdbe36c15f558960/`；按 suite 排除 external |
| `uv run --locked --extra dev ty check` | All checks passed | 最后修改后再次通过 |
| `pnpm.cmd test` | 101 文件、891 测试全部通过，16.66s | 包含 catalog 身份、分组、草稿保持、Trace/Inspector 和既有语言切换测试 |
| 最终 ActionGlimpse 夹具核对 | 14 passed，2.45s | 补齐测试自有 failure 摘要后聚焦复验；glimpse 的内部 failure 状态仍由 activityBuffer 从协议 failed 映射 |
| `pnpm.cmd build` | TypeScript 与 Vite 构建通过 | 仅有现有大 chunk 提示 |
| 真实后端 Chromium E2E | 3 passed，38.7s | `.local-test/e2e-backend-6TkMwq/backend.log`；使用下方命令 |
| `git diff --check` 与当前术语复核 | 通过 | 无旧内置 task 枚举/别名、Cycle Stage1/2/3、failure.stage、失真 execution stage；合法局部 stage 保留 |

真实后端浏览器的最终命令（在 `visualization/`）为：

```powershell
node node_modules/playwright/cli.js test --config test/e2e/backend.config.ts
```

本机 `pnpm exec playwright` 未能解析已安装的命令，直接调用同一已安装 Playwright CLI 完成验证，未下载或替换依赖。Windows 沙箱限制了 Playwright 对自己启动的 Vite 服务进行进程清理，本轮在获准的本地非沙箱运行中完成 E2E；这一环境处理没有写入仓库脚本。uv 在本机不在 PATH，通过已安装 uv 的绝对路径调用上述标准入口，缓存留在 `.local-test/uv-cache/`，未提交个人路径。

中途失败包括旧 UI 选择器、窄屏导航定位、未同步的 Copied 标签断言，以及新增详情测试误选 Action 名称；均根据真实界面修正后复验，没有跳过测试或放宽业务结果。最初长心跳使测试关闭等待超时，短测试心跳与正常退出流程消除了该诊断。Vitest 仍有既有 jsdom scrollTo 提示，不影响用例结果。

### 7.3 浏览器观察范围

本轮使用浏览器 Chromium、真实 Agent/Endpoint/owner 和脚本化 LLM 输出，无公网 provider、个人凭据或个人运行数据。

| 页面/路径 | 本轮检查 |
| --- | --- |
| User Turn | 两个 Phase 任务可路由；回答、ask/reply、原问题与补充回复、刷新后的 Session 恢复正常 |
| Reflection | 共用 ask/reply；完成和刷新保留状态，不新增 User Session 记录 |
| Interface | 主题、字体、字号、locale 保存至项目 TOML；新客户端与刷新读取同一 locale；没有 config apply/reload，generation 不变；鉴权资产预览与下载正常 |
| Context 设置 | 中英文当前占用/无活动轮次/背景说明；420×900 窄屏长说明与数值控件可读 |
| Phase 绑定 | 中英文说明、真实 task 候选、默认选项；420×900 布局 |
| 凭据 | 中英文固定标签、原始 backend 分组标题和引用；420×900 布局；编辑节点/未提交值保持另由 mounted 测试验证 |
| Action 详情 | 中英文真实 workspace.read 的位置、处理环节、参数与正文；420×900 布局；同一已展开详情切换时不重读、不丢参数由 mounted 测试验证 |

本轮截图保存在 `.local-test/playwright-output-backend/` 下对应 spec 目录，包括 `context-{locale}-narrow.png`、`phase-bindings-{locale}-narrow.png`、`credentials-{locale}-narrow.png`、`action-detail-{locale}-narrow.png` 和 `shared-interface-and-assets.png`。截图只作人工检查证据，不建立像素快照门禁。

未声称遍历全部界面、验证真实模型效果或完成 Tauri 桌面验收；本轮未修改 Rust、Tauri bridge 或依赖，未重复运行 cargo。旧 MemoryGraph/Session graph 勘误仍以 §4.5 为准。

### 7.4 AGENTS.md 对照

- **唯一 owner 与依赖方向：** kernel 复用 llm 的 TaskProfile；后端业务 owner、Agent/Turn/Cycle 调度和 Endpoint 协议职责保持清楚。Presentation 独立保存语言，不触发运行世代激活。
- **事实与显示分层：** UiText 保存固定消息身份或动态原文；catalog 仅投影已知身份的标签，凭据分组使用正式 ID；未知字段和值不会因翻译缺失而消失。
- **类型与语义：** 继续使用既有 StrEnum、CyclePhase 与 ActionResultStage；kind 只表示前端展示种类；没有旧名称 alias、平行状态机或新的失败控制层。
- **正常主线优先：** 修复已证实的引用读取、草稿稳定、窄屏换行与测试关闭问题；不扩展假设故障的恢复链。测试仍围绕协议、owner 行为和代表协作路径。
- **当前文档与历史记录：** 当前 AGENTS/design/README 与实现同步；配置变更成组更新要求已记录，未操作个人数据；旧归档不批量重写。
- **交付门禁：** 先聚焦、Fast，再 Full/ty；前端单测/build 及真实后端浏览器检查通过。P1–P5 与 A1–A10 已完成，满足归档条件。

## 8. 合理性、影响与准备状态

本方案符合当前设计，且无需新增业务能力：

1. **所有权清楚。** PresentationService 继续拥有共享偏好，Infra 与业务模块拥有配置事实，前端只拥有显示资源和草稿。分组身份来自既有 catalog，不生成平行业务事实。
2. **执行语义稳定。** Phase 沿用现有运行类型；局部 stage 保留。内置任务标识改名只调整声明与路由引用，不修改 Turn、Cycle、Action、Trap 或 Job 的运行规则。
3. **前后端耦合有限。** 翻译依赖稳定字段身份，不匹配后端英文句子；未知内容原样显示。Phase 默认选项删除重复默认值，标题不再决定凭据分组身份。
4. **实现范围可控。** 主要改动在前端字典、Settings、Chat/Trace 投影与测试；后端集中于两处任务默认定义、正式模板与其消费者。没有依赖升级、持久数据迁移或第二套 i18n 框架。
5. **验证与真实风险对应。** 关注任务链引用、真实结果结构、已挂载界面切换和草稿保持；沿用 Fast/Full 与现有前端、浏览器入口，避免为文案清理建立沉重测试设施。

主要影响是旧项目采用新默认任务名时需要成组更新引用；具体边界已在 §4.3 明确。另一个检查重点是英文本身可能改变含义，必须依据当前 owner 的行为审阅，不能只检查字典是否齐全。

本计划不包含 uv/conda 环境再迁移、主机更新脚本、运行数据调整、模型提示词翻译或无关的 Session/Memory 功能重构。已确认的个人使用、共享界面偏好和正常主线优先原则均保持一致。

实施后复核：方案已按 P1–P5 完成，并由 A1–A10 和 §7 的实际证据核对。没有遗留待决策项或必要验证缺口，状态为 **done**。已有项目采用新默认任务名时仍需同步更新配置引用，这属于 §4.3 已确认的部署影响，不自动修改个人数据。
