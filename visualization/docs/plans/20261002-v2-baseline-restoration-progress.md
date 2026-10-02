# v2 对齐 c479ca0 界面：实施核对

状态：`done`；核对日期：2026-10-02。

执行计划：[Chat v2 基线恢复与界面重构](../../../docs/analysis/done/20261001-done-visualization-chat-v2-baseline-restoration-plan.md)。在最新代码上实施，以 `c479ca0` 的组件布局、光泽、动作轨迹、回答动画和滚动规则为基线，使用 v2 的正式事实和读取接口。

## 逐项核对

| 阶段 | 实施与证据 |
|---|---|
| P0 基线 | 对照原 `components/chat/{ChatView,TurnView,LiveStatus,ActionGlimpse}` 与 `components/trace/TurnTraceDrawer`，复用主题和 motion 常量，由下列 v2 入口承接表现行为。 |
| P1 Observation | `api/v2/observation.ts` 统一 Turn scope；连接订阅 model 级事件。`ActivityBuffer` 保留必要摘要，按 sequence 合并 replay；思考来自 reasoning summary，执行状态来自 execution/result。 |
| P2 连续会话 | `turnController` 读取全部 Session 目录分页并复用不可变正文；`ChatView` 在同一容器按 owner 顺序显示当天全部 Turn，活动 Turn 按 ID 去重。刷新后仍显示多轮正文。 |
| P3 Chat | `ConversationRows` 承接气泡、单一 Agent 内容列、问题与回复、回答流入与收束、完成栏；`LiveStatus` 恢复计时、思考、动作浮层和 Working。`useConversationScroll` 保留顶部锚点、长回答跟随与手动接管。删除未使用的 `TurnView.tsx`。 |
| P4 Trace | `ProcessPanel` 保留统计区和 Cycle/Phase 卡片、推理预览、控制请求、Action/Model/Job 入口；活动 Turn 刷新。模型 MessageStack 从阶段 context 按钮向左展开，同一 Inspector 栈管理返回与关闭。 |
| P5 Context | `ContextInspectorPanel` 提供当前 Context、Session map、已加载 Home、已加载 Memory；资源子页复用已安装段读取，不调用 `read_top`。无活动 Turn 时仍可查看 Session map。 |
| P6 设置 | `i18n/` 映射页面文案及 catalog 字段标题、说明和枚举显示标签。搜索支持中文、原文和路径；未知字段保留原文。批量草稿和运行方案切换前的明确处理保持不变。 |
| P7 验证与文档 | 完整门禁及本地 Endpoint 浏览器联调通过；同步 Chat、Settings、Connection、页面索引和配置覆盖文档。 |

## 语义与边界

- Turn/Session 决定交互和结果，Observation 提供过程详情。请求模型执行 Action 不等于执行成功；取消、未执行与未知结果不生成工具返回。
- Working 读取当前已安装 plan；Trace 中 Working 标明来自最后一次留存模型请求。
- 顶部 Context 是本轮安装内容，模型上下文是某次调用的消息；Home/Memory 全量资源浏览保留在各自页面。
- 完成栏显示正式状态和交互记录中的 Action 统计；活动记录可显示捕获耗时。Session 未提供的历史耗时、模型用量不填零或推测；留存模型详情继续从 Trace 查看。
- 设置翻译只属于表现层，不修改路径、ID、枚举值、用户输入或校验规则；动态后端诊断保留原文。本轮没有增加语言切换或后端翻译协议。
- 本轮未修改生产后端 API。端到端测试使用真实 Agent、owner、HTTP 和 WebSocket，模型 runner 使用确定性脚本；未调用外部供应商。

## 验证记录

| 验证 | 结果 |
|---|---|
| Vitest 全量 | 88 个文件、789 个测试通过；最终完成栏修改后 ChatView 15 个相关用例再次通过 |
| TypeScript / Vite | 检查及生产构建通过；构建仍提示既有大型 chunk |
| Python Full | 1223 passed，25 deselected |
| Python typecheck | TinySoul Python 3.13.12、ty 0.0.84，通过 |
| 浏览器交互 | 提交、真实思考事件、问题选项/评论、回复、Trace 模型双抽屉、Context 四子页、连续两轮与刷新恢复通过 |
| 浏览器页面巡检 | 明暗 Chat、Session map、历史、中文设置、Home、Memory、Workspace、Runtime 以及 800px 窄屏通过 |

追加输入、预算、取消、事件 gap、历史只读和迟到响应隔离由组件/控制器测试覆盖；真实浏览器路径验证共同使用的 v2 接线。测试截图位于忽略的 `.local-test/playwright-output/` 与 `.local-test/visual-review/`，可由 `test/e2e/chat-flow.pw.ts` 和 `visual-review.pw.ts` 重建。测试端口由系统分配，日常连接仍由设置页输入 `127.0.0.1:1430` 或已有转发地址。

## 组件细节复核与补齐

后续对照见 [组件细节恢复计划](../../../docs/analysis/done/20261002-done-visualization-baseline-detail-restoration-plan.md)。上述 P0–P7 记录接线与页面恢复；本轮继续补齐其未充分验证的表现细节：

- Turn 使用同一挂载实例承接活动投影和 Session，复用 c479ca0 起止编排；滑动定位、活动折叠、回答打字和收束经过浏览器逐帧采样。
- 动作浮层恢复原版紧凑内容与两拍展开；手动折叠、快速释放和 reduced-motion 分别验证，完整结果仍进入 Trace。
- Activity 显示真实背景资源、任务 Skill、思考及已接受域；原版图标/领域色适配现有类型。Trace 补齐 Phase 状态、Cycle/Phase 耗时和留存 token 统计。
- 后端新增只读 background 页，通过既有 Session completion 保存 Heap 正文。Home/Memory 子页直接阅读，完成后和刷新后仍可查看原快照，不调用 Agent 加载接口；旧记录缺失正文时明确提示。
- 最终验证：Python Full 1224 项、ty、TypeScript、Vite；Vitest 90 个文件 799 项；真实 Endpoint 连续对话与背景/模型抽屉联调通过。细节与验证边界以新计划为准。
