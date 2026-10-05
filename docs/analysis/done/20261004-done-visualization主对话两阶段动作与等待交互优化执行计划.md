# visualization 主对话两阶段动作与等待交互优化执行计划

状态：done

计划日期：2026-10-04

实施完成：2026-10-05

基线：`c479ca0` 的主对话视觉与动效语义；`35f1440` 之后的 v2 接口；当前工作树的 visualization 实现

关联规约：`AGENTS.md`、`docs/design/` 中关于 Turn/Cycle/Phase、Action、Observation、Context 和渐进披露的当前定义

## 1. 为什么做

当前主对话已经保留了 c479ca0 的主要质感：LiveStatus 持续扫光、阶段动效、回答收束动画和右侧 action 详情抽屉。需要继续打磨的是信息落点：Stage2 计划与 Stage3 结果要各自说明“准备做什么”和“实际得到什么”，等待选择不能因为对话较长而落到视口外，连续文档不能被分页边界打断，Context 中已加载 Home 也应先呈现资源集合再按需阅读。

本批次只在现有 v2 owner 投影和前端组件上改进呈现，不新增前端状态机，不把实现字段直接暴露给用户，也不改变后端 Action、Question、Context 协议。若核对真实数据后确有缺失字段，再由对应 owner 提出最小协议调整。

## 2. 已确认的呈现语义

### Action

- Stage2 action plan 先产生，呈现已归一化的动作名称、所属域和真实业务参数。
- Stage3 action result 后产生，但主对话和 ProcessPanel 均保持“最新条目在顶端”，因此 result 在 plan 上方；底层事实仍按观察顺序保存，不在前端伪造事件顺序。
- result 只读取真实状态、payload、命中项、退出码、写入统计和失败反馈；不使用 plan 参数冒充执行结果。
- 预览按 action family 给出紧凑摘要，完整核查继续从右侧 `ActionDetailPanel` 进入；原始 JSON 和附加执行链路保持折叠。

### 等待选择

- 等待板从 Composer 上方底部弹出，允许覆盖 Composer 和对话底部区域；对话与完整 LiveStatus 保持可见，运行扫光持续。
- 弹出区域使用轻度背景模糊和现有 surface 光泽，选项、完整问题和补充想法保持在同一板内；不增加定位按钮、解释性微文案或折叠 LiveStatus。
- 补充想法输入稳定显示，不依赖先选项才出现。提交仍复用现有 question id、turn id、epoch 和 `replyToQuestion`。
- 提交后等待板转为只读选择板，显示问题、全部选项和框中的已选项；补充想法单独追加为用户气泡。正式 owner 投影到达后替换临时本地状态，避免重复事实；option id 映射为选项标签。
- User Turn 与 Reflection Turn 共用一个 dock 和同一 live-question 选择器，同一时刻只显示当前等待目标。

### 动效、阅读与 Context

- 保留当前 LiveStatus 扫光、`live-border`、`text-shine` 和运行指示；只在输入焦点、可选项和已选项增加轻微外晕与内层光泽，并继续遵循 reduced-motion。
- 连续 page 在同一 Markdown 语境渲染，保留真实 fragment/page 来源映射，不扩大 disclosure 范围；Home、Active Memory、Memory Document 共用更稳定的阅读宽度和局部横向滚动。
- Context 的已加载 Home 改成紧凑资源目录行：标题、稳定 ref、来源、规模和摘要优先，展开后才显示已加载正文。

## 3. 要做什么

### 3.1 Action 预览

1. 补齐现有 facts 展示适配对目标引用字段的读取，统一 plan 参数摘要和 result 结果摘要。
2. 调整 `ActivityStep`/`ActivityGlimpse`：plan 显示动作与参数，result 显示状态和真实 family 结果；保留两条条目、右侧详情入口和最新在上。
3. workspace edit/write 的 result 使用实际写入统计、资源引用和 owner 反馈；没有真实 before/after 时不显示差异图。
4. 为代表性 action family 增加展示测试，覆盖 plan/result 顺序、失败/超时/取消/未知结果以及参数与结果不串用。

### 3.2 等待板与提交呈现

1. 在 ChatView 布局边界加入共享 `WaitingResponseDock`，把 active QuestionForm 移到 Composer 上方，同时保留正式只读 `QuestionCard` 渲染路径。
2. 让 QuestionForm 的补充想法稳定占位；选中项使用轻微 focus/selection 光晕，不改变卡片尺寸和现有运行光效。
3. 提交成功后在 dock 内先显示只读选择板和可选补充气泡；投影收敛后由正式 interaction 接管，accepted reply echo 不重复显示，失败 echo 保留原有重试语义。
4. 验证 User Turn、Reflection Turn、长内容滚动、过期/失败、预算等待和 reduced-motion 行为。

### 3.3 阅读与新页面

1. 修改共享 `ChunkedMarkdown`，按连续同源 page 拼接后一次渲染，同时维护 fragment 命中定位和来源标记；不同文档或不连续 page 保持边界。
2. 收敛 Home、Active Memory、Memory Document 的正文宽度和代码/表格局部 overflow。
3. 将 `BackgroundPanel` 的 loaded Home 资源改为“目录行 + 按需展开”，保持 owner ref、来源和实际内容读取。
4. 修复执行页结束事实的标签表达，避免把附属诊断误认为执行失败。

## 4. 验收与边界

- 长 LiveStatus 下等待板始终在视口内，扫光不停止；提交后问题、全部选项、选中项和补充气泡各自只出现一次。
- action result 位于 plan 上方，且预览不从 plan 参数推断成功、差异或写入内容；Details 仍能核查完整事实。
- 连续代码围栏、表格、引用和段落跨 page 不断裂，fragment 定位仍绑定实际读取 page。
- Home/Memory 正文在宽窄窗口均可读，Context 首屏先看到资源集合和摘要，展开才读正文。
- 通过现有 visualization 单测与构建检查；不修改无关后端、持久化和运行控制代码。

## 5. 实施顺序

实施按以下顺序完成：先补齐 action facts 与结果呈现，再把等待回复收拢到共享底部 dock；随后合并连续 Markdown page、统一阅读宽度并压缩 Context 资源目录密度。最后运行聚焦用例、完整 visualization 测试和生产构建，核对全部条目后归档本计划。

## 6. 实施核对

- Action：保留观察事实顺序，在 LiveStatus/ProcessPanel 中维持最新条目在顶端；result 位于 plan 上方。plan 使用实际参数摘要，result 使用 payload、状态、命中项、退出码或写入统计；右侧详情入口保持不变。
- 等待：新增共享 `WaitingResponseDock`，从 Composer 上方弹出并覆盖底部区域；LiveStatus 扫光持续，补充输入保持可见，提交后显示只读选择板，补充想法单独呈现为用户气泡，正式投影接管后不重复显示 accepted reply。
- 动效：保留既有运行扫光和回答收束，新增 focus/selection glow，并通过 reduced-motion 关闭新增的弹出动画。
- 阅读与页面：连续同源 Markdown page 合并到同一渲染语境；Home、Active Memory、Memory Document 使用统一阅读列；Context loaded Home/Memory 资源改为紧凑目录行、展开阅读；执行结束诊断标签明确区分收尾与清理。
- 验证：聚焦用例 5 个测试文件、49 项通过；完整 `npm test` 通过，91 个测试文件、812 项通过；`npm run build` 通过。构建仍报告 Mermaid 等既有大型 chunk 提示，不影响产物生成；本地预览服务返回 HTTP 200。
