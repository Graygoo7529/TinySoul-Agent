# 模型 family 来源与草稿一致性修正方案

日期：2026-10-17

状态：done（2026-10-17 已逐项核对源码、模板、文档及验收结果，按 AGENTS.md 归档）。

关联：[模型目录与运行方案改进执行计划](../20261015%20模型目录与运行方案改进执行计划.md)。原计划因后续发现的运行方案与任务模型选择问题重新打开；本专项的 family 来源修正保持完成，详见[提交后复核](../20261017%20模型配置执行计划复核.md)。

## 1. 核对结论

后端已有 `create_source`、候选 include 加载、保存与重载能力，可以承载同一文件中创建多个模型。主要遗漏在前端：模型投影已包含草稿，但 family 的可写来源查找仍只读取 saved sources；新建、重命名和撤销没有完整共享这个事实。

本次按正常编辑流程修正，不引入 family 注册表、模型别名、兼容读取、文件搬迁工具或独立配置状态机。family 继续是模型的显示字段；物理文件与 source 继续属于已有配置设施。

## 2. 已确认的问题与证据

| 场景 | 修正前行为及代码位置 | 修正目标 |
| --- | --- | --- |
| 新 family 连续添加两个模型，期间没有保存 | `LlmModelsPage.tsx` 的 families 使用投影模型，familySources 却只接受 saved 中可写来源；第二个模型回退到默认 ungrouped 来源 | 两个模型都指向同一草稿 source，提交仅包含一个 create_source |
| 删除最后一个模型后，复用留下的空 TOML | 新 family 的 sourceCollision 只判断文件是否在 saved sources 中，不区分空文件 | 已加载、可写的空文件直接接受 set，不再次创建文件 |
| 新 family 的唯一草稿模型重命名 | `objectEditing.ts` 先 resetEntries；store 因没有字段引用删除 create_source，然后才写入新 ID | 重命名保留原 source，清理以改名后的草稿引用为准 |
| 一个 family 的模型分布于多个文件 | familySources 使用 Map 重复写同一个 family，最后遍历的模型决定落点 | 明确复用唯一来源或使用 family 规范文件，不由模型排列顺序决定 |
| 连续新增多个 family，项目使用显式 include | 创建逻辑从 saved 读取 include；后一次追加可覆盖前一次草稿追加 | 从当前投影读取并合并 include，保留既有顺序并去重 |
| 新建弹窗先选择 Adapter | Adapter 候选被当前 Provider 限制，effect 会根据 Provider 重设 Adapter | 依照已确认的 family → Adapter → Provider 顺序，Provider 按 Adapter 筛选 |

修正前，`ungrouped.toml` 的实际用途是 catalog 的固定默认来源；两套模板只有“User-created model definitions are written here”注释。该注释与按 family 创建文件的主流程不一致。前端新建已要求选择 family，因而默认兜底会掩盖来源解析遗漏。

修正前的前端测试覆盖 source 操作构造、单对象撤销、已保存模型重命名和草稿 Provider 选择，但没有串联“新 family → 连续添加 → 草稿重命名 → 保存”的路径。2026-10-16 的门禁通过记录仍是有效执行记录，不能据此宣称这些路径已验收。

## 3. 已确认的语义

### 3.1 family 决定新模型的目标文件

| 输入情景 | 目标来源 | 提交操作 |
| --- | --- | --- |
| 已有 family 只有一个可写模型来源，包括草稿来源 | 复用该来源，不根据 family 名重新推导路径 | set |
| 新 family，对应文件尚不存在 | `configs/llm/models/<family-slug>.toml` | create_source 一次，随后 set |
| 同一草稿继续向新 family 添加模型 | 复用先前声明的 source | 追加 set |
| 所选规范文件已加载且可写，为空或仅承载目标 family 的模型 | 复用现有来源 | set |
| family 已分布于多个文件 | 新模型使用 family 的规范文件；不存在则创建 | set，必要时 create_source |
| 所选新文件名已经用于其它 family，或目标不可写 | 表单提供简短说明；文件名冲突时允许改名 | 不写入无关来源 |

family 名、文件名和逻辑模型 ID 分开。普通英文 family 自动建议小写连字符文件名；用户指定过文件名后，后续模型沿实际 source 复用。无法生成明确文件名时让用户填写，不用含糊的 `family.toml` 自动占位。文件名输入只在需要选择新文件时作为辅助项出现。

同名 family 的输入应归入已有 family 的解析流程，不能通过“新 family”重复建立另一套来源选择规则。空文件本身不创建 family 胶囊；family 仍由模型成员投影。

已有模型的字段修改和重命名写回所属来源。修改 family 字段只改变分组，不搬迁模型。不建立文件名与 family 必须相等的运行时约束。

### 3.2 取消模板中的 ungrouped.toml 默认来源

删除 development/standard 的空 `ungrouped.toml`，并取消 LLM model collection 的固定 `create_source`。新模型必须得到明确的 family 目标来源；解析失败不能静默落入另一个文件。

“未分组”仍是缺少 family 显示信息的模型的 UI 分组，不要求对应物理文件。普通手写模型仍按当前解析规则加载，编辑使用其实际来源。这是当前通用 TOML 语义，不增加旧格式转换或兼容分支。

通用 collection descriptor 原先要求固定 create_source，因此不能只删除模板文件。本次将该字段改为可选：有固定创建位置的 Provider、任务链等继续声明；LLM 模型省略，前端按上述规则解析。后端类型使用明确的可选值，JSON 省略未设置字段；前端不能因字段缺失丢弃整个 collection，也不能以空字符串冒充来源。

维护者已确认这一项语义调整；原计划 §4.4 同步改为固定创建来源可选，不保留默认文件或旧格式兼容分支。

## 4. 实现安排

### 4.1 统一来源投影与选择

在现有 `models/collectionDrafts.ts` 中提供纯投影/解析逻辑，输入为 saved sources、create_source 草稿和现有模型投影。该结果按需计算，不另存 family 状态或持久映射。

- 来源存在性同时包括已保存来源与本批次声明创建的来源。
- family 的成员及 ownerSources 使用 saved + draft 的一致视图。
- 同一 family 的多个候选来源先去重，再执行明确选择规则，避免 Map 最后一项覆盖。
- 解析结果明确给出目标 source 和是否需要创建，或者可在表单展示的局部问题；不返回默认文件兜底。
- 编辑既有字段优先使用字段实际来源；新增字段、重命名等同样要求已解析的可写目标，清除共享编辑 helper 对固定默认文件的隐式依赖。

### 4.2 创建、重命名和撤销保持一致

`LlmModelsPage.tsx` 负责表单交互，调用统一解析结果，再交给既有 store 和 objectEditing。是否生成 create_source 由目标来源是否存在决定，不由用户点击“新 family”这一 UI 状态决定。

重命名先保留新 ID 对同一 source 的引用，再撤回旧 ID 草稿；无引用 source 的清理由最终草稿集合决定。只修正现有编辑顺序或集中为一次草稿更新，不引入通用事务框架。

删除其中一个草稿模型应保留同文件其它模型与 create_source；删除最后一个模型或放弃全部草稿后移除无引用声明。已保存空文件继续保留，复用时不发送 create_source。

默认模板已有 `configs/llm/models/*.toml`，创建新 family 无需改 include。对已有的显式 include 追加逻辑，读取当前投影并合并；后端仍负责正式 glob 匹配与候选校验，不在前端复制一个通用 include 引擎。保留草稿撤销语义，避免遗留指向已撤回新文件的自动 include 项。

### 4.3 后端与错误边界

后端仅需调整 collection descriptor、catalog 序列化及模板；`create_source` / set / delete 的 Endpoint 与 SDK 操作协议继续使用现有定义。候选和落盘继续共用 ProjectConfig → LLMConfigParser，不增加 family 专属解析器。

文件名冲突、缺少可写来源等属于表单可修正问题；实际保存失败继续使用配置模块 ConfigError 和现有 Endpoint 映射。专用模型协议、LLM adapter 以及 Runtime bridge 不承担来源选择，也不因此增加新失败类型。

## 5. 改动范围预览

| 文件/目录 | 预期改动 |
| --- | --- |
| `visualization/src/features/settings/models/collectionDrafts.ts` | 来源投影、family 目标选择及字段写入来源解析 |
| `visualization/src/features/settings/models/LlmModelsPage.tsx` | 使用统一解析；复用草稿/空文件；调整 Adapter 与 Provider 依赖；include 从投影合并 |
| `visualization/src/features/settings/models/objectEditing.ts` | 草稿模型重命名保留来源；消除模型编辑的默认文件兜底 |
| `visualization/src/features/settings/draft/store.ts`、`model.ts` | 必要的 source 草稿生命周期调整，复用现有操作构造与清理 |
| `tinysoul/infra/config/descriptors/models.py`、`loader.py` | collection 固定 create_source 可选，并保持 typed 校验 |
| `tinysoul/infra/config/catalog/models.toml` | LLM model collection 不声明固定 create_source |
| `visualization/src/features/settings/draft/catalog.ts` 及固定来源消费者 | 解码可选来源；固定创建位置的 collection 正常使用已声明来源 |
| `tinysoul/assets/{development,standard}/configs/llm/models/ungrouped.toml` | 删除空模板；保留已有 family TOML 与通配加载 |
| `docs/design/infra.md`、`docs/design/llm.md`、`docs/endpoint/configuration.md`、`visualization/docs/design/config-coverage.md` | 同步来源选择与 catalog 可选字段的当前契约，删除默认 ungrouped 叙述 |
| 对应现有测试文件 | 补充真实交互和配置协作回归，修改固化默认落点的断言 |

没有已证明需要的新 Python 模块、额外依赖或新增 HTTP 路由。

## 6. 验证与完成条件

- [x] 已有 GPT family 新增模型写入原 gpt.toml，重命名和字段编辑保持原来源。
- [x] 新 Qwen family 连续创建两个模型，只生成一次 create_source，两个 set 指向 qwen.toml。
- [x] 新 family 的唯一草稿模型重命名后，create_source 仍存在，原 ID 不残留。
- [x] 删除一个草稿模型保留剩余模型和来源，删除最后一个则撤回无引用来源及本流程自动追加的 include。
- [x] 已加载的空 family TOML 可以复用，选择其它 family 占用的文件名得到清楚的局部提示。
- [x] 两个新 family 同批创建且 include 为显式列表时，两项追加都保留；通配模板不产生无谓 include 修改。
- [x] Adapter 选择决定可选 Provider，不被旧 Provider 反向重置。
- [x] 模型 collection 未声明固定 create_source 时仍可显示和创建；其它固定来源集合照常工作。
- [x] 保存并重载后，新模型由同一 TOML loader 加载，并在模型列表和任务模型选择中可用。
- [x] 按 owner 补充最小回归；前端组件至少覆盖一次连续创建与重命名流程，后端验证代表性 create_source + 多模型保存/重载边界。
- [x] 实施后通过受影响模块测试、Full/typecheck 与前端测试/构建，逐项核对原计划 P4/P6；完成时按 AGENTS.md 规则标记 done 并归档。

## 7. 实施记录

- family 来源解析统一放在 `models/collectionDrafts.ts`，按 saved + draft 视图复用文件，保留唯一实际来源，多个来源时选择规范文件。空文件复用与文件名冲突使用同一规则。
- `LlmModelsPage.tsx` 使用明确目标创建模型；首次 Adapter 选择独立于 Provider，Provider 只显示兼容候选。编辑器使用实际 writeSource，取消模型固定创建来源。
- `objectEditing.ts` 在撤回旧 ID 草稿前建立新 ID 对同一 source 的引用；source 生命周期仍由现有 store 负责。
- source 草稿只在自动追加 include 时记录其 `includeSourceId`，用于撤回自己追加的路径；不存另一份 include 列表。操作请求仍只有既有 create_source/set/delete，内部标记不发送至后端。
- catalog 固定创建来源改为可选，缺省时 JSON 省略字段；Provider、任务链等固定来源消费者保留实际声明。两套空 ungrouped 模板已删除。
- 增补连续创建、重命名、删除、空文件复用、Adapter 选择和 include 合并撤回回归；原先只验证单模型写入的后端用例升级为多模型与任务链共同保存、磁盘重读和激活的协作用例。
- 聚焦验证：前端相关测试 58 项通过，配置模块 78 项通过。
- 完整后端门禁：使用 TinySoul Conda 解释器运行 `scripts/test.ps1`，Fast 1273 passed、28 deselected；Full 1278 passed、23 deselected。Full 包含项目生成与 wheel 安装验收，按规则排除 external 测试。
- `scripts/typecheck.ps1` 通过，`ty check` 无错误。
- 前端完整验证：91 个测试文件、807 项通过；TypeScript 检查与 Vite 生产构建通过。通过 Node 调用本地已安装的 `vitest/vitest.mjs`、`typescript/bin/tsc` 和 `vite/bin/vite.js`，未改动依赖；构建仅有现存的大 chunk 提示。
- `git diff --check` 通过；原计划 P4/P6 与本计划验收项全部核对完成，两份计划均按规约标记 done 并归档。

## 8. 按 AGENTS.md 复核

| 规约与验收项 | 实施位置与核对结论 |
| --- | --- |
| 持久事实单一 owner，不引入重复目录 | 配置文件仍由 `infra.config` 管理；family 从模型投影得到，目标来源由纯函数解析，没有注册表或文件迁移逻辑。 |
| 同一草稿贯通正常编辑主线 | `pages.test.tsx` 串联新 family、首模型重命名、第二模型创建和逐个删除；`store.test.ts` 验证两份显式 include 追加及撤回；操作构造继续使用现有协议。 |
| 实际来源决定编辑位置 | `collectionDrafts.test.ts` 验证 GPT 实际来源、空文件及多来源选择；组件使用 Kimi/GLM 代表性对象覆盖既有 family 添加和重命名，规则不依赖具体 family 名。 |
| 新文件与既有文件统一加载 | `test_config_controller.py` 验证同批创建文件、写入两个模型并更新任务链；磁盘重读经 `LLMConfigParser` 校验，reload 激活包含两个模型。模型列表和任务选择继续消费同一配置投影。 |
| 动态入口明确类型，失败留在所属边界 | descriptor 明确使用可选字符串并保留校验；前端解析结果区分有效目标与表单问题。保存、加载异常沿用 ConfigError 与 Endpoint 映射，未增加 Runtime 失败语义。 |
| 复用设施，消除死抽象与兼容残留 | 新增逻辑位于既有文件；`includeSourceId` 仅由撤销流程消费且不进入 API。删除默认 ungrouped 模板和 catalog 声明，没有旧格式读取、别名或迁移层。 |
| 文档描述当前事实 | 同步 infra、llm、Endpoint 配置协议和前端配置覆盖文档；原计划 P4/P6 的缺口与本计划逐项对应。历史 2026-10-16 验证记录保留原时间和范围。 |

测试按 owner 覆盖：组件验证用户操作至提交操作集合，配置控制器验证操作至磁盘与激活；没有把组件测试描述为真实浏览器连接 Endpoint 的端到端测试。本次不调用真实 Provider，也不改写既有用户项目文件。
