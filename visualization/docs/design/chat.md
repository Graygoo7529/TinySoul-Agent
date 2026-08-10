# 对话与执行轨迹设计

## 对话优先

- 主界面是一条连续的聊天历史（背景为 2% 透明度 24px 微网格）：右侧为用户消息（浅 tinted 玻璃气泡：accent 浅底 + 深靛文字 + 细描边 + 背模糊），左侧为 Agent 行（渐变头像 + 内容区）。
- Agent 行在完成态展示 Markdown 渲染的最终回答。回答卡为微渐变亮面纸感（顶部内高光 + accent 淡彩柔影）；当前会话内完成时，回答在**回锚滑动 → 折叠 → 停顿**之后以固定节奏（约 280 字/秒，6s 封顶）逐字流入，流入期间卡片带 accent 柔光与顶部流光扫掠（`answer-streaming`），历史恢复的回答直接全量呈现。页脚给出状态徽标、耗时、概要（cycles/actions/domains/成败数）、token 用量与 Details 入口。
- 用户输入通过本地回声即时上屏；非本端输入从首个 message stack 的 `user_input` 段恢复。

## 运行状态动态披露（LiveStatus 活跃状态）

进行中的用户轮在 Agent 行内展示 LiveStatus 实时状态卡（即主对话界面的浮动状态栏），全部从观察事件流派生：

- **流光标题行**：陈述当前活动——phase 运行中显示与 trace 折叠条同款的运行句（`PHASE_META.running`：Maintaining context and selecting domains… / Generating action parameters… / Executing actions…），执行 action 时显示 registry 动词 + 目标；流光动画与入场动画分层嵌套互不覆盖。准确性采用**单一待定规则**：phase3 只剩 1 个无结果 action 时才具名（此时必然准确），多个待定显示 "Executing N actions…" 批次进度，不妄指（彻底解决依赖后端 `action.execution.started` 事件，见需求单）。右侧为轮计时与当前 action/phase 计时（tabular-nums）。
- **流动更迭节奏**：1500ms 原子节拍（`useThrottledValue`）把抬头与步骤轨迹合并为同一次提交，爆发期合并为一拍、尾随冲刷保证最终状态不丢。每拍按精确时间线依次播放三类动画（由 motion 库驱动）：① t=0 抬头经 `Crossfade` 交叉淡入淡出（出 280ms / 入 360ms），思考行旧文本淡出（300ms）、新行 t≈120ms 起柔和浮现（fade + 上浮 + 去模糊 450ms）；② t≈650ms——新思考明显开始之后——步骤区新行高度展开（600ms），旧行随布局流整体下滚；③ t≈920ms 新行内容浮现（450ms），全拍约 1.4s 收定。同拍多条以 170ms 级联（上限 3 级）。工作区条目（todo/milestone）进出均经高度 tween，移除不瞬跳。步骤行以 activity 条目的稳定 `seq` 为 key——事件流全量重建（derive replay）不会重挂载任何行，这是"坍塌再填充"类闪动的根治。
- **沉淀态（settled 折叠条）**：LiveStatus 在运行与落定之间是**同一卡片实例**——轮次结束时先停顿 300ms、再按需回锚滑动（800ms，运行漂移或用户滚动过但当前空闲时滑回气泡置顶位），随后卡体（思考面板 + 步骤区 + 工作区）从下沿向上卷起折叠（700ms 高度 tween），抬头淡换为落定状态行（"回答完成/轮次失败…" + 概要 + 定格总时长），呼吸边框转静态；折叠条带 chevron，点击重新展开完整静态轨迹（展开恒为向下铺出——折叠类交互会短暂暂停滚动跟随，方向与滚动位置无关）。发起新 user turn 时旧折叠条自然收起（新一轮挂出自己的运行卡）。**终态清扫**：轮次结束时 derive 层把遗留 running phase 置 `ended`、未落定 action 条目置 `stopped`（静态停止图标）、in_progress todo 置 `cancelled`——settled 卡与 trace 抽屉里不再有任何"还在转"的假象（无结果的 ActionCard 显示 interrupted 徽章）。
- **思考流**：最新一条 reasoning 以**固定一行**呈现（`.thinking-slate`）——内容为第一个非空行的**行内 Markdown 预览**（`.md-inline`：块元素降为行内、字重压平（加粗忽略）、链接惰性、数学经 KaTeX 行内排版、省略号截断；整行 11.5px/380 细体微斜 oblique 8° + fg-faint，左端留 12px 空隙），换思考时旧行淡出、新行柔和浮现，面板高度恒定不动；有更多内容时可 Expand 展开为完整 Markdown（`.thinking-md`：与预览同字号同风格的 11.5px 细体微斜排版，加粗克制为 500、斜体记号以正立体形成对比、公式保持 KaTeX 正立），高度平滑释放。整块首次出现时经 `grow-in` 展开入卡。
- **语义步骤栈**：最新在前的活动条目（intent + domain 胶囊、挂载 skills、todo/milestone、action）。运行中步骤区为**固定最大高度的滚动视口**（`.steps-viewport`，12rem ≈ 7 行，渲染窗口 9 条）：新行先展开高度把旧行整体下滚（滚轮感），内容随后浮现；抵近底边的旧行在渐变消融 mask 中淡出消失（溢出闩锁判定，临界不闪动）；就地更新全部 tween 化——状态图标翻转微淡入、stage3 结果行高度展开（`ActivityStep` 的 `animate` prop）、glimpse 挂载经 `grow-in`、glimpse 撤下经 `AnimatePresence` 高度坍缩——栈内无瞬时跳变。视口填满或存在更早步骤时底部出现 "+N earlier steps"（经 `grow-in` 出现），展开时解除高度限制（用户主动行为）。**有结果要点的已落定 action 行可点击就地展开/收起其 gist**（悬停底色 + 右侧 chevron），滚入历史的行同样可展开。配合 `ChatView` 的**顶部停泊跟随**（见下），视口填满后卡片边框完全冻结。纵深渐隐由 `.step-depth` 过渡承担。action 条目是状态机（planned 空心点 → running 旋转 → succeeded/failed/timeout），并呈现两条信息：上行 stage2 调用语义（编辑的目标文件、检索意图、待访问链接、待执行命令、inspect/recall 目标），下行 stage3 结果摘要（exit code、结果数、revision、行数）。
- **顶部停泊跟随（ChatView）**：内容区尾部有**永久约 85vh 空白**，锚点（视口顶沿下 20px，`TOP_ANCHOR`）在任何状态下都可达。新一轮开始即以 950ms 平滑滑动（easeOutQuart 快出慢落）把气泡送到顶沿；**运行全程只锚定不跟底**——live status 是浮动新内容，向下延展即可，视图不动。轮次结束时：先停顿 300ms，再按"用户此时未在滚动"为条件做 800ms 回锚滑动（运行中用户滚动过也没关系；正在滚动则跳过），随后折叠、打字；**仅打字期间**内容超出视口才交接为内容底部跟随（最新回答文字始终在屏内）。用户滚轮/触摸立即接管（滑动即时取消，回到目标附近自动重新停泊）；完成后不做任何位置调整。
- **Action 内联详情（ActionGlimpse）**：步骤栈中运行中的 action 披露其 stage2 输入（命令行、patch 迷你 diff、生成 instruction、memorize 操作清单），最近完成的 action 自动披露其 stage3 结果要点（输出尾部默认 2 行可展开、检索前三条、抓取标题摘要、diff 统计 +N/−M、失败 feedback）；其余已落定且要点的 action 行可点击就地展开/收起。保持紧凑，完整呈现归 TurnTraceDrawer。
- **独立工作态区域**：todo 列表（状态图标、进行中高亮、完成划线）与 milestone 在状态卡下部常驻，由 Phase1 control tools 与 message stack 的 `working` 段共同推导。
- 整卡在运行中呼吸渐变边框（live-border）+ 流光标题（text-shine）；停止请求挂起时降级为静态警示边框。停止按钮在 Composer 上。

## Turn 追溯抽屉（TurnTraceDrawer）

每个用户轮可从右侧拉出追溯抽屉（即 "Details 面板"，运行中实时更新，标注 live）：

- **Overview**：cycles / LLM calls / tokens / actions 统计与最终回答摘要。
- **Working Context**：该轮最终 todo/milestone 状态。
- **CycleSection（可折叠）**：折叠时显示状态徽标、选中的 action domain 胶囊标签、动作/LLM 调用/耗时统计；展开后呈现三个默认折叠的 PhaseSection 行。
- **PhaseSection（折叠即语义）**：不解释"phase 是什么"，直接陈述"phase 做了什么"——
  - Phase1：折叠直接展示选中的 domain 胶囊，文案为 "Selected N domains" / 运行中 "Maintaining context and selecting domains…"。
  - Phase2/3：折叠直接展示动作名胶囊（planned 灰 / 成功绿 / 失败红 / 执行中 accent）；Phase2 文案为 "Planned N actions"（折叠行宽度有限，动作语义由胶囊与展开卡片承担），Phase3 运行中为 "Editing workspace:x.md (1/2)"、完成为 "2 actions executed · 1 failed"。折叠行副标题的 intent/reasoning 预览经纯文本化（`plainExcerpt` 剥除 markdown 记号）。
  - 展开后呈现完整语义：意图与推理思考以引述式块呈现（accent 左边线 + 浅底，避免大面积色块并置突兀；`md-calm` 柔化加粗），control operations（domain 选择与 intent、todo/milestone 设置/移除、背景加载/逐出）、ActionCard 输入输出、工作区变更。
- **LlmTaskDrawer 子抽屉**：Phase 折叠行右侧的 accent 胶囊按钮（Brain 图标 + "context"/"N calls"）是唯一入口，不展开 Phase 即可直接唤出最近一次任务；子抽屉从主抽屉**左侧**弹出（简约 slide+settle 动效，点击面板外收回），头部两行布局（标题行 + 模型/用量元信息行，窄窗口不重叠），展示该次任务的 Request message stack（Identity / User Inputs / Background / Turn Trace / Working Context / Task Prompt 分区，分区可折叠，内部 JSON 字段默认展开）、Tools offered（胶囊标签，点击展开 description、kind/strict 徽标与 parameters schema）与 Response（reasoning / answer / tool calls / usage）。
- **ActivityTimeline**：全量语义活动时间线（kind 过滤、时钟时间、点击锚定 ActionCard 并闪烁高亮）。
- **Trace 导出**：选择目录后由 Rust 侧写入文件夹——`tinysoul-turn-<id>-<时间戳>/` 下 `turn.json`（完整结构投影）、`trace.md`（可读文档），以及 `cycle-N/phaseM-llm-K-<profile>.json` 每次 LLM 任务（Request+Response）的独立文件。浏览器 dev 模式回退为单 JSON 下载。

## Action 呈现架构（registry + 家族渲染器）

呈现语义集中在两处，新增 action 只需改一个域文件：

- **`src/derive/actions/`（纯函数层）**：`descriptorFor(action)` 返回 `{verb, family, summarizeCall, summarizeResult}`——stage2 调用摘要（中文动词 headline + 结构化 target + chips）与 stage3 结果摘要（headline + tone）。49 个 action 按域组织（core/workspace/execution/web/home），未注册 action 回退 generic descriptor。15 个呈现家族：answer / reason / generate / patch / command / process / search / fetch / memory-read / memory-write / read / inspect / scan / delete / generic。
- **`src/components/trace/renderers/`（视图层）**：family → 丰富视图的映射。patch 家族渲染 old/new 行级 diff（`utils/diff.ts`）；command/process 家族渲染命令行与 exit code/stdout/stderr 终端块（含 candidates）；search 家族统一四类结果列表；fetch 家族渲染标题/摘要/字符数；memory 家族渲染 recall Markdown 预览与 memorize ops 清单；read/generate/answer 各有专属视图；探针失配一律回退 JsonTree，不隐藏任何信息。
- **ActionCard**：头部为 family 图标 + registry verb + target；Input 节 = 家族输入视图 + Raw parameters 折叠；Output 节 = failure 框（reason/scope/feedback/disposition/constraint 五元组）+ 家族输出视图 + Raw payload 折叠 + Diagnostics 折叠（`frame_data` 与 invoke/batch id；`ActionResult.stage` 标注为 "stage: \<value\>"，与 Phase 术语区分）。

## 派生数据

`src/derive/chat.ts` 消费原始 `EndpointEvent[]`（+ 本地输入回声），构建：

- `ChatTurn[]`：用户输入、助手回答、状态、Cycle 列表、working 投影、activity feed、usage、currentActivity。
- `Cycle[]` / `PhaseStep[]`：按 `cycle`/`phase` scope 帧归组。
- `ControlOp[]`：从 Phase1 模型响应的 control tool calls 解析（`select_action_domains`、`set/remove_todo`、`set/remove_milestone`、`load/evict_background`）。
- `ActionRecord[]`：`action.call` 在 Phase2 生成 planned record；`loop.phase.started(phase3)` / `action.batch.started` 时将未完成的 planned 记录**预镜像**进 Phase3（运行中即可观测"哪个 action 在跑"）；`action.result` 按 call_id 同时更新镜像与原记录。计划与执行不混淆，normalize 失败的单侧 result 直接追加。
- `ActivityItem[]`：语义活动 feed。action 条目按状态机流转（phase2 完成建 planned 条目 → phase3 最早未完成项翻 running → result 到达翻 succeeded/failed/timeout 并写 resultHeadline），文本取自 registry。
- `ModelTask[]`：按 `llm.*` 事件归组，含 request（完整 message stack）/response。
