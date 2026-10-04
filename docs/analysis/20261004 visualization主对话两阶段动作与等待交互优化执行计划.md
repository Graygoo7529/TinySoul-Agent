# visualization 主对话两阶段动作与等待交互优化执行计划

状态：待讨论确认

日期：2026-10-04

基线：`c479ca0` 的主对话视觉与动效语义；`35f1440` 之后的 v2 接口；当前工作树的 visualization 实现

关联规约：`AGENTS.md`、`docs/design/` 中关于 Turn/Cycle/Phase、Action、Observation、Context 和渐进披露的当前定义

## 1. 目标与判断

本次工作以恢复和延续 `c479ca0` 的设计语义为基线，而不是重新制作一套页面。当前实现已经保留了原版较重要的质感：深色/浅色表面层次、LiveStatus 的运行扫光、阶段时间线、输入区域的动效、回答结果的收束动画，以及当前右侧 Action 详情面板的独立阅读方式。后续改动应在这些稳定行为上做小步、可验证的增强。

主要目标有四个：

1. 让 Stage2 的 action plan 和 Stage3 的 action result 在视觉和语义上明确分开，同时让预览卡片能够表达真实执行信息；保留右侧详情抽屉作为完整核查入口。
2. 将等待选择从固定文档流改成从底部 Composer 上方弹出的等待选择板，使较长的 LiveStatus 不会把操作控件推到视口之外；LiveStatus 仍完整可见并持续运行。
3. 修复分段 Markdown 被逐块渲染造成的连续代码、表格、引用和围栏语义断裂，并收窄 Home/Memory 的正文阅读宽度。
4. 降低 Context 中已加载 Home 的噪声，突出“已安装的资源集合”而不是把整段正文直接堆在检查页面中。

第一执行批次不改变后端 Action、Question 或 Context 协议。当前后端结果已经包含 workspace、execution、search/inspect、memory、web、job 等预览所需的事实；只有在实现核对时发现某种 action 缺少真实结果字段，才由对应 owner 补充最小投影，不在前端拼造结果、不新增平行状态机。

## 2. 已确认的设计约束

### 2.1 动效与主题

- 保留当前 `live-border`、`text-shine`、运行中的旋转指示和阶段流光。等待用户选择期间，LiveStatus 不停止扫光，也不折叠运行区域。
- 输入焦点、待选项和已选项增加同一套 focus token 下的轻微外晕与内层光泽。光效只用于表示可交互和当前选择，不改变卡片尺寸和布局。
- 当前 Light/Dark 主题已经由设置页和 CSS token 支持。第一批不引入第三套主题；先把新增阴影、边框和 accent 色收敛到既有 token。若后续需要多套视觉风格，再单独做 accent palette 的 token 审计，避免给每个组件增加局部颜色分支。
- 减少动效设置仍然有效：新增的呼吸和焦点光晕必须遵循现有 reduced-motion 规则。

### 2.2 Action 的两次出现

一次 Action 在界面中保持两个有明确顺序的条目：

1. **Stage2 / action plan**：表示已归一化、将要执行的行动。卡片给出动作名称、所属域、必要的业务参数和目标对象，例如查询词、文档引用、命令、工作区文件、记忆操作类型。它不能显示成“已完成”，也不使用执行结果字段。
2. **Stage3 / action result**：表示本次执行已经得到的事实。卡片给出成功、部分结果、失败、超时、取消、未执行或结果未知等状态，以及结果数量、退出码、写入摘要、命中标题、截断提示等实际字段。没有结果时明确说明原因，不用 plan 参数冒充结果。

预览只负责回答“做了什么”和“得到什么”，不展开全部 JSON。点击预览的 Details 仍打开现有右侧 `ActionDetailPanel`，详情面板按“结果状态 → 人类可读摘要 → 计划参数 → 执行链路/时间 → 原始载荷”排列，并继续保留不执行、取消、未知结果等事实的区分。

预览和详情共用现有 `trace/registry`、`facts` 与 family result view，不引入第二套 action 分类或前端执行状态机。需要的人类可读文案由 visualization 的展示适配器从已校验的 action/result 事实生成；固定模型文案仍归原 owner 管理，前端文案不进入模型消息。

计划和结果的预览形态按 action family 收敛：

| action family | Stage2 计划预览 | Stage3 结果预览 |
| --- | --- | --- |
| workspace edit/write | 文件或资源名、编辑数量、操作类型 | 实际写入数量、路径、失败项或提交摘要；没有 before/after 时不显示差异图 |
| execution/process | command、工作目录或资源引用、是否为 Job | exit code、stdout/stderr 摘要、截断/运行状态、Job 事实 |
| search/inspect | query、source/refs、分页或约束摘要 | 命中数量、标题/引用、命中依据或正文片段、继续读取入口 |
| memory/home | memorize/write/inspect 等操作和引用 | 实际写入或读取的文档、条目数量、引用校验和 owner 反馈 |
| web/mcp/acp | 目标、查询或连接范围 | 标题/链接、工具返回摘要、失败原因或连接状态 |
| job-control/dialog/session | 启动/检查/回答/整理等语义和关键参数 | Job/问题/组织结果的状态与待处理事实 |

`actionTarget` 需要补充当前真实协议中已经存在的 `target_link`、`source_link`、`cwd_link` 和 action family 特有目标字段，使摘要不会退化成内部字段名。若结果只有 `payload` 或 `items`，先由 family view 读取真实字段，再以统一数量和标题摘要显示。

### 2.3 等待选择板

等待板是等待期间的一个共享呈现入口，目标是当前唯一处于等待用户的 Turn。它不创建新的 Turn、Cycle 或回复状态机，也不改变 `QuestionCard` 的权威快照和 `replyToQuestion` 的收敛流程。

- 从 Composer 顶部弹出，覆盖 Composer 及对话底部一部分空间；设定最大高度，选项和补充输入在板内滚动。
- 背景保留当前对话和完整 LiveStatus；弹出时可使用低透明度 scrim 与轻度 `backdrop-blur`，但不隐藏 LiveStatus，不出现“定位问题”按钮，也不增加解释性小字。
- 选项使用选择板布局，选中项保留边框、浅色填充和轻微光晕。问题正文、完整选项和补充想法在同一板中连续出现。
- 若当前问题允许补充想法，补充输入始终显示在选项下方，不再在选中选项后才展开；`Other` 输入也保持可见并按当前协议决定是否需要内容。提交按钮只在协议要求满足时可用。
- 键盘焦点进入弹出板，`Esc` 只关闭临时焦点或返回草稿，不取消 Turn；提交仍走原有 question id、epoch、turn id 和回答接口。
- 用户提交后，等待板立即结束交互显示，等待状态是否继续由服务端快照决定。正式投影到达后，在 LiveStatus 下追加只读的选择板：显示问题和被选中的选项标签，补充想法作为一条普通用户气泡；不显示 `opt_a` 等内部 option id。临时 outgoing echo 只保留到 owner 投影收敛，避免重复事实。
- Reflection Turn 复用同一个等待板组件和同一选择器，只替换 target id 与主题语境；因为根执行同一时刻只有一个等待目标，不同时显示两块问题板。

Budget 等待仍沿用当前 BudgetCard 和预算事实，不把预算倒计时伪装成问题选择。若需要统一视觉，只复用等待板的表面和焦点 token。

### 2.4 阅读与页面密度

`ChunkedMarkdown` 当前按每个 2000 字符单元独立调用 Markdown，导致围栏代码、表格、引用和连续段落在边界处失去语义。修复时保留 disclosure page 的 ref、顺序、继续读取和容量边界：

- 在已经读取的连续 page 序列中拼接原始文本后进行一次 Markdown 渲染，不插入虚假的换行或分隔符。
- 同时保留每个片段的来源范围，用于 fragment 定位、继续读取和错误提示；不把连续渲染误认为已经读取了未加载内容。
- page 不连续、引用切换或读取失败时，显式保留边界和继续入口，不静默拼接不同文档。
- 同一阅读组件供 Home、Active Memory 和 Memory Document 共用，代码块/表格允许局部横向滚动，正文容器控制在约 68–76ch，并在宽屏居中。

Context 的“已加载 Home”改成紧凑资源目录：每项只显示资源标题/稳定 ref、来源标签、字符或片段数量和一行摘要；点击或展开后才显示当前已加载内容。展开仍使用 owner 提供的 Markdown 和 ref，不新增后台加载，不把 actual Home、overlay 和本轮安装快照混为一层。

## 3. 代码实施范围

### 3.1 Action 预览与详情

1. 在现有 `trace/registry.ts`、`trace/facts.ts` 和 `chat/presentation.ts` 之间补充一个纯展示描述层，统一生成 action label、参数摘要和结果摘要。其输入只接受已经归一化的 plan/result facts。
2. 调整 `ActivityStep` 与 `ActivityGlimpse` 的信息层级：plan 显示真实参数，result 显示真实状态和 family 结果；两个条目的颜色和图标可以相互呼应，但不能合并为一张“完成卡”。
3. 扩展 `ActionDetailPanel` 顶部摘要和参数分组，保留右侧抽屉、模型调用、Job 链接、失败反馈和原始 payload 折叠层。原始 JSON 必须继续放在最后。
4. 将 workspace edit 的结果视图与 plan diff 严格分开；只有后端实际返回 before/after 或等价事实时才显示差异，否则显示写入统计和 owner 反馈。
5. 增加覆盖代表性 family 的展示测试，重点验证 plan/result 顺序、失败/未知/未执行状态、参数字段和结果字段未互相串用。

### 3.2 等待板与回复收敛

1. 在 ChatView 的布局边界增加 `WaitingResponseDock`（名称可在实现时按现有命名调整），它消费当前 live waiting question，不复制 QuestionStore 或 turn 状态。
2. `WaitingQuestionCard` 的 active 交互迁移到 dock；LiveStatus 下保留正式只读投影所需的渲染路径，避免 active 与 formal 同时出现。
3. QuestionForm 的补充输入改为稳定占位区域，保留现有校验、选项 id、comment 和提交回执；选中态增加轻晕，不改变当前 action/live 光效。
4. 正式回复行使用 canonical question/options 将 option id 映射为显示标签；用户气泡只承担补充想法或真正追加文本，避免把内部协议字段直接暴露给用户。
5. 为 User Turn 和 Reflection Turn 增加同一套弹出、提交、失败、过期、预算等待和 reduced-motion 行为验证。

### 3.3 Markdown、Home/Memory 与 Context

1. 优先修改现有 `ChunkedMarkdown`，让连续 page 在同一 Markdown 语境中渲染，并维护 fragment → page 的来源映射；只有现有组件无法表达映射时才拆出小型纯展示子组件。
2. 为 HomeContentView、ActiveMemoryView、MemoryDocumentView 统一接入阅读宽度和局部 overflow 样式。
3. 将 `BackgroundPanel` 的资源卡改为“目录行 + 按需展开”的紧凑层级，保留完整内容读取和来源标识。
4. Context Overview 继续按 Background/Trace/Working 分组；只改善行标题、数量、形状和 owner 摘要的可读性，不把内部 revision、digest 等实现字段直接暴露给用户。
5. 修复执行页把不同结束事实都称为 “After-finish diagnostics” 的标签，分别表达最终结果、收尾失败和附属诊断，避免把清理诊断误认为执行失败。

## 4. 执行批次

### 批次 A：数据与动作呈现

完成展示描述层、actionTarget 字段补齐、Stage2/Stage3 卡片分层和 ActionDetailPanel 摘要调整。先用现有真实 observation/turn projection 构造 fixture，确认不需要后端变更。

验收：每个代表性 action 都能看到“计划参数 → 结果事实”的顺序；失败、超时、取消、未执行和未知结果没有被压成成功；点击 Details 能继续核查完整载荷。

### 批次 B：等待选择板

迁移 active QuestionForm 到 Composer 上方 dock，保留 LiveStatus、扫光、对话滚动和当前 Composer 输入语义。实现低强度背景模糊、焦点光晕、键盘焦点和板内滚动。

验收：长 LiveStatus 下选择板仍在视口内；等待期间运行扫光持续；没有定位按钮、折叠 LiveStatus 或额外小字；提交后正式问题、选择标签和补充气泡只出现一次。

### 批次 C：阅读连续性

修复共享 Markdown 渲染和来源映射，随后调整正文最大宽度、表格/代码局部滚动。

验收：跨片段代码围栏、表格、引用和连续段落保持语义；继续读取仍按真实 page 工作；不连续 page 不被伪装成一个文档；Home 与 Memory 的正文在宽屏和窄屏都可读。

### 批次 D：Context 与新页面细节

完成 loaded Home 紧凑目录、Home/Memory 页面间距和执行结束标签修正。保持当前 Context Inspector 的 tab 和右侧详情行为。

验收：首次进入页面能先看到资源集合和重点摘要；展开才看到正文；owner、ref、来源和已加载范围仍可核对。

### 批次 E：回归与细修

按现有 visual review、motion trail、question reply、Context/Home/Memory 页面用例回归。重点检查窄屏、长 action 参数、长结果、失败结果、等待板滚动、Light/Dark 和 reduced-motion。

## 5. 不做的事情与后续选项

- 不把等待板变成全屏模态，不隐藏或折叠 LiveStatus，不加入“定位问题”按钮，不依赖解释性微文案维持操作。
- 不把 Stage2 plan 和 Stage3 result 合并为一条，也不从 plan 参数推断成功、差异或写入内容。
- 不新增第三套主题、不在本批次重写全部颜色系统；主题扩充只有在 token 审计后作为独立小批次执行。
- 不为前端展示新增通用 JSON 日志、第二套 Action 状态机或跨 Turn 缓存。
- 不因阅读组件修复而自动扩大 disclosure 范围；容量、page、ref 和 owner 规则保持不变。

## 6. 需要确认的默认选择

我建议按以下默认值进入实现讨论：

1. 等待板采用“Composer 上方底部弹出 + 低强度背景模糊 + 板内滚动”；提交后的正式呈现采用“只读选择板 + 有补充想法时再追加用户气泡”。
2. 主题先保持 Light/Dark，新增光效全部使用现有 token；暂不承担第三套主题的维护成本。
3. loaded Home 采用“紧凑资源目录行，点击展开当前内容”，而不是继续在 Context 页面直接展示长正文。
4. 第一批保持后端协议不变；若真实数据检查证明某个 action result 缺少必要字段，再提出对应 owner 的最小投影改动。

请确认这四项默认选择是否作为后续实现边界；若你希望在“只读选择板”和“选择后追加完整用户选择气泡”之间调整，我会在实现前把该分支的重复信息和视觉占用重新列成对照稿。
