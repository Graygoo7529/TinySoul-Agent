# Action 模型绑定编辑一致性执行计划

日期：2026-11-15
状态：done（2026-11-16 完成收尾校正，门禁全绿，逐项核对通过）
核对基线：`369a0f09`；编写计划前工作树干净。

依据：[AGENTS.md](../../../AGENTS.md)、[Action 设计](../../design/action.md#模型用途)、[Infra 配置设计](../../design/infra.md#统一配置链路)、[Settings 设计](../../../visualization/docs/design/settings.md)、[配置覆盖清单](../../../visualization/docs/design/config-coverage.md#32-action-模型用途--actionmodelsbindings)。

## 1. 目标与改动预览

使 Action 模型绑定的编辑、草稿、提交与运行展示遵循同一套语义：实现决定目标和选项，草稿表达用户当前选择，运行投影解释已经生效的值。

| 使用场景 | 当前问题 | 实施后的效果 |
| --- | --- | --- |
| 修改 `llm_task` 的模型链 | 隐藏的相关性阈值随表单一起提交，被后端拒绝 | 只提交模型链和适用的生成选项 |
| 清空输出上限，再修改模型链 | 逐字段回退可能取回运行中的旧上限 | 清空持续有效，使用所选任务链自身的限制 |
| 切换模型实现，再修改目标 | 旧实现的选项可能从运行投影重新进入草稿 | 草稿只保留当前实现的字段 |
| 使用默认相关性阈值 | 前端自动填入数值，混淆未设置与显式配置 | 留空使用后端默认；填写时保存显式阈值 |
| 查看尚未应用的修改 | 原始配置与运行时解析值直接比较，可能把默认值展开误判为修改 | 配置快照用于比较，运行投影用于展示实际生效值 |

示意链路：

```text
已保存配置 + 本地草稿
          │ 按 consumer 取得完整绑定
          ▼
对应实现的编辑值 ──→ 对应实现的 target/options
                              │
                              ▼
                     现有 ConfigDraft / apply
                              │
                              ▼
                     owner 校验 → 保存并激活

当前运行配置与 Action 投影 ──→ 差异提示与运行值展示
```

本次实现集中在前端 Settings 行为模块，后端继续提供已有绑定语义和配置事务。`core.answer` 是发现问题的入口，修复覆盖所有使用该编辑器的模型用途。

## 2. 已核实的现状与问题

### 2.1 现有职责可以支撑此次修复

| 层次 | 现有职责与实现 |
| --- | --- |
| Action 声明 | `agent/composition/actions.py` 声明 `core.answer.generate` 等模型用途；`ModelUseDescriptor` 给出用途与允许实现 |
| Action 配置 | `kernel/action/config.py` 按实现解释 `target/options`；`ModelUseRegistry` 校验 consumer、实现和目标引用，提供前端投影 |
| 模型调用 | `ActionTaskFactory.create()` 将绑定中的任务链传入 `TaskCall`；LLM 负责链内模型与供应商选择 |
| 配置设施 | Infra 构造并校验候选配置，再保存或发布；Agent 组合根调用所属 owner 完成语义校验 |
| Endpoint | 提供 saved/active 配置、Action 能力与运行绑定投影，以及统一 apply 协议 |
| 前端 | ConfigDraft 维护草稿；`bindingsModel.ts` 按 consumer 修改整数组原子值；`ActionsPage.tsx` 提供绑定编辑控件 |

后端已支持生成用途引用独立模型链。`tests/kernel/action/test_config_settings.py` 已覆盖声明用途绑定自定义任务链及目标引用校验；无需为回答模型增加新的路由机制。

### 2.2 需要修正的编辑语义

1. `ActionsPage.tsx` 的 `commitPatch()` 将所有实现的字段合在一起，并始终携带缺省为 `2` 的 `relevanceThreshold`。控制项隐藏并没有改变提交内容。
2. `bindingsModel.ts` 的 `encodeBinding()` 对 `target` 按实现编码，对 `options` 却只检查是否有值。这使表单中的无关选项穿过了提交边界。
3. 编辑值使用 `entry?.value ?? running?.value` 逐字段回退，无法区分“没有绑定”与“绑定明确没有设置这个可选值”。
4. 运行差异比较直接混用保存形态与解析后的运行形态；例如未声明的 decision 阈值会在后端展开为默认值，不能据此认定配置尚未应用。

这些问题共同指向绑定编辑模型的两个边界：不同实现之间的字段边界，以及编辑配置与运行投影之间的边界。

### 2.3 已有验证及其限度

此前诊断已用实际前端编码函数生成候选，再交给真实 `parse_action_settings()`：LLM 绑定携带相关性阈值时被拒绝；移除无关选项后结构解析通过。实际测试项目的原文件未包含该错误字段，拒绝发生在候选配置阶段。

相关前端测试两个文件共 25 项通过，但编码测试输入已经是合法字段组合，页面测试未覆盖直接修改 LLM 任务链。这说明需要补充主线交互覆盖，而不是增加更多孤立的合法对象样例。以上验证不等于检查了用户项目中新增模型链的全部配置。

## 3. 实施设计

### 3.1 按实现表达编辑值

在现有 `bindingsModel.ts` 中，将 `BindingDraftValue` 改为以 `implementation` 区分的联合类型，明确三种编辑形态：

| implementation | 目标字段 | 可选配置 |
| --- | --- | --- |
| `llm_task` | `taskProfile` | `maxOutputTokens` |
| `decision` | `use` | `relevanceThreshold` |
| `embedding_similarity` | 使用 owner 的 embedding 依赖，无绑定级目标字段 | 无上述选项 |

编辑过程中允许目标暂未选择，便于用户先切换实现再选择目标；提交完整配置时仍由现有 owner 校验引用。`BindingEntryView` 复用相同的实现分支表达，并附带 consumer 与草稿状态。动态 JSON 在这一现有边界解码，页面不再通过宽泛断言把任意字符串当作合法编辑类型。

`encodeBinding()` 按实现分支一次构造 target 与 options，空对象可省略。页面的目标和数字修改针对已经收窄的分支构造下一完整值，移除将所有字段展开的通用 `Partial<BindingDraftValue>` patch。

原始 Endpoint 投影继续由 `actionsView.ts` 负责只读解码；只有实际消费需要时调整其与编辑模型的转换，不建立第二套 schema 或通用表单框架。

### 3.2 草稿与运行值分开

编辑器以 `bindingEntry()` 返回的 saved + draft 完整条目为依据：

- 条目存在时，其目标、选项及未设置状态完整决定控件值。
- 条目不存在时，呈现待配置状态；可将后端允许的首个实现作为表单起点，目标留空。打开页面本身不创建草稿。
- 运行投影仅用于显示当前生效绑定，不参与补齐编辑值。

同一实现内修改目标时保留适用选项。切换到不同实现时建立新分支，目标重新选择，可选值未设置；不缓存各实现的历史表单来回填。撤回仍调用已有 `withdrawBinding()`，恢复该 consumer 的保存基线。

未设置在编辑模型中明确表示为可选值缺失，在 JSON 中省略字段。数字零是有效 decision 阈值，不能被空值判断丢弃。

### 3.3 默认值由 owner 解释

输出上限与相关性阈值都采用可清空的数字输入：

- 输出上限留空，沿用任务链限制。
- 相关性阈值留空，沿用 Action owner 的默认阈值；已显式填写的值继续显示并保存。

复用页面现有 `OptionalNumberRow`，按两个真实消费者补充可选最大值、单位与可访问标签：输出上限显示 tokens，阈值无单位；范围使用当前 `modelUse.options` 投影。清空移除该字段，后续编辑不会重新填入运行值或前端默认数值。

中英文补充简短说明“留空使用默认阈值”及对应英文，使用稳定 message ID。默认阈值不进入翻译字典，也不通过新增 Endpoint 字段复制到表单。输入范围同时使用 catalog 的最小值和最大值，避免明显超限值进入草稿。

### 3.4 差异提示比较同类事实

草稿状态继续与 saved 绑定比较；行为页的待应用提示表示本地草稿相对保存快照的变化。实际运行绑定仍从 `modelUse.binding` 只读显示，Settings 总览继续负责展示 saved 与 active 的整体待激活状态。

这样，后端展开默认值不会造成虚假的待应用提示，明确清除配置也不会被运行值遮蔽。用户显式设置了与默认相同的数字，仍是一次合理的配置修改。复用已有 saved/active 快照，不增加状态存储或前端默认值解析器。

### 3.5 保持配置操作的既有身份与原子性

绑定通过稳定 consumer 定位，编辑单项后仍暂存整个 `action.models.bindings` 数组，保留其他条目和来源。情景切换只更换能力视图，同一 consumer 共享草稿。

任务链候选继续使用 `projectCollection(state, "llm.tasks")`，因此已保存链和本地新建链均可选择；新增链和绑定可以通过同一批 apply 操作提交。模型名、提供方、链 ID 来自项目配置，不加入任何特定名称规则。

后端的选项校验、候选保存与 generation 激活保持原职责。本次不需要 Endpoint 协议变更，也不需要迁移已有有效配置。

## 4. 文件与改动范围

以下路径除注明外均相对 `visualization/`。

| 文件 | 预计改动 |
| --- | --- |
| `src/features/settings/behavior/bindingsModel.ts` | 实现区分的编辑类型、绑定解码与编码、供编辑和差异比较复用的读取逻辑 |
| `src/features/settings/behavior/ActionsPage.tsx` | 完整条目驱动控件，分支内提交，清空与切换语义，运行提示，复用数字输入 |
| `src/features/settings/behavior/actionsView.ts` | 核对只读投影边界，仅在实际转换需要时调整类型或解码 |
| `src/features/settings/behavior/models.test.ts` | 按当前语义更新模型测试，覆盖未设置值与编码形态，保留已有原子编辑测试 |
| `src/features/settings/behavior/BehaviorPages.test.tsx` | 补充真实控件操作与连续编辑回归，使用测试自有配置 |
| `src/i18n/messages/zh-CN/settings.ts`、`en-US/settings.ts` | 阈值默认行为的双语说明 |
| `docs/design/settings.md`、`docs/design/config-coverage.md` | 同步绑定编辑来源、实现字段与默认值语义；相关段落以动态声明代替固定 consumer 数量 |
| 仓库 `docs/analysis/` 本计划 | 记录进展、验证证据和完成核对，完成后按规约归档 |

业务代码实施以 frontend 范围为主，后端模块作为协议与回归验证依据。若实施时发现既有接口无法表达上述语义，先明确缺口与影响，再调整计划。

## 5. 执行步骤

### P1：统一绑定编辑模型

- [x] 引入实现区分的编辑类型，将现有入口与消费者迁移到该类型。
- [x] 按实现构造 target/options，移除跨实现的字段合并。
- [x] 保留按 consumer 编辑、撤回与整数组提交的既有行为。

### P2：修正页面状态与交互

- [x] 从完整 saved + draft 条目读取编辑值，移除逐字段运行值回填。
- [x] 完成同实现编辑、不同实现切换、清空可选值和未绑定入口。
- [x] 复用可清空数字控件，相关性阈值默认值交给 owner，补充双语说明。
- [x] 以配置快照比较待应用差异，运行投影独立显示。

### P3：验证主线协作

- [x] 补充第 6 节的最小交互覆盖，整理受影响旧断言。
- [x] 检查当前前端提交与真实后端 parser/registry 的一致性，记录一次代表性链路验证。
- [x] 完成前端测试与构建、仓库规定的 Full 与类型门禁，记录命令和结果。

### P4：文档与完成核对

- [x] 同步两份前端设计文档，说明已落地职责，不复制本次故障经过。
- [x] 对照 AGENTS.md 检查类型边界、配置 owner、状态来源、测试与文案。
- [x] 逐项核对第 7 节，在本计划中补充实现位置、验证结果与剩余事项。
- [x] 全部完成后标记 done，文件名加入 `-done-` 并移入 `docs/analysis/done/`。

## 6. 验证安排

### 6.1 少量、有区分度的主线用例

| 场景 | 主要观察点 |
| --- | --- |
| 生成用途选择另一条任务链 | 操作真实下拉框；目标更新，生成选项保持，提交无 decision 选项，其他 consumer 保持 |
| 清空已有输出上限，再修改链 | 控件重渲染后仍为空；提交仍省略上限，运行中的旧值只作展示 |
| 带输出上限的 LLM 绑定切换为 decision，再选择 use | 不再携带 LLM 字段；阈值未设置时省略，显式设置有效值时保存，覆盖零值 |
| decision 与 similarity 分支 | 复用已有切换测试，确认离开 decision 后不残留其 target/options |
| 保存值缺省、运行值已展开默认 | 打开页面不生成草稿，不产生虚假待应用提示；草稿清空可选值时保留用户意图 |
| 新建任务链草稿并选择它 | 候选来自草稿集合，提交中同时保留链定义和绑定；不自动选用预设链 |

已有 consumer 原子替换、撤回、情景切换测试继续保护各自契约，不在每个新增用例重复整套断言。测试定位使用稳定身份或当前翻译资源，断言配置结构与状态变化，不固定生产模型清单、路径、中文句子或用户项目数据。

### 6.2 前后端契约核对

复用后端已有 `tests/kernel/action/test_config_settings.py` 和 `test_model_tasks.py` 验证绑定解释与调用传递。使用测试自有配置，将当前前端编码得到的一个完整生成绑定交给真实 `parse_action_settings()` 与 `ModelUseRegistry.validate_targets()`，核对读取到所选链；decision 缺省阈值由后端解析，前端不补值。

该核对可作为一次实现验收证据，不为本次修复搭建 Node/Python 相互启动的常驻测试框架。前端交互测试负责证明控件实际生成了正确候选，后端 owner 测试负责解释协议；FakeEndpoint 的成功响应不单独作为后端接受配置的证据。

在隔离测试配置中完成检查，不修改个人使用项目，也不要求真实 provider 调用。

### 6.3 验证命令

前端目录：

```powershell
pnpm test src/features/settings/behavior/models.test.ts src/features/settings/behavior/BehaviorPages.test.tsx
pnpm test
pnpm build
```

仓库根目录，实施后的日常反馈与最终门禁遵循 AGENTS.md：

```powershell
uv run --locked --extra dev python scripts/test.py tests/kernel/action/test_config_settings.py tests/kernel/action/test_model_tasks.py
uv run --locked --extra dev python scripts/test.py
uv run --locked --extra dev python scripts/test.py --suite full
uv run --locked --extra dev ty check
```

定位到已安装但不在 PATH 的工具时，可在本机用实际可执行文件路径运行，不将个人路径写入共享配置。验证工件沿用项目忽略目录；记录真实执行结果，未执行项不记为通过。本轮仅编写计划，不将上述实施验收标记为已完成。

## 7. 完成标准

- [x] A1：任意已声明生成用途可选择有效任务链，提交的实现、目标与选项相互匹配。
- [x] A2：清空可选值后继续编辑，旧运行值不重新进入草稿。
- [x] A3：不同实现切换后继续编辑，草稿只包含当前实现的字段。
- [x] A4：decision 阈值可显式设置或清空，未设置由后端解释；打开页面不写默认配置。
- [x] A5：运行展示、保存状态和待应用提示使用各自事实来源，默认值展开不制造虚假差异。
- [x] A6：同一 consumer 的全局身份、数组原子提交、其他草稿保留和撤回行为正常。
- [x] A7：测试覆盖实际编辑路径及协议衔接，前端构建、Full 和类型门禁通过。
- [x] A8：设计文档与最终实现一致，按 AGENTS.md 逐项复核后归档计划。

## 8. 可行性判断与当前进展

方案可在现有模块内完成。后端已经提供实现约束、配置快照和统一应用链路；前端已有草稿集合、consumer 定位、可选数字输入及双语文案设施。主要工作是收紧编辑类型、修正数据来源与提交方式，并补上此前遗漏的交互测试。

2026-11-16 收尾校正：`OptionalNumberRow` 现接收 catalog 声明的最大值，decision 阈值超出 `0..3` 时在前端标记为无效且不写入草稿；归档后的本地链接已按新目录层级修正。当前复核聚焦测试为 30 项，前端全量 912 项，后端 Full 1500 项，`ty check` 与构建均通过。

实现时需要关注的交接点是：联合类型迁移后的所有提交调用点、数字控件的空值/单位，以及原始配置与运行默认值的区别。上述设计已明确这些语义，目前没有需要维护者另行决定的架构事项。

当前完成：P1–P4 全部实施完毕。实施要点：`bindingsModel.ts` 的 BindingDraftValue 改为按实现判别的联合类型，encodeBinding 按分支构造 target/options（空对象省略、0 阈值保留）；`ActionsPage.tsx` 的 ModelUseEditor 由完整 saved+draft 条目驱动（运行投影只读、不回填），实现切换建立干净分支，decision 阈值改可清空 OptionalNumberRow 并补双语“留空使用默认阈值”说明，待应用徽标按草稿 vs 保存快照同形态比较。验证证据：models.test.ts 新增未设置值/零阈值编码形态断言（13 项通过）；BehaviorPages.test.tsx 新增四条主线交互用例（改链只提交 llm_task 字段且保留其他 consumer、清空上限不再回填、切换 decision 无残留、打开页面不产生草稿且无虚假待应用提示；共 30 项通过）；一次性契约核对脚本（.local-test/binding-contract-check.py）将前端编码候选交给真实 parse_action_settings + ModelUseRegistry 六条全过（含旧错误形态被拒的对照证据）；后端既有 tests/kernel/action 25 项通过。门禁：前端 tsc 零错误、vitest 105 文件 912 用例全绿、build 通过；仓库 scripts/test.ps1 -Suite Full 1500 项通过；scripts/typecheck.ps1 全过。文档：config-coverage.md §3.2 补绑定编辑语义段（consumer 数量改动态声明），settings.md 行为页条目同步。
