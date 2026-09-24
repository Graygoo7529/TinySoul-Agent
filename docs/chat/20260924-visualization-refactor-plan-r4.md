# Visualization 前端重构与建设执行计划

> 日期：2026-09-24；交付版本：20260924-r4。
> 状态：pending。设计已经整理，功能实施与验收尚未开始。
> 最新检出：10b43c9e1b9d245da9029fd713510317b754e662。本次新增提交仅调整文档；业务代码与已复核的 f4965082011f5c654e4a877f6aea3e8d3fe053bd 一致，AGENTS.md 未变。
> 配套计划：[后端功能支持执行计划](../../../docs/analysis/20260924-visualization-backend-support-plan-r4.md)。
> r4 替代 r3：按原版保留对话/工作区布局与 Luminous 风格，设置重组，Context 回到右上入口；Action 模型使用集中编辑为 Q-02 建议，待讨论确认。本轮不制作新预览。
> 本文引用 API-01～API-19，与后端计划逐项对应。标为新增/扩展的接口当前不可当作已实现使用。
> 后续讨论：[Action 模型用途与 Reflection 写入架构提案](../../../docs/analysis/20260924-action-model-usage-architecture-proposal.md)。Q-03 若确认，Actions 模型使用将基于正式用途绑定，Home 固定链可编辑，运行方案 routing 同步迁移；原版布局保留等界面决定不受影响。

阅读顺序：§1～3 是边界与数据架构；§4～15 是功能设计；§16 是 Endpoint 清单；§17～19 是实施与验证；§21 的 P00～P14 是逐页交互规格；§22 是代码交接；§23 是需求复核与范围确认记录。前端实现者应同时阅读配套后端 §4～10 和附录 DTO，不能只依页面截图猜接口。

## 1. 产品目标、范围和已确认决策

Visualization 是 TinySoul 的交互、资源浏览、配置和运行观察界面。它呈现同一个 Agent 的正式状态和事实，帮助用户与 Agent 协作；不在浏览器里重建执行内核。

本轮以最新 AGENTS 为语义依据，保留现有 React 19、TypeScript、Vite、Tauri、Zustand、Tailwind、motion、react-markdown 与 KaTeX 基础。重构数据流、页面职责和共享渲染，而不是为换技术栈而重写。

界面改动范围：对话与 Workspace 保留主要布局、组件和成熟交互，以新增能力及语义适配为主；设置整体重组但保留 Provider/模型/任务链的对象编辑逻辑；Home、Memory 新设计；运行观察按本计划建设。原版 styles/index.css、utils/motion.ts 与现有页面是视觉依据，r3 概念预览只作交流记录，不作为重做所有页面的样板。

已确认并纳入本文：

- 设置整批草稿，通过配置应用命令保存并重载；发布前失败撤回本批保存，草稿可修改或放弃。
- 运行方案由后端按项目保存；包含模型、任务链、调用分配，可选纳入 Context/Turn 预算；对话输入区旁提供选择入口。
- 当前 Turn 不切换运行方案；空闲时切换 Agent generation，随后各客户端读取真实状态。
- core.ask 表单回复同一 Turn；普通回答中的表单填入输入框。
- 后端模型配置增加 family/collapsed，分别表示模型簇和默认收起，不等于禁用。
- JEV、图像生成等规划能力分类与配置接入；具体业务消费另行设计。Embedding、Web 等当前能力必须可实际配置。
- Home/Memory 浏览与发起 Reflection 属于本次；直接编辑 actual Home、持久 Memory、Session map 不在本次。

### 1.1 原始需求覆盖

| 需求 | 本文落实位置 |
|---|---|
| 承接后端重构语义/API | §3、§16、F0/F1 |
| 设置布局、现代控件、批量配置 | §10～§12 |
| 本地与后端设置分开 | §10.1、§13 |
| 命名配置方案与聊天选择 | §4.3、§12 |
| Context、Session、模型调用 | §5～§6 |
| Action 可视化与旧 demand | §6.3、§17 |
| ACP/MCP/Jobs/事件/监听 | §9 |
| 追加、提问、回复、可扩展代码块 | §4、§14 |
| Memory/Home 页面 | §8 |
| 统一链接与资源路由 | §15 |
| 其他使用和性能改善 | §3.4、§18 |
| 保留优化视觉风格及两份计划 | §2、§19，与配套后端计划 |
| 补充模型簇与折叠、非 LLM 服务配置 | §11 |

## 2. 全局布局与视觉系统

### 2.1 信息架构

主导航：对话、工作区、Home、Memory、运行观察。底部固定连接入口、设置入口。Session map 是对话页面内部视图；Reflection 是同一 Agent 的执行情景，在 Home/Memory 和运行观察中有入口与状态，不另建“维护系统”。

沿用现有 AppShell、NavRail、TopBar 和 StatusBar，各页按任务选择结构，不强制统一成四栏：

- 左侧 NavRail：约 60～68 px，图标、名称提示、当前页标识。
- 页面二级导航：Workspace 保留约 280 px 文件栏；设置按类别与对象组织；Home/Memory 自行设计目录。主对话默认没有新增日期/Turn/话题侧栏。
- 中央内容：主任务区，承担主要阅读/编辑。
- 详情沿用按需打开的 Drawer，可扩展为全宽；不是主对话或 Workspace 常驻右栏。Context 从原 TopBar 右上按钮打开，Action/模型任务从原过程入口打开。
- 全局顶部：项目/连接名、后端活动状态和当前页必要操作。常态不展示原始 UUID。

Drawer/Inspector 共用导航与来源组件；同一时刻一个主详情，内层资源通过返回路径切换，不无限叠窗。无需为统一详情而重建全部页面 Shell。大地图和复杂差异可全宽查看，返回保留原页面滚动、草稿与选中项。

### 2.2 响应式布局

| 可用宽度 | 布局 |
|---|---|
| ≥1440 px | 原版页面主布局；资源/设置页可有目录，详情按需打开；不自动给聊天增加侧栏 |
| 1100～1439 px | 原版中央优先，页面自有目录可折叠，详情覆盖或全宽查看 |
| 768～1099 px | 单主区，树/目录改弹层，Inspector 覆盖 |
| <768 px | 底部或紧凑主导航；详情全屏 sheet；输入框固定底部，不显示四栏 |

断点是实施设计值，验证时按内容最小宽度调整，不按设备名称写特殊页面。树、长代码和表格只能在自己的区域横向滚动。

### 2.3 Luminous 视觉延续

沿用现有亮/暗主题、中性三层底、hairline、靛蓝至蓝色品牌渐变、领域色、细微光效与 motion。域色表示来源，成功/失败/等待色表示结果，两者不能混用。

- 正文默认 14 px，可由用户调节；Inter + PingFang SC/Microsoft YaHei/system-ui，代码为 JetBrains Mono 等宽回退。
- 次级文案以 12～13 px 为主，10 px 只用于不承担必要阅读的信息。
- 卡片强调阅读层次，避免每个动作都使用高亮大阴影。
- 运行中可有轻量流光；等待用户是稳定的待答状态，不伪装成仍在计算。
- 保留原版运行流光、过程收拢、回答呈现与平滑滚动语汇；用新正式状态驱动。动画不推迟按钮可用、问题显示或状态更新。恢复历史不逐条播放入场。
- 键盘 focus、错误文本、选中态在两主题都可辨；状态同时提供文字/图标。
- reduced-motion、字体缩放和高密度模式使用统一 token。

### 2.4 产品文案与信息密度

页面以对象、内容和操作为主体。不增加愿景口号、设计解释、每卡固定副标题或“让每一种运行事实……”式说明。标题下面只有用户确实需要才能做决定的说明；常规机制解释放 tooltip、帮助或设置高级区。

状态用简短文字/徽标、空间和对齐组织，不用“·”拼接日期、阶段、模型与预算为装饰性小字串。必要来源和错误说明保留；不改写用户/模型原文、路径或代码中的标点。UUID、owner、shape、ref、generation 等默认在详情/高级区，不挤占日常主界面。重要正文和操作不用低对比小字承载。

空态只交代当前状态与下一步，例如“没有待整理变化”“添加 Provider”；不放产品宣传句。预算/模型链的技术摘要在选择器展开后呈现，Composer 收起时只显示方案名称与必要状态。

## 3. 数据架构与前端代码组织

### 3.1 正式来源

| 页面数据 | 权威读取 | 实时更新/详情 |
|---|---|---|
| 活动 Turn 与队列 | status、TurnSnapshot | 事件触发刷新 |
| 当前已接受交互 | Turn interactions | 按 identity 增量合并 |
| 完成的用户对话 | Session turns/interactions | 完成通知后接续 |
| 当前模型 Context | Context snapshot/segment/inspect | Context changed 提示刷新 |
| 当前资源与知识 | Workspace/Home/Memory owner 查询 | 相关变化通知失效 |
| 模型请求、动作过程、诊断 | Observation | scope 定向分页 |
| 配置 | saved/active config、catalog | 应用后重新读取 |
| UI 偏好、草稿 | 前端本地 | 组件直接订阅 |

不以 raw events 全量扫描推导所有页面；不以 Observation 重放替代 Session/manifest。前端缓存是派生数据，可丢弃重建。

### 3.2 建议目录职责

| 目录 | 职责 |
|---|---|
| src/app/ | 组装、导航、全局外壳、连接生命周期 |
| src/api/ | v2 transport、类型化客户端、错误边界、事件流 |
| src/state/ | 后端快照/事件实体缓存、选择器、连接级失效 |
| src/features/chat/ | Turn 交互、Composer、方案选择、Session 导航 |
| src/features/context/ | 段目录、披露浏览、Session 关系视图 |
| src/features/workspace/ | 资源树、编辑、Trash、归档 |
| src/features/home/、memory/ | 各 owner 内容浏览与 Reflection 入口 |
| src/features/activity/ | Turns/Jobs/ACP/MCP/环境与日志 |
| src/features/settings/ | 草稿、类别与专用配置编辑器 |
| src/rendering/ | Markdown、代码块、动作展示、资源链接注册表 |
| src/components/ui/ | 视觉原语，不持有业务协议 |
| src/types/、utils/ | 边界类型和真正通用工具 |

迁移现有 api/store/derive/components 到上述职责时逐项替换；不同时保留旧 appStore 全量状态机和新实体 store。目录名允许按实际模块规模合并，但职责不可重叠。纯函数、React 组件按现有 TypeScript 风格使用，不机械地把每个 UI 函数改成类。

### 3.3 实体身份与注册

缓存 key 包含项目/instance、必要的 generation/day/turn。Active Context 必须绑定 turn；资源正文区分 effective/actual、当前/归档。绝不能只按 resource link 缓存所有日期的 Workspace。

显式注册四类扩展：

1. ActionRenderer：精确 action id、family、结果判别与卡片内容。
2. CodeBlockRenderer：语言标识、parse、render、lazy load 和导出。
3. ResourceHandler：Link 解析、定位上下文、预览与页面路由。
4. SettingsEditor：catalog surface/capability_kind 到专用表单；model.family 只负责模型簇展示。

不强制四类使用同一接口。公共 RenderContext 只提供来源身份、资源导航、受约束回调和本地偏好，不提供整个 store 或任意 HTTP client。

### 3.4 首屏与重连

1. 验证连接实例/项目身份，读取 status。
2. 加载当前日最近一页 Session 摘要、活动/排队 Turn；活动 Turn 读取 interactions。
3. 用 status 的事件游标接续 WebSocket；快照期间到达的事件缓冲后按 identity 合并，必要时重读受影响 owner。
4. detail 面板打开后再取 Context、模型正文、长输出、图形依赖。
5. gap=true 或 instance 改变时，清除相关事件派生状态并读取正式快照；不能把空事件页当作“没有消息”。
6. generation 改变时使活动能力/config/context 查询失效；旧完成的 Session 页面仍按日身份读取。

一次快照不宣称跨所有 owner 的数据库事务。通过既有身份、快照替换和变化通知收敛即可；不增加全局 revision/CAS。

错误在 API 边界转换为稳定 UI error；字段错误贴近控件、资源错误贴近面板、连接错误统一横条。局部 Action 失败是卡片内容，不触发全屏断线。网络断开不表示 Turn 停止，也不自动重放写操作。

## 4. 对话页面

### 4.1 空间布局

保留 ChatView 的单列连续对话、当前 max-w-3xl 阅读宽度、底部 Composer，以及 TurnView/LiveStatus 的用户气泡、Agent 过程和回答层次。默认不新增左侧 Session 导航、不新增“今天/日期/对话/地图”顶部切换栏、不常驻 Context 右栏。宽度只因内容可读性做局部调整，不以预览尺寸覆盖原版。

TopBar 右上原 Background Context 按钮升级为 Context；内部显示当前 Home/Memory/Session 等段。历史浏览放按需“历史记录”入口（现有历史控件或更多菜单），打开后选择归档日/Turn；读取历史时才出现必要的来源日和返回当前对话操作，不引入常态日期栏。

提问卡、用户追加/回复、预算卡嵌入现有消息序列；运行方案放 Composer 旁。原有过程详情入口保留。新的排队和待答提示按实际状态出现，无内容时不占位。

ChatView 的滚动锚点、用户滚动后暂停跟随、历史恢复不播动画等交互继续保留。TurnView 需从“把全部 userMessages 放在轮首”改成按交互事实穿插，但复用现有气泡/过程/回答组件；视觉延续不能导致补充与回复被移动到错误位置。

### 4.2 消息和过程呈现

- 初始输入：用户消息。
- 追加输入：相同用户风格，带小型“补充”标记和所属 Turn。
- Agent 问题：回答卡同族视觉，清晰的问题与选项。
- 用户回复：用户消息，附“回复此问题”关联，可跳回问题。
- core.reason：可展开的思考/说明片段，只显示真实已披露内容。
- 动作过程：默认紧凑活动列表，按 Cycle 分组可折叠。
- 最终回答：完整 Markdown 卡；停止/失败保留实际已产生内容和结果状态。
- Reflection：显示独立运行提示和详情入口，不冒充 Agent 对用户的正式回答。

展示状态至少区分：本地发送中、后端已受理、等待处理、模型已可见（有明确事实时）、失败。输入消息按稳定 identity 更新，不按文本查重。pending 输入的最终事实位置由 owner 给出；滚动锚点需保持。

接口：API-02/03/04/05/09/10。历史正文来自 Session，过程细节缺失不会让正式问答消失。

### 4.3 Composer 与运行方案

Composer 原布局内增加紧凑方案按钮，例如“均衡 ▾”；不增加相邻的 cycles/Context 预算说明串。可访问名称为“运行方案”，预算和链详情在弹出层中查看。名称由用户保存，示例“均衡”不是一套新的全局推理强度开关。

方案 Popover 宽约 320～380 px：

- 顶部当前方案/已修改状态；
- 搜索与命名方案列表；
- 默认每项显示名称与选中状态；用户填写的简短说明可选显示，链和预算摘要在该方案详情中查看；
- 展开差异查看模型链/预算变化；
- 底部“保存当前为方案”“管理方案”。

点击方案在空闲时调用 apply，成功后更新选择；不乐观地先显示已切换。活动/等待/排队不能切换时说明原因，仍可查看或进入设置编辑。保留用户草稿，不自动取消 Turn，也不把方案点击变成新消息。

本次只提供独立的“应用方案”和“发送”。应用未完成时禁用发送，成功后保留草稿由用户发送；不把两次独立请求包装成具有原子保证的“应用并发送”。活动轮显示实际运行中的方案摘要；历史没有记录方案标签时不显示标签，只展示保留的真实模型调用信息，不能用最新配置倒推历史。

模型推理强度属于方案内各模型配置；不在 Composer 加一个会覆盖所有任务的虚假全局 reasoning slider。

### 4.4 输入状态表

| 当前情况 | 默认发送行为 | 旁路操作 |
|---|---|---|
| 空闲 | POST turns，创建 User Turn | 选择方案 |
| 当前 User Turn 运行中 | POST /input，明确标记“补充当前轮” | “作为下一轮排队”使用 POST turns |
| 等待 core.ask | 表单/回复模式调用 /reply | “仅补充信息”仍是 /input，不能代答 |
| 等待预算 | /grant 正整数追加；也可取消 | 问题与预算共存时分别处理 |
| 正在 Reflection | 默认创建排队 User Turn | 不把日常文本塞入 Reflection 来源 |
| finalizing | 明确“作为下一轮” | 不再向关闭的 Inbox 追加 |
| 断线/后端未就绪 | 保存本地草稿，发送不可用 | 重连后重新查询 |
| 查看历史日期 | 明确提交到当前日，不续跑归档 Turn | 回到今天、引用历史事实 |

不要使用 /v2/input 的终端命令语义承担主聊天；这里使用结构化 Turn API。用户输入斜杠文字按普通文本处理，前端命令菜单是单独显式 UI 操作。

### 4.5 提问表单

每个选项为整行卡片，含 A/B/C 视觉序号、label 和可选说明；A/B/C 不是提交身份。默认末项“其他”展开输入框。选中后点“提交回复”，支持键盘选择和提交。

绑定 active question 时调用 typed reply；成功保留问题和回复，表单转为只读。提交失败保留选择，不自动换成 append。超时/被取消/已在另一客户端回答时重新读取问题状态。

普通 answer 的表单选择只生成 Composer 草稿，按钮文案“填入回复”；历史 ask 表单显示当时选择及来源，不重新启用旧 question_id。

待答问题立即呈现，不受打字机和动作节拍延迟。用户在历史位置阅读时提供待答定位条，避免强制抢走滚动。

## 5. Context 与 Session map

### 5.1 Context 面板

从右上 Context 按钮打开原 BackgroundDrawer 升级后的详情界面。标题为“上下文”，必要时显示活动 Turn；捕获时间放刷新信息中。默认三组：

| 展示组 | 内容 | 典型交互 |
|---|---|---|
| 背景资料 Background | identity、session、inputs、home、memory | 段目录、加载状态、引用追溯 |
| 当前过程 Trace | TurnTrace、工具发起与结果、可见输入/事件事实 | 栈顺序、折叠块、inspect |
| 工作状态 Working | plan、Workspace 索引、Jobs、connections | 当前值、变化提示、跳转 owner |

每段行以名称和必要的加载/折叠状态为主，展开后显示字符量和来源；owner/shape/ref 等进入技术详情。实际顺序取 descriptor，不维护写死的消息标签顺序。TaskPrompt 只在具体模型调用中显示，不虚构为一个永久工作段。

API-11 概览 → 段正文 → inspect 按需请求。面板清楚标示“在界面展开”与“Agent 已加载”；本次不提供直接点击 UI 即修改模型 load/evict 的隐式行为。要让 Agent 参考资源，可“引用到对话”，仍由 Agent 决策。

### 5.2 形状与渐进披露

- State：键值、待办、里程碑、连接等最新投影；里程碑保留事实状态，不全部画成完成打勾。
- Heap：目录/顶层线索，已加载项单独标记；点击进入下层引用。
- Stack：按执行顺序列出热区和折叠块，折叠块包含范围/线索及来源。
- Map：话题导航、解释/事实节点、关系和证据。

共享 DisclosureBrowser 显示标题、ref、直接正文、children、related、sources 和“继续读取”。query 输入框只在 capability 支持时出现，搜索范围明确是当前 ref。分页不会偷偷递归加载全部子节点。

折叠是当前投影/访问形态，不表示底层内容已删除。UI 展开不执行 core.context.inspect Action，不生成模型工具消息。

### 5.3 Session map

从 Context 的 Session 段进入会话地图。先呈现本轮安装的 Session 内容与引用，再提供“浏览当日会话地图”读取 owner 完整 map；两者来源有清楚标签。默认列表/分支大纲，选中后展示局部关系；宽图可在这一入口全宽展开，返回原抽屉和聊天位置。主聊天不另设“对话/地图”页签或话题侧栏。

关系图：

- 问题、回答、追加/回复等事实有明确样式；
- thread/note 等解释使用不同图标/线型；
- 解释节点展示来源与修订/撤回状态；
- 共享节点仅一个身份，多条边引用；
- 点击 Turn 或来源跳回对应对话，不复制正文到每个话题；
- 未归类 Turn 有固定入口，不能因未 Organize 而消失。

日选择使用 API-09；API-10 读取原日 map。归档只读，不构建跨日合并语义图。UI 可以把“请梳理这些对话”的意图填入当前聊天，不能调用外部 Session 编辑 API。

## 6. Trace、模型任务和 Action 可视化

### 6.1 Trace 详情布局

中央或 Inspector 显示 Turn → Cycle → Phase 的折叠树，顶部过滤“交互 / 动作 / 模型调用 / 事件”。默认只展开当前活动分支。

阶段失败、Action 局部失败、Turn 失败与附属清理诊断分开显示。未执行、取消、结果未知不渲染为普通成功 ToolResult；计划调用不等于已执行。

Trace 与 Session 是互相跳转的不同视图：Session 负责完成的对话事实与解释；Trace 负责当前过程及保留的观测细节。

### 6.2 模型调用详情

模型任务 Inspector 标签：

1. 概览：task profile、所属 Phase/Action、模型/Provider、耗时、实际 usage。
2. 请求：原始顺序的 provider-neutral MessageStack；语义分组模式可切换但保留原始 index。
3. 工具与指导：实际 tool scope、控制/Action 工具类别、挂载 Skill 来源。
4. 响应：真实返回的正文、工具意图、披露的 reasoning summary。
5. 尝试：模型/Provider 切换和有限失败信息。

不存在的 token、计费或概率不估成真实值；字符估计明确标记。MODEL 正文通过 API-05 的 task_id/through 定向分页加载，离开面板可释放大 payload。

后端未记录供应商最终网络 JSON 时，界面名称用“TinySoul 消息栈”，不能称“完整供应商请求”。历史正文被淘汰时显示不可用，并继续保留任务摘要。

### 6.3 Action 展示矩阵

统一卡片头：领域图标/色、动作意图摘要、状态、必要计时；展开后是参数摘要、结果、资源/关联操作和原始结构化详情。

| 家族 | 当前真实 Action 示例 | 展开内容 |
|---|---|---|
| 核心交互 | core.answer、core.ask、core.reason | 回答/表单/真实 reason；避免与主消息重复正文 |
| 等待与工作监督 | core.wait、core.job.status/wait/stop | 等待原因、关联 Job、收敛结果 |
| Context/Session | core.context.inspect、core.session.organize | 披露线索、来源、解释变化 |
| Workspace 浏览 | workspace.list/search/read/analyze | 路径、命中摘要、正文、分析引用 |
| Workspace 修改 | workspace.write/edit/append/compose/move/delete/tag/mkdir/restore | 实际目标、变更摘要、可用 diff、标签/恢复结果 |
| 转换/资源 | workspace.convert_with_pypdf、convert_with_markitdown 等 | 输入资源、输出资源、格式与结果 |
| 执行 | execution.run_shell/run_script/start/collect/stdin | 命令/脚本、cwd、stdout/stderr、exit、关联 Job |
| Web | web.search_by_kimi/discover_pages/fetch_with_trafilatura/fetch_with_defuddle | 搜索结果、来源站点、抓取摘要、资源 |
| Home | home.top.*、home.resource.*、home.prompt_mount.*、home.diff/review | effective/actual 来源、变更、Skill mount、review 结果 |
| Memory | memory.inspect/recall/memorize/write/write_daily | 检索、活动记忆、持久文档与引用；标记所属情景 |
| ACP | subagent.agents/connect/delegate/collect/respond/disconnect | 外部 Agent、连接、Job、输出、父 Agent 应答 |
| MCP | expand.describe_servers/describe_tools/search/call | Server、Tool、schema、输入与结果 |

注册优先精确 action id，再 family，最后通用 renderer。未知动作正常显示结构化内容，不因缺少美化组件丢失结果。

卡片不直接读取当前文件拼历史 diff；只有后端提供历史 preview 时显示“本次修改”。“查看当前文件”单独路由到资源页面。长输出、图像、JSON、diff 共用基础查看器。

## 7. Workspace 页面

### 7.1 布局

- 保留 WorkspaceView 约 280 px 左栏与右侧资源预览/编辑区，不重新布局为三栏工作台。
- 左栏顶部沿用 Files/Trash、刷新/新建及搜索；新增上传、标签、归档访问放已有工具区/菜单，避免再铺一整排顶部说明。
- 文件树新增 pinned/tmp/library 标签筛选；标签不表示跨日保留。
- 中央：列表或资源标签页；列表列出名称、类型、大小、说明、标签。
- 资源信息：放在编辑区内的可折叠信息区或按需详情，提供相关 Link、引用到对话；不新增常驻第三栏。
- 编辑模式：中央正文/代码编辑器，上方路径和未保存标记，下方保存/放弃。

目录操作、移动、重命名、标签、trash/restore 使用 API-14，删除解释为正式 Trash 语义，不用旧 mirror/apply/discard。

### 7.2 阅读与写入

Markdown 默认预览，可切源码；代码/JSON/文本使用适合的查看器；图片、PDF、音视频按已有/可支持类型预览，大文件分页或流式下载。不可预览时仍可显示信息和下载。

新增文件必须用户指定名字/类型；修改使用现有 write/edit/append 的正式语义。页面不构建内容 CAS 或 expected_revision。保存前已有用户草稿而收到 workspace.changed 时提示磁盘已变化，保留草稿并提供查看最新/放弃；这是用户可见的编辑选择，不是新并发提交协议。

从历史日进入时所有编辑操作禁用，提示“归档只读”；引用链接携带原日身份。切回当前日不会把旧编辑内容自动写入同名文件。

watcher 状态在顶栏小徽标显示；监听失败允许继续显式文件操作。变化通知使 manifest/相关正文失效，不反复请求所有文件。

### 7.3 对话引用

“引用到对话”生成带实际 Link 和来源日的可读引用，显示在 Composer 的引用区域并序列化为后端可理解文本。没有新增附件协议前，不把前端 chip 当成模型已经收到的资源。

上传写入 Workspace 是明确资源操作；随后用户选择是否引用，浏览/上传不隐式触发 Turn。

## 8. Home 与 Memory 页面

### 8.1 Home

顶栏：effective/actual 分段切换、搜索、“待整理变化 N”、“发起 Home Reflection”。

左栏：身份与规约、偏好、通用 Skill、domain/action guidance、资源。分类由 owner catalog 元数据驱动，不按文件名猜语义。

中央：

- 列表模式显示标题、类型、Link、是否来自 overlay；
- 内容模式显示 Markdown/资源；
- 差异模式为 actual/effective 并排或统一 diff，含创建/修改/删除及真实截断状态；
- Skill 页显示说明和声明的 mount 目标，能跳转相关 Action 设置。

右侧：来源、相关链接、是否在所选活动 Turn 已加载（若有该 Context 数据）、引用到对话。

“已加载”必须来自 API-11，不能因文件存在就点亮。查看旧任务挂载内容走 Task 观测，当前 Home 内容不是过去的快照。

Reflection 按钮打开轻量表单：整理说明，可引用所选 diff；调用 API-15 后展示真实 turn_id/state，提供运行观察跳转。这里不提供直接 accept/reject actual 的越权按钮。

接口：API-12、API-15、API-11、API-06。

### 8.2 Memory

顶栏：搜索框、文本/语义搜索选择、来源日筛选、“整理记忆”。

左栏两组：

- 活动与归档：当日 Memory.md、选定日归档活动记忆；
- 持久知识：daily、entity、concept、fact、note。

中央：目录列表 → 文档正文；右侧：出链、反链、引用来源、关联日期和重定向信息。可提供局部关联图，默认仍为易读的文档与来源列表。

“当日活动记忆”和“该日 daily”分别标注，不共享同一个标题/编辑区。持久 Memory 是当前知识库，不宣称按日期切换就恢复了历史版本。

语义搜索是用户明确发起的请求，显示实际检索方式；缺少配置则引导到 Embedding 设置。目录/输入框每键变化不调用收费模型。没有评分时不画百分比可信度。

整理弹窗明确 target_day、可选 instructions、已有 daily 可再次整理的语义；候选日来自 Reflection availability，不画成必须逐日清空的维护队列。

接口：API-13、API-15、API-09。阅读/搜索不写 Memory。

## 9. 运行观察页面

### 9.1 布局与概览

顶部紧凑状态带：连接/世代、当前日、活动 Turn、排队数量、来源异常。下方标签为“执行 / Jobs / ACP / MCP / 环境与观测”。

中央列表或树；右侧 Inspector 为选中项详情。保留明确 restart 入口于高级操作，关闭页面/窗口不停止 Agent。

### 9.2 执行与 Jobs

执行页显示 active/queued Turns，User 与 Reflection 有类型标记。点击进入对话或运行详情；waiting 显示具体用户/预算/Job/事件/定时原因。手动补额与取消使用正式 API。

Job 列表列：类型、摘要、所属 Turn、state、待答、输出/结果；右侧显示 stdout/stderr 或 ACP 文本分页、结果链接、实际 backend 详情。

stop 只停止该 Job；cancel Turn 是另一个按钮。Job 消失于 Turn 收尾后不假装仍在运行；历史产物从资源和保留观测打开。

Job permission 待答项标记“父 Agent 正在处理”，需要人时在主对话出现 core.ask。这里不直接调用 ACP RPC，也不建立另一条人工应答通道。

### 9.3 ACP

上部为已配置 Agent 目标卡：名称、命令/连接类型摘要、说明、配置入口。下部为真实连接表：ready/busy/unavailable、cwd、关联 Turn/Job。

点击连接查看工作目录资源和 Job；跨 Turn 空闲连接仍可见，连接不伪装成一个活跃子 Turn。操作入口“让 Agent 使用此目标”填入对话意图；真正 connect/delegate 仍由当前 Agent Action 执行。

### 9.4 MCP

左栏 Server 列表，中部 Server 概览与工具目录，右侧 Tool schema。

状态分开显示：配置启用、已连接、目录已发现、工具可调用。没有发现目录时显示“尚未发现”，提供明确刷新按钮，页面加载不自动连接所有 Server。

工具行显示名称、说明、配置允许状态、schema 可用性和最近调用入口。调整允许工具写入设置草稿，不能把当前运行目录里打勾直接当成即时生效。

工具试调用不在本次页面范围；“让 Agent 使用”走对话。历史 expand.search 结果仍属于 Trace，不作为永久 Working 工具列表。

### 9.5 环境与观测

source 状态按 source/topic 分组；Workspace watcher 独立展示。下方事件列表按 Turn/来源/等级过滤、分页，可展开有限 JSON。

默认不显示全部 model 大正文；打开特定 Task 才查询。显示保留窗口/gap 提示，导出内容标明范围与缺失，不能把观测导出命名为完整持久审计。

接口：API-01/02/03/05/16/17/18/19。

## 10. 设置总布局与批量草稿

### 10.1 两个设置范围

设置页顶部范围切换：“Agent 设置 / 本机界面”。

Agent 设置绑定当前 project/backend；本机界面绑定当前设备。断线时本机界面仍可用，Agent 草稿可阅读但不能应用。

Agent 设置使用 224～248 px 分类栏，中部最大约 1040 px 的表单区；复杂模型/任务编辑采用列表 + 编辑器。右侧帮助和来源不常驻占大面积，用字段旁说明及可展开来源面板。

### 10.2 Agent 设置导航

| 主类 | 子页 |
|---|---|
| 概览与方案 | 配置概览、运行方案 |
| 模型与服务 | 通用模型：Provider、模型库、任务链（链定义/循环分配）；专用模型：Provider、模型、用途；凭据 |
| 行为与上下文 | Actions（行为与可用性/模型使用/高级）、Turn 预算、Context、Reflection |
| 工具与连接 | 执行环境、Web Search、资源处理、MCP、ACP |
| 数据与知识 | Workspace、Session、Home、Memory |
| 系统与诊断 | Agent 运行与 Endpoint、观测记录、配置来源与高级项 |

页面顶部统一搜索，可按字段标题、说明、模型/Provider id、实际 key 搜索；结果展示所属路径，点击定位高亮。只有用户选“高级”时默认展开技术 key。

Actions 集中编辑模型使用为本轮 Q-02 建议；相关目录及 §11.5/11.8 按此组织供确认。原任务链页的 Action Routing 入口改为跳转 Actions 并筛选使用模型的动作，不再放第二个独立 override 编辑器。

### 10.3 草稿行为

所有 Agent 子页共享 ConfigDraft：已读取 saved 基线、结构化编辑操作、字段错误、变更摘要。不得每次输入都 PATCH。数组/对象保持 catalog 定义的完整值边界。

底部固定变更栏：

- “已修改 N 项”与查看差异；
- 放弃全部、恢复当前页；
- “应用并重载”主按钮；
- 正在运行时显示需要空闲，不覆盖草稿。

恢复当前页/放弃全部都只撤销本地编辑。若服务器已有其他入口保存的 pending 候选，单独显示“服务器已有待生效配置”，允许查看 active/saved 差异；本地放弃不能声称撤销服务器候选。

apply 成功刷新 active/saved、方案状态和受影响的服务查询；失败定位错误并保留草稿。HTTP 超时不直接判为失败回滚，先查询实际世代/配置状态。前端不发起补偿 PATCH。

服务器已经存在 saved-but-pending 候选时，变更预览同时展示 active→saved 与 saved→本地草稿两部分；应用会激活这份完整候选。应用失败只撤回本批修改，不能声称之前已经保存的其他候选也消失了。

切换后端/关闭带未保存编辑的页面时提供“保留草稿/放弃”选择；普通子页导航不弹确认。草稿可在本设备按 project 保存非敏感部分，凭据输入只保留内存。

## 11. 各设置子页与非 LLM 扩展

### 11.1 配置概览

顶部显示正在运行方案、active/saved 状态与可应用性。中部三个摘要：模型与路由、运行/Context 预算、已配置工具服务。底部显示真实配置问题和近期应用结果。

主要操作是继续编辑、查看差异、进入方案。不会每次刷新重新探测所有远端 Provider。

### 11.2 LLM Provider

保留 ProvidersSettingsPage/ObjectSettingsLayout 的对象列表—详情编辑逻辑及既有连接字段。整体设置导航重组不要求重做这套编辑体验；主要变化是编辑写入统一草稿、补充代理/引用状态和减少说明性文案。

左侧 Provider 卡片：id、启用状态、adapter 标签、凭据就绪。右侧编辑：

- 基础：名称/id、enabled、支持 adapter；
- 连接：base_url、凭据环境变量引用；
- 高级：实际 catalog 支持的字段；
- 被哪些模型引用：只读列表。

base_url 的文案明确为“API 地址，可为官方或转发地址”。出站 HTTP/SOCKS 代理是另一个传输概念；只有后端实际提供对应字段时出现，不能用 base_url 代替。

删除存在引用的 Provider 时展示引用清单并由整批校验处理；用户可在同一草稿里调整依赖。凭据就绪不表示已验证付费额度或远端连通。

### 11.3 模型库：family/collapsed

保留 ModelsSettingsPage 的对象详情、adapter 专属参数、Provider binding 编辑与新增对象流程。分簇/折叠主要改左侧对象目录；Provider 顺序以拖动块和键盘移动增强，不改成抽象的新流程向导。

顶部搜索、按能力筛选、“显示已折叠模型”开关、新增模型。中部按 family 分组，空 family 属于“未分组”；组头有数量和会话级展开开关。

普通模型默认可见，collapsed=true 的模型进入组内“已折叠 N 个”。搜索可以命中并临时展示折叠项。临时展开不修改后端 collapsed。

选中模型右侧表单：

- 基础：model id、family（现有簇选择 + 自由创建）、collapsed；
- Adapter 与能力：adapter、声明能力、context window；
- Provider Chain：有序行，每行选择 Provider 与 provider_model；
- 行为：adapter-specific thinking/reasoning、request_overrides；
- 被引用任务链。

把“折叠此模型”的保存纳入 ConfigDraft；标记不改变模型可用性或重试。组排序用确定规则和用户本地展开状态，不新增后端 family 调度表。

任务链中选中的折叠模型必须完整显示并附标记；历史模型任务不受折叠影响。避免旧模型从目录隐藏后变成不可理解的“未知 id”。

### 11.4 任务链

保留 TaskChainsSettingsPage 的对象列表、链详情和循环分配页签。任务链是可被复用的配置对象，不按名称推断用途或强制分成 Reflection 专用组；根据真实消费者显示“循环决策”“Action”“Home 检索”等引用，无引用的配置正常展示为“未发现内置引用”。右侧：

- 主要区：模型有序链，可拖拽、键盘移动、添加/移除；
- 概览区：候选数、所需能力、引用该链的调用位置；
- 调用参数：temperature、输出限制等实际可配置字段；
- 高级折叠：retry、Provider/Model switch wait、成功偏好与链轮询次数。

有序列表不用数值滑块。标量可用 slider + 数字框，最终仍接受精确值。Phase 强制的 answer_format/tool_use 规则标注为实际调用覆盖，不能让用户以为任务默认值总会生效。

### 11.5 循环分配与 Action 模型使用

循环分配仍编辑 loop.cycle.phase1_task_profile、phase2_task_profile，归任务链页。它们供 User 与 Reflection 的正常内核决策共同使用，不伪装成 Action。

建议把 LLM Action 默认链及 action.llm_action.overrides 的主要编辑入口迁到 Actions 的“模型使用”视图（Q-02）；保留实际存储和校验，不另建 UI 路由配置。顶部编辑共享默认链，左侧 domain/动作筛选，右侧按动作的实际模型用途显示继承来源、当前任务链、覆盖/恢复默认和模型顺序预览。修改链定义时跳回既有任务链详情；预览不复制模型链数据。

模型使用与可用性是同一 Action 的不同配置面，使用独立标签/分区。选择情景只影响可用性视图；当前 LLM 路由不支持情景覆盖，不能把同一个全局 override 伪装成三套 User/Home/Memory 配置。

现 ActionRoutingPanel 用 available 与 backend.kind 筛选候选，迁移后不能直接沿用为全部模型使用的判据。默认可以筛选可用动作，但已配置且当前情景不可用的动作仍可发现，并显示原因/生效情景，不能丢掉 Reflection 专属动作；能否编辑某个绑定由其真实配置契约决定。

不要只用 backend.kind 判定是否使用模型：home.top.search 是 native，但 Home owner 用固定 home_search Task 做可选重排；该项显示实际引用并跳转链定义，不提供当前不存在的 Action override。memory.write/home.review 是原生写入/审核，不放模型选择器。一个动作未来可有多个具名模型用途，不能简单给每个 Action 增加唯一 model 字段。

未来只有 owner 已实现且输入输出契约相容的用途，才显示“LLM 任务链/结构化判断”等执行方式选择。JEV 本轮仅预配置，不出现在可用的 Action 执行方式中。具体后端边界和扩展方案见后端 §5.7；不把 JEV 模型塞进 llm.tasks.models。

### 11.6 专用模型：用途 → 单模型 → Provider 链

此页按后端计划 §5 实施；真实 Embedding 用途绑定/Provider 链与 JEV 预配置已确认纳入本轮。前端排序控件必须对应真实路由配置，不能仅展示顺序。

专用模型区域沿用 LLM 的对象编辑习惯，导航按“Provider / 模型 / 用途”组织：先登记连接，再在模型详情选择并排序 Provider，最后由用途绑定模型。没有强制操作顺序，允许同一草稿补齐引用。通用 LLM 保留自己的任务链；两者共用对象列表、引用选择器、连接编辑器与有序列表组件，运行协议由后端各自拥有。

**用途页**

- 顶部 3 个分类页签：嵌入、结构化判断、生图；结构化判断可附 JEV 说明，但 kind 不是 jev。
- 左侧用途列表：名称、绑定模型、消费者摘要和状态。默认入口 embedding / decision / image_generation 来自 catalog。
- 中央编辑：用途 id、能力类型（创建后由约束决定可否改）、一个模型选择器；模型可搜索，按 kind 过滤。这里没有“添加后备模型”或任务 Model Chain。
- 选择器下方只读“接入顺序”预览，列出该模型 Provider bindings；编辑按钮跳转模型页并保留导航回溯。
- 下方“使用位置”：Memory 语义检索等真实 consumer_refs；点击到相应配置页。无消费者显示“已配置，尚未被 Agent 使用”。
- 尚无绑定显示“未配置模型”，提供创建同类模型并返回选中的流程，所有步骤只改同一 ConfigDraft。

**模型页**

左侧按能力分类的模型目录，右侧编辑 model id、kind、adapter、Provider Chain 与该能力适用选项。Provider 行含顺序号、Provider 选择、provider_model、凭据/代理就绪摘要、删除；拖动/上移/下移改变优先次序。Provider 的不同地址是同一逻辑模型的不同接入，不暗示更换成其他模型。

| 能力 | 主要字段与说明 | 页面不呈现的无关控件 |
|---|---|---|
| Embedding | dimensions、batch_size、timeout_seconds；Memory 引用；切接入可能重建缓存 | temperature、工具调用、LLM task 重试轮数 |
| 结构化判断 | TypeSafe System One adapter、模型名、超时；Choice/Score/Noul 能力说明 | 本轮不提供检索自动开关、具体 JEV Action 开关 |
| 生图 | 已注册协议的 Provider 映射及该协议真正支持的 options | 不猜所有 Provider 共用的 size/quality；不放无后端消费者的“生成”按钮 |

**Provider 页**

左侧 Provider 列表，可按支持协议筛选；右侧为 id、enabled、protocols、API 地址、凭据变量引用、有序引用（适用时）和高级 HTTP 代理环境变量引用。API 转发地址和出站代理分为两行，说明前者决定服务入口、后者决定如何连接。

“从通用 LLM Provider 复制连接”只复制地址/环境变量引用等共同字段到草稿，协议重新选择；不会制造跨目录联动。状态至少区分配置已保存、凭据就绪、运行协议已接入、被消费，不画一个含糊的绿色“已启用”。

**范围与状态**

Embedding 需要后端 B1b 真正迁移：Memory 页控制 embedding_use 是否为空，用途页控制绑定哪个模型，模型页控制 Provider 顺序。删除用途时显示 Memory 引用，允许同批修正。

JEV 可以预存配置但不启动 client，页面横幅“配置已保存；业务调用尚未接入”，隐藏测试调用/运行开关。生图若没有已注册 adapter，显示说明和后续接入需求；本次不接受任意 JSON 参数来假装支持。

专用模型配置通过 API-06/07，作为项目设置；不纳入目前的聊天运行方案，不随切换 LLM 推理方案而切换 Memory 向量空间。Web Search 仍在工具与连接下，沿 Web owner 的服务语义。

### 11.6.1 凭据页

这一页迁移现有 CredentialsSettingsPage 的有用能力，取消逐条 Apply。

- 顶栏：按变量名/引用对象搜索、新增变量、未配置筛选。
- 列表：变量名、配置状态、来源、引用者；默认不显示值。引用者可为 LLM、专用模型、Web、MCP/ACP 等实际 catalog 消费。
- 选中后：替换值输入框、显式删除、返回引用者；新增/替换/删除都进入全局 ConfigDraft。
- 未修改的遮罩不是新值；变量名错误就地提示；进程环境覆盖显示只读来源。保留变量名原样，不强制把合法名称改成大写。
- 底部使用同一“应用并重载”。与 Provider 一起创建的变量由后端在同一候选内验证和激活，失败一起撤回。
- 新输入值只保留内存；差异摘要显示“替换值”，清空/导出草稿不泄出它；方案保存不包含凭据值。


### 11.7 Turn 预算与 Context

Turn 预算页用三张卡：User、Home Reflection、Memory Reflection 的 max_cycles，说明耗尽后进入补额/中断交互。不是子 Agent 总额度。

Context 页布局：

- 顶部解释三个槽位与压缩目的的紧凑示意；
- 主要项：Session 背景容量、压缩触发/目标比例；
- 高级项：Trace chunk、branch factor、hot entries、inspect 容量、图像 byte 预算；
- 相关链接：到当前 Context 面板查看实际值。

比例采用关联双控件，确保 target < trigger；值域以 catalog/后端校验为准。字符、token、byte 单位明确分开，不编造一个覆盖所有模型的全局 Context token 上限。

### 11.8 Reflection 与 Actions

Reflection 页：时区、定时策略、当前来源可整理情况、执行预算链接；手动发起使用独立对话框，不把保存设置理解为立即开始 Reflection。

Reflection 不设独立模型链面板：Phase1/Phase2 来自循环分配，内部实际 LLM Action 来自通用默认/覆盖。生成内容发生在模型决策或真正的 LLM Action 中，不因 memory.write/home.review 在 Reflection 使用就把其 native 提交操作标为 LLM。任务名 memory_daily 当前仍在配置/枚举中，仓库未发现内置生产调用；不能凭名字把它呈现成当前 Memory Reflection 绑定，也不自动删除用户配置。

Actions 页建议保留 ActionCatalogSettingsPage 的 domain → Action → 详情结构，增加“行为与可用性 / 模型使用 / 高级”分区。可用性分区选择 User/Home Reflection/Memory Reflection；granted、supported、available、visibility、selection 与来源在必要位置披露，默认以“可用/不可用及原因”表达，不铺满机器字段。

用户调整的是现有允许配置，不能通过 UI 开关授予缺失写服务。领域默认、动作覆盖和情景覆盖清晰区分；无效显式启用在保存前/后端校验时反馈。

“模型使用”按实际依赖分三种：可配置路由、固定绑定（可跳转编辑所用链）、关联服务（链接到 owner 配置）。Memory Embedding 是共享检索服务用途，不能给每个调用它的动作复制一份 embedding 模型选择；非 Action 消费者仍留在自己的服务页。

### 11.9 工具与连接各页

| 子页 | 主要布局 |
|---|---|
| 执行环境 | Shell/工作目录语义说明、执行 limits、进程相关真实设置；不同于 Job 运行控制 |
| Web Search | 已实现搜索/抓取后端及参数，凭据引用与实际适用 Action |
| 资源处理 | 可用转换后端、读取/输出限制及依赖状态 |
| MCP | Server 列表 + stdio/Streamable HTTP 条件表单；env/header refs；工具选择；实际状态跳转运行观察 |
| ACP | 外部 Agent 目标列表 + command/args/env/env_refs 相关配置；连接限制；委派行为说明 |

切换 transport 隐藏不适用字段，并在草稿规范化中移除不属于该类型的旧字段。含点的 MCP tool 名作为完整对象 key 保存，不拆配置路径。细粒度字段必须来自当前 catalog；不从页面标题推断后端一定有该项。

### 11.10 数据与知识、系统

Workspace/Session/Home/Memory 四页分别配置 owner 的路径、容量、读取/索引等行为，顶部提供“查看内容”跳转。容量配置不会改变文件跨日归档语义。

系统页分为：Agent 运行/Endpoint 配置、观测保存、配置来源。本设备后端地址/项目选择放在本机连接管理，避免一个连接项有两个编辑归属。进程参数等只读项解释来源；环境/override 覆盖关系可查看，不能假装写入了进程环境。

“高级配置”仍使用 catalog 类型化字段/对象编辑，不提供把任意 JSON 发给后端的万能表单。

## 12. 运行方案管理页

左侧方案列表，中央详情。详情顶部名称、说明、当前匹配/已修改；下方 tabs 为模型、任务链、调用分配、预算、差异。

操作：从当前 active 保存、从 saved/当前草稿保存、重命名、明确覆盖快照、应用、删除。保存方案与应用配置有不同按钮；保存草稿为方案不会先把草稿写入正式配置文件。

保存弹窗：名称、说明、来源、预算组开关（默认包含）。模型/任务/路由必选，预算是整体组，不允许无说明地保存几个随机叶字段。详情明确列出 scope。

专用 models/uses/providers 保持项目级设置，不被运行方案快照或差异自动纳入。

budgets 包含 User/Home/Memory Reflection 的 Turn max_cycles、Session 背景容量及后端白名单 Context 压缩/披露参数；不包含凭据、路径、定时、授权或本地外观。

切换为完整范围替换，不是不断叠加。未包含预算的方案保留当前预算。Provider 定义共享，缺少引用时显示需要修复的项目，应用不能默默跳过。

删除当前关联方案只删除方案记录，不停止或还原 Agent。手动编辑配置后显示“方案名 · 已修改”。folded/family 是模型定义的一部分，跟随 models 快照，但不影响执行选取。

接口：API-06/07/08。具体请求结构按后端计划 §4。

## 13. 本机界面设置

| 分组 | 设置 |
|---|---|
| 外观 | 浅色/深色/跟随系统、正文与代码字体、字号、行距、紧凑/舒适密度 |
| 阅读 | 自动跟随新消息、动画/打字效果、代码换行、默认展开偏好 |
| 布局 | Inspector 宽度、导航展开、对话/资源视图偏好 |
| 提醒 | 待答/完成提示开关；系统通知在宿主支持并获用户开启后使用 |
| 连接管理 | 本设备项目/后端连接记录；凭据沿现有连接存储方式处理 |

使用前端本地版本化偏好存储，跨重启有效；普通视觉偏好设备级，面板选中/草稿按项目保存。不把字体写到后端 TOML，不因调节字号触发 config reload。

“恢复界面默认”仅重置本地偏好。“清除本地缓存”不删除后端 Session/知识/资源。

## 14. Markdown 与代码块扩展

### 14.1 公共渲染入口

对话、资源正文、Home/Memory、动作结果共用 MarkdownRenderer；通过 RenderContext 区分 read_only、compose、active_question 等真实用途。

CodeBlockRegistry 以 fence language 显式注册。组件职责分为 parse、render、source view、copy/export；renderer 通过有限回调返回用户意图，不直接取得 Agent 内核或任意 URL 执行能力。

流式 fence 尚未闭合时显示源码；完成且解析成功后渲染。解析错误在该块内展示错误和源码，不让整条消息消失。

### 14.2 本次内置能力

- 普通代码：语言标题、复制、换行、展开；
- tinysoul-question：同一 QuestionContent 表单，依据绑定决定 reply/compose/read_only；
- mermaid：图形/源码切换、缩放、适应窗口、SVG 导出；
- tikz：TikZJax 渲染模块按需加载，源码、错误、SVG 查看/导出；
- 数学继续使用现有 KaTeX。

流程图可由 mermaid fence 中的 flowchart 语法实现；不要把不同 flowchart.js 语法静默当作 Mermaid。如果未来确需独立 flowchart fence，应注册独立解析器。

图形内容、主题、renderer 版本作为缓存身份；未进入视口的重图形延迟渲染。TikZ 资源本地打包或由应用明确加载，不在每条消息插入远端任意脚本。

未来扩展通过代码注册增加 renderer，不引入第三方运行时代码市场。链接和交互按钮使用统一 ResourceRouter/InteractionBinding。

### 14.3 表单协议一致性

后端负责 core.ask 的归一化与身份，前端渲染正式 QuestionContent。普通回答 fence 在前端解析同一内容 schema，测试 fixture 两端共用示例。

协议只包括 question、options 的 id/label/description、allow_other；不含自定义 endpoint、事件脚本或自行生成的 question_id。未知字段给出有限协议提示。

## 15. 统一链接、路由与资源预览

ResourceRouter 输入“Link + 来源上下文”，输出类型化目标。先识别正式 Link，再处理普通相对资源链接和 HTTP(S)。不能让每个组件自己拼 URL。

| 来源 | 路由 |
|---|---|
| workspace: | Workspace owner，带 day；正文/图片/blob 使用正式端点 |
| home: top/resource/skill | Home 对应类型，带 effective/actual |
| memory: 持久 Link | Memory 文档 |
| memory:current/latest/target | 来源 Turn/日绑定解析；无绑定时提示选择来源，不打开任意当前文档 |
| session: / Trace ref | 原日 Session inspector 或活动 Turn Context inspector |
| HTTP(S) | 系统浏览器；Tauri 使用现有 opener |
| 相对资源 | 由当前 owner Link/文档位置解析，无法确定时显示文本/复制 |

前端内部路由建议：

- /chat?day=...&turn=...&view=conversation|map
- /workspace?day=...&link=...
- /home?view=effective|actual&link=...
- /memory?kind=...&day=...&link=...
- /activity?tab=jobs|acp|mcp|events&turn=...
- /settings?scope=agent|local&section=...

Tauri 可沿实际路由方案使用 hash，但页面使用稳定类型化导航对象，不能在业务组件里手拼字符串。

相同查看器支持预览和跳转主页面；后退返回原来位置。链接文本为友好名称，完整 Link 可复制；内部 HTTP 请求才附带认证，不将 token 放入模型 Markdown 或外部浏览器 URL。

内嵌浏览器及 Agent 浏览器控制属于后续独立能力，本次保留 ResourceRouter 扩展入口，不默认加载所有外站。

## 16. 页面与 Endpoint 对接矩阵

详细请求/响应和 owner 约束以配套后端计划同名 API 为准。

| 页面/组件 | Endpoint | API |
|---|---|---|
| 连接与全局状态 | GET /v2/health、/v2/status | 01 |
| Composer/队列 | POST /v2/turns；GET /v2/turns/{turn_id} | 02 |
| 追加/问题/预算/停止 | POST /v2/turns/{turn_id}/input、reply、grant、cancel | 03 |
| 活动消息 | GET /v2/turns/{turn_id}/interactions | 04 |
| 实时/Trace/模型详情 | GET /v2/events；WS /v2/events/ws；查询支持 turn_id/task_id/through | 05 |
| 设置 | GET /v2/config?view=saved或active、/catalog、/actions?scenario=... | 06 |
| 应用 | POST /v2/config/apply；已保存候选的显式 reload | 07 |
| 方案列表/详情/保存 | /v2/config/presets 及 /{id}；激活走 apply | 08 |
| 日期导航 | GET /v2/days | 09 |
| 历史/语义地图 | GET /v2/session/turns、/turns/{turn_id}、/map、/inspect | 10 |
| Context Inspector | GET /v2/turns/{turn_id}/context、/context/segments/{segment_id}、/context/inspect | 11 |
| Home | GET /v2/home/catalog、/content、/changes、/diff | 12 |
| Memory | GET /v2/memory/active、/catalog、/document；POST /v2/memory/search | 13 |
| Workspace | 现有 /v2/workspace/*；只读 GET 增加 day/有界读取 | 14 |
| Reflection | GET/POST /v2/reflection | 15 |
| Job 列表/详情/输出/停止 | /v2/turns/{turn_id}/jobs、/jobs/{job_id}、/output、/stop | 16 |
| ACP | GET /v2/subagent | 17 |
| MCP | GET /v2/expand/servers、/tools；POST /v2/expand/servers/{server_id}/refresh | 18 |
| 明确重启/控制 | POST /v2/restart、/v2/control | 19 |

不存在的接口在开发中通过显式 mock client 驱动 UI；生产界面显示能力未就绪，不偷偷退回 v1 或扫描本地文件。前端不直接调用 TypeSafe/LLM/MCP 供应商，也不持有其业务 API 密钥。

表中 Job 的详情、output、stop 均属于 /v2/turns/{turn_id}/jobs/{job_id} 路径；Session 的详情属于 /v2/session/turns/{turn_id}。新 DTO 的必要字段见后端计划附录 A，不能根据本文的简写实现全局 /jobs 或另一个 /turns 历史查询。

## 17. 实施顺序与清理

| 阶段 | 交付 | 后端依赖 | 状态 |
|---|---|---|---|
| F0 | 现状清理清单、类型契约、页面骨架、token 与 mock fixtures | B0 | pending |
| F1 | v2 client、连接、实体状态、事件接续、错误边界 | 01/02/05，B2 部分 | pending |
| F2 | 设置草稿/凭据、apply、模型 family/collapsed、运行方案、专用用途编辑器、输入旁选择 | B1；专用运行依赖 B1b | pending |
| F3 | 完整对话交互、问答表单、补额、队列、Session 历史 | B2/B3 | pending |
| F4 | Context/Map/Trace/LLM 详情、Action registry、Markdown 扩展 | B3/B6 | pending |
| F5 | Workspace 迁移、Home/Memory 页面、资源路由 | B4 | pending |
| F6 | Jobs/ACP/MCP/环境运行观察 | B5/B6 | pending |
| F7 | 跨页联调、性能/视觉验收、正式文档、删除旧代码 | B7 | pending |

前端开发范围为 visualization；后端缺口在 visualization/docs/demand 留下对应 API 编号，后端落地后关闭。两份计划的阶段可交错实施，不能以一个 mock 页面完成代替端到端功能完成。

需要移除/替换：

- src/api 的 v1 runtime/configuration/maintenance/workspace 路径；
- 旧 maintenance state 与类型；改用 Reflection 的正式语义；
- 旧 Workspace expected_digest/expected_revision/retention/mirror 假设；
- configStore 逐字段提交与“PATCH 即激活”提示；
- derive/chat 中基于字符串/事件缺失猜阶段与结果的分支；
- 为主聊天从头加载 mode=model 全量历史的路径；
- MessageStackView 的 label 推断排序；
- BackgroundDrawer 期待 background event 携带完整 Home 正文的逻辑；
- 仅为旧协议存在的兼容 aliases、状态复制和重复 renderer。

保留并迁移有价值的 Markdown、视觉原语、Action family 查看器、Workspace 编辑能力。清理前确认新的正常链路已承接相应功能，避免旧组件删除后遗漏用户交互。

## 18. 验证、性能与可访问性

### 18.1 契约与组件验证

- 每种共享机制用少量有区分力的 fixture：配置草稿/应用、方案替换、交互身份、Disclosure 分页、资源路由、Action fallback。
- API client 针对真实 DTO/error 测试，不用旧 events 造出不可能状态。
- 表单验证 choice/other、过期问题、预算同时存在、普通回答填入草稿。
- family/collapsed 验证搜索、选中项、已引用隐藏模型、历史模型记录。
- 不对字体文本/每个 catalog 项做冗余大快照；视觉 QA 用代表性截图。

### 18.2 端到端主线

1. 新 Turn → 追加 → ask → choice/other → grant → 完成 → 刷新/重连 → 历史完整。
2. 保存方案 → apply → 对话旁切换 → 真实模型/预算变化；运行中切换被明确阻止。
3. 跨设置页编辑 → 一个字段无效 → 整批未应用 → 修正成功；放弃本地草稿不改变后端。
4. Context 折叠 → inspect → 子 ref → UI 查看不改变模型 loaded/folding 状态。
5. Workspace 编辑/外部变化/Trash 恢复；日归档链接打开原资源。
6. Home overlay/diff → Reflection；Memory active/daily/持久引用与语义搜索。
7. ACP Job 输出和待答、MCP 首次显式发现、watcher 故障提示不阻止正式文件操作。
8. 历史观测正文缺失，正式 Session 对话仍可阅读。

### 18.3 性能设计与验收

- 首屏只请求当前必要摘要/一页历史；必须确认没有隐式全历史 model 请求。
- 大 JSON、长输出、图形依赖、模型消息按需加载；历史分页和列表虚拟化按实测规模启用。
- 事件按实体增量处理，不每条事件重新 derive 全日聊天。
- 快照失效按 owner/资源 key 合并，状态更新不触发每页重新 GET config。
- 测试定时器用可控时钟，等待条件用状态而不是固定 sleep；动画测试关闭。
- 记录代表性数据集（例如 200 个 Turn 摘要、2 万条保留观测、一个长 Job 输出）的首屏请求、渲染耗时、内存与大 chunk；给出实测再确定阈值，不在计划中编造性能数字。
- npm test、npm run build；Playwright 覆盖少量关键浏览器交互。桌面集成在可用 Tauri 环境验证连接、opener、文件导出。
- 本次仅撰写文档不运行功能门禁；实现完成须按项目 AGENTS 要求完成相关后端门禁和前端验证，并记录环境/结果。

### 18.4 视觉与交互检查

在 1440、1280、约 390 px 宽度及明/暗主题检查：对话进行中、待答、设置有变更、Home diff、Memory 文档、Job 输出。截图使用真实或契约一致 fixture。

键盘可达所有主操作，拖动有按钮替代；焦点返回来源，Esc 关闭详情不取消 Turn；中文输入法 Enter 不误发送；选项点击区域清楚。字号变化不遮挡固定 Composer，reduced-motion 关闭无限动画。

## 19. 文档与最终交付准则

实施期间更新 visualization/docs/design 的 connection、chat、settings、workspace、visual-system，并补充 context、knowledge、activity、rendering 的当前设计。设计文档不得把尚未实现的 endpoint 写成现状。

旧 demand：

- action execution started：在接入 action.execution 后归档；
- result content preview：按 B6 的展示片段核对；
- mounted skills：按 Task provenance 核对。

完成标准是各页面能通过正式后端契约闭环、旧路径被清除、UI 和 owner 语义一致、验证证据完整。不是“所有页面看起来有内容”或“测试数量达标”。

本计划实施状态始终按阶段更新；只有实现、文档和验证完成才更名 -done- 并归档。当前交付仅是两份详细执行计划，无前后端代码实现。

## 20. 外部能力参考

核对日期：2026-09-23。JEV 的 state + typed questions → structured answers 支持独立结构化判断分类；具体使用位置留待未来检索/Action 设计。

- [TypeSafe Quick start](https://docs.typesafe.ai/introduction/quickstart)
- [TypeSafe API](https://docs.typesafe.ai/api)
- [Mermaid Usage](https://mermaid.js.org/config/usage)
- [TikZJax](https://tikzjax.com/)

引入图形依赖时锁定已验证版本、核对打包与许可证，并在 Tauri/Web 两端验证。此处不承诺第三方任意 Markdown 插件都能直接运行。

## 21. 逐页布局、交互和接口交接规格

本节补足实施者不应自行猜测的页面细节，与前文的 owner/API 约束共同执行。页内对象选择进入类型化路由；暂时展开、滚动位置、列宽等是本机状态。未特别说明的查询采用首次加载骨架、保留已加载结果的局部刷新、面板内失败重试；不使用全屏转圈覆盖已有内容。

### P00. 连接与项目入口

| 区域 | 布局与内容 | 操作/数据 |
|---|---|---|
| 中央连接卡 | 产品标识、最近项目/后端、当前状态 | 本机连接记录；无连接也能进外观设置 |
| 桌面连接 | 项目根选择、发现结果、启动命令复制 | 复用 Tauri discover_backend；不自动启动第二个 Agent |
| 浏览器连接 | 地址/端口/连接凭据输入；最近连接选择 | 沿现有连接能力验证，不把本机项目路径当浏览器文件权限 |
| 状态说明 | 未发现、后端初始化、协议不支持、连接成功 | API-01；协议不支持不能退回旧 v1 |
| 失败区域 | 简短原因、重试、修改连接 | 保存输入；401 与后端业务失败分开 |

联动修改 src/api/connection.ts、useBackend.ts 和 Rust 连接描述消费。当前 browser fallback 固定 protocol_version=1 必须去掉，以连接描述及 /v2/status.protocol_version 为准；/v2/health 当前只有 ok，不能从它臆测协议版本；连接描述 schema_version 与 HTTP protocol_version 是不同概念，不能一起机械改为 2。

连接成功后落到 /chat 的当前日；读取最近页和活动 Turn，不先下载 model 级全量事件。关闭窗口只断开 UI。已有连接存储策略需统一实际代码与文档，不以此为由重建安全系统；新的分享/资源链接不携带连接 token。

### P01. 全局 Shell 与导航

保留现有 AppShell/NavRail/TopBar/StatusBar 及页面分区，NavRail 增加 Home、Memory，运行观察沿现有入口改进，底部仍是设置和连接。主对话不新增页面导航列；Workspace 保留树与编辑区。每项有图标和可访问名称；紧凑模式可显示 tooltip。

- 顶部保留产品/Agent 名称、必要运行与连接状态、右上 Context 入口；不增加当前日期/今天切换栏或口号。待答/补额可出现定位提示，不每个 Cycle 闪烁。
- 新日更新正式数据；仅在用户打开历史/归档视图时显示来源日，正在读归档页不被强制跳走。
- Inspector 一次一个，有标题、来源徽标、返回与关闭；内部查看 ref 可以后退，不在正文叠多层抽屉。
- 关闭 Inspector 保留主视图滚动；切换导航保留每页选择。关闭资源查看不停止执行，Esc 不等于 cancel。
- 中屏收起页面导航为抽屉；窄屏 Inspector 成全屏详情，顶部明确返回。主 Composer 不被虚拟键盘、底部草稿栏或 toast 挡住。

整体色彩使用现有背景层次与强调色；用户消息/Agent 输出/过程/待答靠版式和图标区分，避免每个 domain 都铺大块高饱和色。动效仅用于进入、展开和状态过渡，不让 waiting 看起来一直忙碌计算。

### P02. 对话：阅读、活动轮与输入

| 区域 | 默认布局 | 关键交互 |
|---|---|---|
| 历史入口（按需） | 沿现有历史控件/更多菜单打开日期与 Turn 列表，不常驻左栏 | API-09/10；归档只读，返回保持滚动 |
| 原 TopBar | 产品名、必要状态、右上 Context 按钮 | 当前 Context 只对活动 Turn；无日期/地图切换栏 |
| 主时间线 | User 输入 → Agent 过程/问题 → 用户补充/回复 → 输出 | API-04 或 API-10；正文按事实显示，不靠动画顺序决定事实 |
| 当前状态条 | 运行/等待原因、活动 Job 数、补额或定位问题 | API-01/02；只显示正式状态 |
| Composer | 引用 chips、输入框、发送模式、运行方案、发送/停止 | API-02/03/07/08；未发送草稿按 project 保存 |

默认采用当日连续对话时间线，Turn 标题/细分隔提供边界。最新完成输出不重复渲染为一个 Action 结果加一个回答气泡。core.reason 以“思考记录”折叠在过程区，实际工具调用有独立卡片，用户追加和问答永远在主线可见。

初次进入加载最新一页 Turn 摘要，并取可见 Turn 的正文；向上加载保持首个可见消息锚点。活动轮可以附在已加载历史后，不能因为历史尚未拉全把活动轮隐藏。跳转某个旧 Turn 只加载目标及必要邻近内容，不全量扫描当天事件。

发送流程：按 UI 明确模式创建新轮/追加/回复；提交中按钮去重，后端返回后放入正式实体。请求失败保留输入；不要本地伪造一个已被接受的气泡。一个正常 pending 气泡可显示“发送中”，随后由正式 input_id 替换。网络不确定时先刷新对应 Turn，不能自动重发导致重复事实。

选择“作为下一轮”时，排队区显示完整输入摘要和取消入口；queued 消息与 accepted 的当前输入样式区分。当前日切换由后端决定，提交回执的 day 才是事实。

当前 UserTurn 结束：用 turn_id 原位替换为 Session 正文来源，input_id/result_id 可用于锚点；无结果动作不用下标匹配。切换期间保留已知内容和“正在保存记录”提示，完成事实存在后才移除临时投影。完成但 Session 提交失败时显示实际失败，不声称历史已保存。

输入区引用：点击资源“引用到对话”只增一枚可删除 chip；实际发送展开为可读文本及 Link/来源日。拖入文件先上传 Workspace，完成后可引用；失败显示具体文件项，不发送空的“附件”承诺。

### P03. 待答、回复和预算卡

待答卡占 Agent 消息正文宽度，顶部问题图标/“等待你的回复”，正文 Markdown；选项为单选卡，视觉字母只做阅读辅助。默认“其他”展开多行输入。选中并不立即发请求，底部“提交回复”一次提交完整 answer。

状态顺序为未选择 → 已选择/已输入 → 提交中 → 已回复只读；事实表明已过期/取消时转为不可提交，保留原问题。两种提交均保存可理解文本，不能只显示一个无问题背景的“A”。

- core.ask：来源绑定 turn_id + question_id，走 API-03 reply。
- 普通 answer 代码块：没有活跃问题身份，按钮为“填入回复”；生成包含问题摘要与选项文本的草稿，不发 HTTP。
- 历史 ask：显示当时问题/完整选项/回复，折叠时保持选择关联。
- 自由提问没有 options：卡中直接给多行回复框；允许用户在 Composer 切换“仅补充信息”，该模式不能自动解除问题。

预算卡与待答卡分别显示：数值框（正整数 cycles）和“追加额度”、停止当前轮。建议默认增量从当前配置/真实 request 建议取，后端未给就要求用户填写，不发明无限预算按钮。预算和问题同时存在时，任何一个提交都不自动完成另一项。

待答通知绕过打字机效果。用户未在底部时出现“有新问题”定位条，不抢焦点；键盘焦点从提交按钮回到新状态说明或下一输入区。

### P04. Context 与 Session map

Context 的主入口是原 TopBar 右上按钮，复用并扩展 BackgroundDrawer；默认先显示三槽位段目录，不自动展开所有正文。也可全宽查看；不是主聊天的新页签。

| 层 | 布局 | 请求与行为 |
|---|---|---|
| 目录 | Background / Trace / Working 分组；段名称、必要状态与线索；技术详情按需展开 | API-11 overview；排序使用 descriptor.order |
| 段 | 顶栏来源/shape、已安装正文、根 ref、可用操作 | segment endpoint；有界分页保留原 message index |
| 披露 | ref 面包屑、content、children、related、sources、更多 | inspect；按钮沿 ref/continuation 读取，不调用 Action |
| 状态 | 捕获时点、当前已更新提示、刷新 | 新批次安装后提示可刷新，不每事件自动把用户读的位置重置 |

Home/Memory 段分“本轮已安装”与“浏览 owner 内容”入口；后者进入对应资源页。未加载 ref 点开只表示人正在读，标记为 UI 预览，不能点亮“模型已加载”。Working 采用状态表/卡片，Stack 显示时间/折叠枝，Heap 显示线索层，Map 显示关系与来源；renderer 注册基于 shape，语义专用内容由 owner 标识增强。

query 输入只在 capabilities 声明支持时出现，并标明检索范围；结果仍带 ref，点开沿相同披露路径继续。底部区分“还有页面”与“保留内容已截断”，不能无限加载一个实际不存在的下层。

Session map 从 Context → Session 进入，必要时全宽展开为独立详情层：左侧话题导航，中间关系列表/图形切换，选中项显示说明与来源。关闭回原 Context/聊天位置，不改主聊天的常态布局。已安装 Session 投影与完整 owner map 使用不同数据标签；共享节点只有一个身份，回路以关系呈现，不复制事实。

选择解释项先显示摘要、状态、成员/来源 refs，再按需拉来源 Turn；点事实打开主对话定位。列表用明确“事实”“整理线索”徽标，解释不装成用户原话。当前尚无解释时显示完整 Turn 时间线和“还没有整理线索”，而不是一张空白地图。没有人工编辑/拖拽提交图关系功能，浏览不触发 organize。

旧日 map 从原日 Session archive 读取；跨日切换清楚更新标题和 URL。Context 完成后显示“本轮 Context 已释放”，提供 Session 和历史模型请求入口，不从最新 Home/Memory 伪造旧 Context。

### P05. 过程与模型调用 Inspector

过程主视图以 Turn → Cycle → Phase 分层，当前分支展开，已完成分支只显示结果/耗时摘要。顶栏筛选动作、模型、事件和失败，所有筛选是查看行为，不影响 Agent。

点击 Action：卡头始终有动作 ID/人类可读意图、执行状态；正文 tab 为“结果 / 参数 / 关联 / 原始”。熟悉的动作 family 注册专用内容，未知动作可读 JSON fallback。Action 想要执行、已开始、未执行、未知结果不能统一显示完成打勾。

点击模型任务：概览 → 请求 → 工具与指导 → 响应 → 尝试五个 tab。请求默认按实际消息顺序，一行显示 role、index、来源段/TaskPrompt、字符量；点击展开内容。用户可切换按槽位分组，但原始 index 不变。尝试列表标记当次 model/provider 及失败，不把 fallback 合并成只有最终模型的一次调用。

- 只有选择 Task 时请求 API-05 model 正文，并固定 through 上界。
- model 请求并非流式 assistant 最终回答，不能逐帧灌到主对话。
- 无 usage/源段信息则省略相应量，不猜 token/成本。老观测没有 provenance 时标记来源未记录。
- 请求正文被淘汰时保留可用摘要，显示“超出保留范围”；不能用当前 Context 重建成“当时请求”。

图形、diff、大 JSON、stdout/stderr、Markdown 共用 rendering 基础组件；各 ActionRenderer 仅组合数据与导航。展示文案和色彩不绑定后端错误字符串全文。

### P06. Workspace

保留 WorkspaceView/WorkspaceTree/ResourceEditor/BinaryPreview 的两栏阅读编辑结构、Files/Trash 和既有交互。新增操作进入原工具区、菜单或资源信息折叠块；资源详情不强制变成常驻第三栏。归档选择放按需入口，只有选中归档时显示来源日与只读状态。

| 控件/行为 | 具体接口 | 返回后的更新 |
|---|---|---|
| 目录/标签浏览 | GET /v2/workspace/manifest?day=... | 更新该日树/列表，不清当前打开页签 |
| 正文/预览 | GET /v2/workspace/resource?link=...&day=...；blob | 更新该资源查看缓存 |
| 新建/完整保存文本 | PUT /v2/workspace/resource，link/text/overwrite | 更新资源与 manifest；编辑保存明确 overwrite=true |
| 新建目录 | POST /v2/workspace/directory，link | 更新树并选中目录 |
| 上传 | PUT /v2/workspace/blob，沿当前 upload wire 扩展必要状态 | 每文件进度与结果；成功后才生成资源引用 |
| 重命名/移动 | POST /v2/workspace/move，link/target_link | 跟随返回目标 Link 更新选择与标签页 |
| 标签 | PUT /v2/workspace/tags，link/tags | 更新对应列表项；不承诺生命周期改变 |
| 删除 | POST /v2/workspace/trash，link | 移入 Trash；关闭或标记原页签已移走 |
| Trash/恢复 | GET /v2/workspace/trash；POST /restore，trash_ref | 显示恢复结果，冲突按 owner 错误处理 |

本次编辑器“保存”以完整文本替换为主；append/edit API 供明确的追加/替换操作，不自行 diff 后拆成很多请求。当前没有 description 编辑端点就只读展示说明，不画不能保存的输入框。

文件树行：图标、名称、标签微标记；右键和行尾菜单提供同组操作。tmp 可按用户本地偏好折叠为筛选组，不假造物理 tmp 目录。列表可按名称/类型/大小排序，搜索未得到全文能力时明确为名称/目录筛选，不声称搜索所有文件正文。

文本查看默认预览；“编辑”打开源码与保存栏，保存成功去掉未保存标记。收到资源变化时，非编辑页可以刷新；已有草稿则保留并提示“文件已变化”，用户选择查看最新或继续保存。无 revision/CAS 弹窗。

归档日顶栏有醒目的只读标记，上传/新建/保存/移动/删除不可用；下载、复制 Link、引用仍可用。当前新日同名路径不能复用旧正文缓存。大二进制用正式 blob/Range 或下载，不通过前端本地任意路径读取。

### P07. Home

入口默认 effective Home。顶栏 actual/effective 切换、确定性搜索和“待整理变化”按钮；左栏分类来自 catalog，选中项 URL 带 link/view。

- 默认列表列为标题、类型、来源（actual/overlay）、变化标记；首次没有内容显示 owner 的空目录说明。
- 文档视图中央 Markdown，右侧小信息栏列 Link、Skill mount 信息、相关链接、“引用到对话”。当右 Inspector 已打开时并入同一面板。
- 变化视图是列表 + 选中 diff：创建绿色新增、删除红色删除、修改并排/统一切换；真实空 diff 不画伪装的更新。
- “模型已加载”只能在选定活动 Turn 的 API-11 中确认，未选活动 Turn 则不显示该标签。
- 页面只读，不把 Home Reflection 的受约束 review 操作复制成人工 accept/reject 按钮。

Home Reflection 弹窗包含说明输入、所选变化引用摘要、开始整理。先取 API-15 availability，允许提交后返回真实 queued/running；POST body.kind=home，instructions 放用户说明，其他字段遵循现有契约。窗口关闭后任务状态仍在运行观察页，完成再刷新变化与 effective/actual 内容。

### P08. Memory

左侧“活动记录”和“持久知识”分区；前者日期目录，后者 daily/entity/concept/fact/note。默认进入当日活动 Memory.md，顶部提示它会随日归档且不是 daily 持久文档。

主区顶部搜索，文本/语义分段选择；下方搜索列表或文档。文档右侧是出链/反链/来源和重定向提示，数量多时局部分页；点击来源走 ResourceRouter。

- 文本/目录筛选走 API-13 catalog，不产生向量请求。
- 显式点击语义搜索发 POST search；输入变化不逐字调用模型。结果显示 mode_used 与降级说明，不把 lexical 结果伪装成向量结果。
- 未启用向量检索时给出“配置语义检索”链接到 Memory 设置，并能继续文本检索。B1b 实施后该设置选择 embedding_use。
- 日期筛选对活动/归档 Memory 与 daily 列表含义各自标明；持久知识没有全库历史版本快照。
- 无活动内容、无知识条目、无搜索命中分别有明确空态；有损坏文档时仅该条显示读取错误，不使整个知识页面失效。

“整理记忆”弹窗先读 Reflection availability，选 target_day、输入可选 instructions，显示已有 daily 可再次整理；POST body.kind=memory。选择某条文档可以把其 Link 放进说明，不能绕过 Reflection 新建持久写 API。

### P09. 运行观察

| Tab | 左/中区 | Inspector 与操作 | 数据 |
|---|---|---|---|
| 执行 | active/queued/保留结果分区；类型、日、状态、等待原因 | 跳转对话/过程；等待补额；取消指定 Turn | API-01/02/03 |
| Jobs | 按当前或所选 Turn 筛选；类型、摘要、状态、待答 | stdout/stderr 或 ACP 文本、产物、stop；自动跟随可关 | API-16 |
| ACP | 目标列表和连接池分别展示 | 连接 cwd/关联 Job；“让 Agent 使用”填 Composer | API-17 |
| MCP | Server 列表 → 已发现 Tool 列表 | schema、允许状态、最近调用；显式刷新 | API-18 |
| 环境/观测 | source/topic/等级/Turn 筛选；分页事件 | 有界 JSON；当前 watcher 说明；范围导出 | API-01/05 |

输出 cursor 按 Job 和通道 owner 定义接续；前端不自行把 stdout/stderr 排成精确全序。离开详情停止输出轮询/订阅，Job 本身继续运行。Jobs 搜索只搜索已知元信息，不倒扫所有历史大输出。

ACP 目标未连接是正常空态；跨 Turn 空闲连接显示“空闲”，没有 Job 时不显示虚假的进度条。外部 Agent 目标配置不提供页面直接 delegate；用户意图送回同一个主 Agent。

MCP 初始“尚未发现工具”与“发现到 0 个工具”分开；只有用户点击刷新才调用 POST refresh。失败显示最后已知目录并标注状态，不编造一次本地成功发现。工具允许状态的修改进入设置草稿。

环境列表不是主对话消息；正式用户追加、Agent 提问和回复仍在主对话。watcher 故障只影响来源徽标，Workspace 正式编辑按钮继续可用。

### P10. 设置公共框架与差异页

设置分 Agent/本机界面。Agent 左侧导航分组，右侧每页有标题、主要字段、高级折叠；不要求每页固定一段用途小字。必要帮助就近按需展开，技术 key 放高级说明。变更计数和应用栏固定在页面底部，内容区留出同等高度。

ConfigDraft 只有一份：以读取的 saved 为基线，记录规范 mutations；字段错误按 source/path 定位，collection 对象内部的显示位置可由编辑器映射。跨子页草稿不丢失。运行中仍允许编辑草稿，apply 按 activity.can_reload 禁用并解释；不能沿旧 can_write 提示把所有控件锁死。

| 用户操作 | 页面行为 | 后端调用 |
|---|---|---|
| 修改字段/拖动顺序/新增对象 | 就地更新草稿和变更数 | 无 |
| 重置此页 | 移除该页拥有字段的本地 mutations | 无；共享字段只属于一个主编辑页 |
| 放弃全部 | 回到 saved 基线 | 无 |
| 查看差异 | 展示 active→saved 与 saved→draft；敏感值只显示操作 | 已有快照；必要时显式刷新 |
| 应用并重载 | 显示整批进度，禁重复点击 | API-07 apply(operations) |
| 保存为方案 | 选择来源与预算范围，显示被排除修改 | API-08 capture；不先 PATCH |
| 应用失败 | 保留草稿，字段定位或页面摘要 | 重新核对实际状态；不反向补偿 PATCH |

新增对象默认聚焦 id，确认后进入草稿列表；必须允许同一草稿先建模型再补 Provider，最终应用时做整批引用校验。删除显示引用清单和仍未解决的问题，不要求用户按“先删任务再删模型”的特定点击顺序；列表项在草稿中保留待删除标记便于恢复。

为避免刷新丢修改，刷新按钮只更新后端基线/状态并标注与草稿冲突的实际字段；不无声覆盖。此处不建设多人版本合并/CAS；冲突时给“保留我的草稿”或“放弃后重新读取”的清楚选择即可。

### P11. 设置各页的字段布局与实际配置映射

以下 key 以当前检出的 catalog 为据（自 f496508 至 10b43c9 未变）；标“新增”的字段须后端实现后接入。页面分组可以调整，唯一字段只有一个主要编辑入口，其它页用链接或摘要引用。

| 页面 | 默认展开的主要区 | 高级区/引用 | 字段 owner/接口 |
|---|---|---|---|
| 配置概览 | 正在运行方案、active/saved 状态、模型与预算摘要 | 待生效变更、来源问题 | API-06/08，禁止自动远程 probe |
| LLM Provider | id/enabled/adapters/base_url/api_key_envs | 新增 proxy_env、被哪些模型引用 | llm.providers.*，API-06/07 |
| LLM 模型库 | family 分组、collapsed、adapter、context window、Provider 顺序 | capabilities、adapter_options、request_overrides、引用 | llm.models.*；family/collapsed 新增 |
| 任务链 | models 顺序、任务说明、引用位置 | 输出参数、重试等待/次数/成功偏好 | llm.tasks.*；不是 Turn 预算 |
| 循环分配（任务链页内） | Phase1/Phase2 | 实际 Task 调用覆盖说明 | loop.cycle.*_task_profile |
| 专用用途/模型/Provider | §11.6 的三页布局 | 实际消费、代理和按 kind options | infra.model_services，B1b |
| 凭据 | 变量状态/引用/替换或新增 | 来源覆盖、待删除 | dotenv source；同一 API-07 |
| Turn 预算 | User/Home Reflection/Memory Reflection 三卡 | jobs 容量跳转运行限制，不与 cycles 混合 | loop.user.max_cycles、reflection.*.max_cycles |
| Context | Session background 容量、触发/目标比例 | 图像预算、trace 披露/折叠；system_text/journal 独立高级区 | context.*、session.background_max_chars |
| Reflection | schedule.enabled、daily_time、timezone | 来源 availability、预算页链接、archive_root 只在路径高级区 | reflection.*，API-15 查询/发起 |
| Actions（Q-02 建议） | 行为与可用性；模型使用含默认链/Action override/继承来源 | 固定引用、关联服务、局部 timeout | API-06 actions + action catalog document set；模型路由仍为 action.llm_action.* |
| 执行环境 | execution.enabled、解释器 enabled/executable、运行时限 | 输出/脚本/命令/参数容量；Job 并发与保留 | execution.*、jobs.per_turn_live_capacity/retained_capacity |
| Web Search | Kimi 搜索连接/启用/凭据；搜索与页面抓取分卡 | discover_pages 遍历容量/并发，fetch 开关、字节/文本限制 | capabilities.web.*；不搬进 llm.tasks |
| 资源处理 | MarkItDown/PyPDF 启用、格式与提取选项 | PDF 页数、图片/附件总量、输入输出限制 | capabilities.resource.* |
| MCP | Server 列表、transport、连接字段、工具默认/override | 总量/分页/超时；查看运行目录 | capabilities.expand.*；API-18 |
| ACP | 目标 id/description/command/args/env/env_refs/auto_approve | max_connections、连接/运行/停止时间、输出限制 | capabilities.subagent.*；API-17 |
| Workspace | watcher.enabled/debounce_ms、ignore_dirs、文件/读写容量 | 搜索/分析限制、root | workspace.*；root 不代表前端本地路径 |
| Session | inspect_max_chars、归档语义说明 | root；背景预算跳转 Context 页 | session.*；不重复放两个 background 编辑器 |
| Home | 读写/Skill catalog 容量、搜索候选与摘要 | root/runtime_root，跳转内容页 | home.* |
| Memory | max_active_chars、文档类型容量、检索设置 | cache 容量/redirect hops/root；新增 embedding_use 选择 | memory.*；不把向量凭据再次复制到此页 |
| Agent 运行/观测 | interactive、retained_outcomes、output.mode/model_max_chars | 终端命令集合；Endpoint 只展示实际已注册配置 | agent.*；实际进程只读设置不能伪编辑 |
| 配置来源与高级项 | source 顺序、可写性、覆盖链 | include/env_file/document_sets 类型化编辑 | config.*；当前 catalog 未暴露者不发未知 mutation |

Task Chain 和 Provider Chain 都采用编号有序行、拖拽手柄、键盘上移/下移、移除和搜索添加；标量比例/有限数值才采用 slider + 数字输入。很多字段没有天然小范围，直接数字输入更清晰，不强加 slider。

模型编辑器的 thinking/reasoning 根据 adapter schema 显示，字段单位/默认/支持范围均来自 catalog。折叠模型在所有引用选择器里仍能搜到；group 折叠是本机 UI 状态，model.collapsed 修改属于配置草稿，两者文字区分。

MCP transport 表单：stdio 展示 command/args/cwd/env/env_refs；Streamable HTTP 展示 url/headers/header_refs；切换类型后清理不适用草稿字段。ACP 当前目标 catalog 没有 cwd 字段，设置页不得复制 MCP 的 cwd 输入；实际连接 cwd 在运行观察只读显示。

### P12. 运行方案详情与 Composer 选择器

方案管理页左侧名称列表，默认选正在关联的方案，否则选首项；无方案提供“从当前配置保存”。右侧头部名称/说明、当前匹配/已修改，内容 tab 为模型、任务链、调用分配、预算、差异。

保存弹窗字段：名称、说明、来源 active/saved/当前草稿、包含预算（默认选）；模型/任务/路由固定包含。显示排除的凭据、专用服务、路径、定时等变更，避免用户以为保存了完整项目配置。Provider definitions 是共享引用，详细列表显示引用缺失；不导出密钥。

操作分清：重命名只改元数据；“用当前配置覆盖方案”需要选择来源，才更新 snapshot；“应用方案”切实际 generation；删除不撤销运行中的配置。应用方案与未保存 ConfigDraft 冲突时，提示先保存为方案/放弃/返回，不偷偷合并两份互斥操作。

Composer Popover 采用紧凑同一数据源：列表名称 + Phase1/Phase2 简述 + 预算徽标；选中项勾标只在 apply 成功后移动。活动/等待/排队期间仍能看详情但应用不可用，消息草稿不丢。模型簇/推理强度属于方案详情，不再追加一个覆盖所有任务的独立全局控件。

### P13. 本机界面设置

采用三列以内的设置卡并带小型实时样例：

- 外观：浅/深/跟随系统；应用于根主题 token。字体选择展示中文与代码样例，字号滑块旁有数值和恢复按钮。
- 阅读：正文行距/代码换行/舒适密度；自动跟随新消息、动画；减少动态效果遵循系统偏好且允许更保守。
- 布局：Inspector 宽度、默认导航展开、面板默认 tab；“恢复布局”不清对话缓存或草稿。
- 通知：待答、完成提示；宿主不支持时解释，不增加后台轮询运行器。
- 连接：最近项目、后端地址、重新发现/连接；与 Agent Endpoint 服务端配置分开。

本机设置即改即用，底部写“仅影响本设备”；不出现 Agent 的应用并重载栏。断线也可改。恢复默认分别作用外观/布局/所有本机偏好，不能误删远端知识、方案或 workspace。

### P14. 通用资源预览与 Markdown 扩展

任何页面的内部资源 Link 点击行为一致：普通点击进入右侧预览，预览头部“在页面中打开”导航到 owner 页面；在资源主列表点击则直接切主阅读区。外部网页点击使用系统浏览器；来源不明确的相对链接提供复制/说明，不能拼一个猜测的 owner 路径。

Preview Header：资源图标、标题、owner、日期或 view 标签、复制 Link、在页面打开、关闭。正文复用 Markdown/图片/代码/二进制查看器；来源信息由 ResourceLocator 传入渲染上下文，相对链接/动态 Memory 引用据此解析。

代码块公共头部：类型、源码/渲染切换、复制、支持时导出。未闭合/解析失败回到源码；Mermaid/TikZ 按需加载，错误只影响该块。tinysoul-question 使用 P03 的三种绑定模式；renderer 不自己猜当前等待问题。

新增 renderer 的交接约束：有一个显式注册条目、输入解析类型、只读默认行为、来源上下文、错误 fallback 和一个代表性 fixture；无需为每种 fence 写独立 store、HTTP 路由或插件运行器。

## 22. 实施交接：替换位置、依赖和验收产物

### 22.1 按现有代码拆分工作，不建设并行前端

| 现有位置 | 保留价值 | 本轮改造/删除 |
|---|---|---|
| src/App.tsx、components/shell/AppShell.tsx | 主题接入、壳与视觉组件 | 组装统一导航/页面；连接入口不再受旧维护弹窗控制 |
| src/api/connection.ts、hooks/useBackend.ts、src-tauri/src/lib.rs | 实例发现、身份和宿主功能 | v2、初始化/断线状态、快照重建；区分 schema/protocol 版本 |
| src/api/transport.ts、tinysoul.ts、runtime.ts | 认证、HTTP 错误与 client 组织 | 更新真实 v2 schemas；不要在页面里直接 fetch |
| src/api/events.ts、history.ts、exportTrace.ts | WS 及导出交互 | 正式 Session 历史替代事件历史拼接；定向 Observation 导出标范围 |
| src/store/appStore.ts、derive/chat 相关代码 | UI 选择、现有 selector | 拆来源实体与本机状态；删除 v1 阶段猜测/整日反复 derive |
| src/store/configStore.ts | catalog/配置读取与表单配合 | 唯一 ConfigDraft、active/saved、整批 apply；删除逐项写入 |
| features/settings/SettingsPage、Navigation、model.ts | 页面导航和 catalog 映射 | 新导航/搜索/主字段归属；不按旧 surface 平铺负载 |
| Providers/Models/TaskChains | 保留对象列表—详情、adapter 参数、链定义/循环分配的页面逻辑 | 配置只写草稿；分簇/折叠、引用反查、拖动与键盘排序 |
| ActionCatalogSettingsPage/ActionRoutingPanel | 保留 domain/Action 详情与真实 default/override 语义 | Q-02：模型路由编辑归入 Actions；任务链旧入口跳转，不保留两个编辑器 |
| ChatView/TurnView/LiveStatus/Composer | 保留单列布局、阅读宽度、滚动锚点、过程折叠、回答动效、输入区 | 按正式事实穿插提问/回复/补充，新增预算/方案控件；不按预览重做布局 |
| CredentialsSettingsPage | 变量引用与输入交互 | 合并 draft/receipt，删除 Credentials active 的错误提示 |
| Infrastructure/ConfigSettingsPage/ConfigFieldRow | 类型化通用字段 | 用于高级/次要字段；不要替代用途/任务链等有意图的专用页 |
| BackgroundDrawer、MessageStackView | 抽屉/消息栈查看原语 | 接 Context descriptor/provenance；删除按 label 猜槽位和事件拼 Home |
| src/components/markdown/Markdown.tsx | Markdown/KaTeX/代码显示 | 公共 ResourceRouter、CodeBlockRegistry、统一 RenderContext |
| 原 Workspace 组件/hooks/API | 两栏、Files/Trash、树、预览、文本编辑、上传 | 保持主要布局补功能；v2 owner 操作/归档身份；删除 digest/revision/retention/mirror |
| src/api/maintenance.ts、维护 types/store/dialog | 可复用弹窗外观 | 删除旧业务状态；发起 Reflection 使用正式 API-15 |

新目录名称按 §3.2；每个切面切换完成后清掉被替换的旧数据入口。允许实施分阶段使用契约 fixture，但在生产 client 中不留 mock fallback 或 v1 自动回退。

### 22.2 分阶段可审查产物

| 阶段 | 进入条件 | 必须交付的具体产物 | 离开条件 |
|---|---|---|---|
| F0 | 两份 r4 已读，区分已确认范围与 Q-02 建议 | v2 types/API client 草图、P00～P14 路由、共享 DTO fixtures、原版视觉/交互保留清单、旧数据路径清单 | 每页主要操作能对应 API/owner；尚缺契约有编号 |
| F1 | health/status/Turn/event 契约可用 | 连接页、Shell、Session/活动态实体、WS gap 和重连 | 刷新页面能找回正式对话/执行；不拉全部 model 日志 |
| F2 | B1；专用模型需 B1b | 所有设置子页、凭据整批草稿、差异、方案与 Composer picker | 一次混合编辑成功/失败闭环；family/collapsed 不改可用性 |
| F3 | B2/B3 | 连续对话、追加/排队/ask/回复/预算、活动到 Session 切换 | 代表性长 Turn 的全部交互刷新后仍可见，无双重正文 |
| F4 | B3/B6 | Context 披露、Session map、Trace/Task、Action registry、代码块 | UI inspect 不改变 Context；原始消息顺序/来源准确 |
| F5 | B4 | Workspace 全操作、Home/Memory、Reflection 弹窗、ResourceRouter | 原日链接正确，知识读取与 Reflection 提交分清 |
| F6 | B5/B6 | 运行观察全部 tabs、输出分页、ACP 池、MCP 刷新、watcher | 只读页无隐式协议连接；Job 输出与父 Agent 待答统一 |
| F7 | 各主线真实端点闭环 | 视觉/窄屏/桌面验证、文档同步、旧代码清理记录 | 实现、协议、测试证据逐项完成才标 done |

F2 专用范围可以独立于 F3～F6 推进，不能因为一个未来 JEV Action 未实现阻塞本次对话/资源功能。各阶段组件可分工开发，但在未接正式端点前只能标 UI/mock_ready，不能标业务 done。

### 22.3 共享数据流与更新规则

采用现有 Zustand 的明确 slice/selector 即可，不为了重构另引入第二套大型状态框架。每种数据只有一个归属：

- connection/local preferences：设备；chat/settings/editor drafts：project；完成 Session：project + day；活动 Context：instance + generation + turn；Observation：instance + sequence；资源正文：locator + 必要 view/day。
- 事件处理先按 (instance_id, sequence) 去重，再更新轻量执行实体或失效 owner 查询；不把原始事件当所有页面的主数据库。
- owner 查询保留 request key，用户切 day/对象后旧请求返回不能覆盖新选择。这是正确的组件生命周期，不引入后端 revision。
- UI optimistic state 仅限草稿、展开/选择、提交中。已接受输入、配置生效、知识提交与执行成功必须等正式结果。
- Query 返回失败只更新该实体错误；未知 Action payload 落通用 renderer，不能触发重新建立整个连接。

事件/查询映射与后端计划附录 B.3 同步。发生状态变化但缺少事件时，补明确 invalidation 观测，或在页面聚焦/命令返回时查询；不用持续刷新所有模块补洞。

### 22.4 设计验收场景

每项用真实端点或严格按目标契约构造 fixture 走一遍，避免只给静态“有数据”截图：

1. 今天已有对话，当前轮运行且用户连续追加；其中一条刚接受未安装。刷新后位置和状态可解释。
2. ask 有选项且同时需要补预算，用户选“其他”；问题、回复、补额各自保留，不相互覆盖。
3. 无地图整理线索的 Session、有共享节点/回路的 Session、归档日 Session 三种视图。
4. 当前 Home 已有新修改但活动 Context 尚未刷新；两个入口准确显示不同来源。
5. 打开旧模型调用，其真实请求部分超出保留范围；仍能阅读 Session 对话。
6. 设置同时新建 Provider、替换凭据、重排任务链、改预算，一处字段错误；整批未激活，所有草稿可继续编辑或放弃。
7. 旧模型 collapsed=true，但任务链引用它；选择器/历史调用仍可看懂。
8. 配置 Embedding 第二 Provider；前端显示真实顺序和索引切换说明；JEV 已配置却显示未被消费。
9. Workspace 外部改动时有未保存编辑；归档同名文件；上传失败其中一件；各状态独立且内容不串日。
10. Home diff 发起 Reflection、Memory source_day/target_day 的整理，显示排队状态而非假完成。
11. ACP 空闲跨轮连接、正在执行 Job、有父 Agent 待答；MCP 尚未发现工具与发现失败区别清楚。
12. 一个普通回答带提问 fence、Mermaid、TikZ 和内部/外部链接；表单只填草稿，未知 fence 保留源码。

视觉样例应覆盖加载/空态/失败/等待/已完成各至少一种，并使用同一 typography、状态色、圆角/层级和动效节奏。测试优先验证这些有区别的行为，不为所有字段生成重复快照。

## 23. 需求覆盖复核与已确认边界

| 用户需求 | 当前计划的实际承接 | 后端依赖 | 判断 |
|---|---|---|---|
| 1. 接最新重构 | v2/正式 owner 快照/Reflection/单根执行；P00～P05 | B0/B2/B3 | 可行；必须清掉 v1 推断 |
| 2. 整体重做设置 | 新导航、主次字段、顺序控件、全局草稿/凭据/应用差异；P10/P11 | B1 | 已覆盖 |
| 3. 本机与后端分开 | scope 切换、本机即时预览、项目配置 apply；P13 | 既有配置 + B1 | 已覆盖 |
| 4. 运行方案 | backend 保存、明确 scope、Composer 选择；P12 | B1/API-08 | 已确认；含可选 Context/Turn 预算 |
| 5. Context/Memory/Home/Map | 三槽位/四形状/披露/来源区别；P04/P05 | B3/B6 | 不复制 Context 状态 |
| 6. Action 美观展示 | 明确矩阵、registry、历史 preview/provenance；P05 | B6 | 未知动作有正常 fallback |
| 7. ACP/MCP/Job/环境 | 运行观察五 tabs、连接池/输出/显式发现；P09 | B5/B6 | 复用同一调度与连接 owner |
| 8. 追加/提问/回复/代码块 | P02/P03/P14；正式 typed reply 与普通填稿区别 | B2 | 协议和渲染同源 |
| 9. Memory/Home 新页 | P07/P08；当前/归档/持久、Reflection | B4/API-15 | 不增持久知识直写渠道 |
| 10. 通用链接 | ResourceRouter/Locator、日期与 view、预览/主页面 | B3/B4 | 不拼物理路径 |
| 11. 其他完善 | 连接、凭据、搜索/空态/重连/性能、接口交接 | 各阶段 | 在本轮真实消费者范围内 |
| 12. 视觉延续与两份计划 | Luminous tokens、响应式、逐页规格、分工/验收 | 文档与实现 QA | 不以换框架代替设计 |
| 补充：模型簇/折叠 | model.family/collapsed，目录分组但不影响调用 | B1 | 已确认 |
| 补充：专用用途/Provider 链 | §11.6、后端 §5；单模型与 Provider 链 | B1b | 已确认，纳入本轮实施 |

复核结论：目标架构可行，接口按 owner 的公开窄服务扩展，前端依事实/视图分层组织，没有需要再造 Loop、Context 或知识存储的理由。最大的实施风险是保留旧事件推导/v1/逐项配置写入，再在其上堆新页面；F1/F2 的数据流替换必须作为后续页面基础。

新增范围 Q-01 已确认：本轮迁移真实 Embedding 用途/Provider 链，并支持保存 JEV 预配置；B1b/F2 专用配置是正式交付项。实际 JEV 检索/Action、生图调用随后设计。r4 新增 Q-02 仅讨论 Action 模型使用编辑入口与真实依赖描述，不撤回前述确认。
具体 JEV 作用于哪种检索、选择哪些生图服务商、是否以后把专用用途纳入运行方案，均是后续功能决策，不阻塞已确认的本轮页面与接口工作。运行方案本轮仍只管理已确认范围。

本次交付版本为 20260924-r4，文件名带 r4，替代 r3 设计稿。当前交付是完整设计与执行计划；各 pending 标记表示尚待代码实施，Q-02 的 proposed 表示新增设计建议尚待确认，不能混为已经实施或既有范围待确认。


## 24. r4 界面改动范围与验收依据

本轮只进行文字设计和计划修订，没有制作新预览。r3 预览为历史交流材料，不能以其多栏聊天、日期切换栏、常驻技术小字或页面口号替换原版。它已经验证过的演示交互不作为生产功能验收证据。

| 范围 | 正式实施基准 | 需要改进 |
|---|---|---|
| 全局视觉 | 原 styles/index.css 的 Luminous 与 utils/motion.ts | 新状态/组件纳入原 token、领域色、光泽和动效；去除装饰说明串 |
| 对话 | 原 ChatView/TurnView/Composer 的主布局、滚动与呈现节奏 | 事实顺序、提问/回复/追加/预算、紧凑方案选择；右上 Context 扩展 |
| Workspace | 原 Files/Trash、树、预览/编辑两栏 | 正式 v2 操作、标签、归档、上传、链接和状态，去旧 revision/digest 交互 |
| 设置 | 重新组织导航、页面负载、整批草稿和本机设置 | 保留 Provider/模型/TaskChain 编辑逻辑；拖拽顺序、模型簇与专用模型 |
| Home / Memory | 新页面规格 P07/P08 | 延续同一视觉语汇，内容与来源为主，Reflection 操作入口清楚 |
| 运行观察 | 既定 P09 布局 | 接真实 Turn/Job/ACP/MCP/事件，不添加产品口号 |

设置仍按六组组织，仅展开当前组：概览与方案、模型与服务、行为与上下文、工具与连接、数据与知识、系统与诊断。类别控制查找方式，跨页共用 ConfigDraft；本机偏好独立即时生效。

F0 在原版上记录保留项，F3/F5 验收对话/Workspace 的布局与成熟交互是否连续，F7 检查：常态无新增聊天日期栏/话题侧栏；Context 统一由右上打开；没有口号或装饰性“·”小字串；提问和回复即时可见；新页与旧页的光泽、颜色和动效一致。不要用测试固化某一个像素数或每句话文本，按代表性页面人工对照与行为测试验证。

数据适配仍必须彻底：保留成熟视觉组件不等于保留 v1、旧维护状态、事件拼接对话或逐条配置提交。对应删除清单见 §17/22。

## 25. 新增设计建议 Q-02 与后续扩展

Q-02（proposed）：Actions 页作为单动作模型使用的主要编辑入口，任务链页保留链定义/循环分配，并通过旧 Action Routing 入口跳转；后端 API-06 提供实际消费者的窄描述，沿现有 ConfigDraft/API-07 写配置。

这一建议使用户先选动作，再看到该动作真正使用的模型能力；资源配置仍在 Provider/模型/任务链页。一个动作可有多个用途，选择器只出现在已支持的位置。当前固定 Home 重排引用只读跳转；Memory 的共享 Embedding 引用不拆成多个 Action 私有副本。

确认 Q-02 不等于确认任何 Action 可以使用任意模型，也不扩展 JEV 本轮实施范围。未来存在相容的业务实现时，可在用途下选择“LLM 任务链”或“结构化判断”，并显示各自的配置选择器；原生提交动作不需要模型，Phase1/Phase2 留在循环分配。对应真实契约、单一配置来源和运行方案边界详见后端 §5.7。

本次已经按用户明确意见修改的是布局保留、产品文案、Context 入口和原模型配置体验；只将新增的 Q-02 组织建议保留为讨论点，不重新询问已确认的 Embedding/JEV 预配置或写入边界。

后续 Q-03 将此问题继续推进到后端实现结构，详见文首架构提案。在其确认前，不能一面采用新的模型用途 UI，一面自行保留/发明两份 action.llm_action 与 action.models 生效配置。确认后前后端一次确定目标来源及迁移；JEV 实际调用仍需明确业务范围。
