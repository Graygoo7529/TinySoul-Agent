# 20260715 Agent Capabilities And Action Expansion Plan

## 状态

status: in_progress (Stage 1 done; Stage 2 pending confirmation)

依赖（已满足）：Stage 8 发布与初始化闭环、`20260715-done-default agent home content plan.md`。

## 目标

基于现有 Action backend mechanism 扩充真实、可维护的 Agent 能力。该计划不以保留 domain 或展示 backend 为目标；只有具备明确用户价值、输入输出协议和安全边界的 action 才进入内置 Catalog。

## 组织边界

1. 具有独立链接、持久化或 runtime/trap 生命周期的能力才建立顶层业务模块；
2. 无独立持久状态的轻量能力放在 `tinysoul/capabilities/<capability>/`，由能力包的 service/client/evaluator 承担业务逻辑，由 `actions.py` 提供 ActionEngine registrar/executor 适配；
3. 通用执行机制继续位于 `tinysoul.action.backends`；capability 不重复实现 subprocess、temporary script、LLM task 或 ActionResult 管线；
4. Catalog 只描述真实 domain/action，空 domain、预留 action、未注册 handler 和通用“执行任意模型脚本”均禁止；
5. 需要硬停止的外部工作使用受控 subprocess/script backend；native 仅承载可协作取消且受信任的进程内逻辑。

## 推荐推进路线

本计划将 TinySoul 定位为本地、项目作用域内的知识工作 Agent。推进顺序优先补齐“取得内容、转换内容、受控执行、确定性处理”，再扩展知识图检索、外部连接器和交互界面。以下 Stage 只表示本能力扩展计划内部的顺序，不复用此前 Daily Lifecycle 的 Stage 编号；每个 Stage 都必须在语义确认、实现和验收完成后再进入下一项：

1. **Stage 1 Resource Conversion（done）**：在 Workspace Link 边界内把受支持文档转换为可检查、可作为后续 action reference 的 Markdown 与关联资源；
2. **Stage 2 Read-only Web Research**：提供有界搜索和网页读取，返回来源 Link、摘要与引用信息，不在该阶段引入登录、提交表单或其它写操作；
3. **Stage 3 Controlled Project Tasks**：只暴露项目拥有的具名工作流和固定参数，不提供任意 shell 字符串或模型自行拼接命令；
4. **Stage 4 Deterministic Utilities**：补充数学、时间、编码和结构化格式转换等具有明确 schema、纯输入输出和稳定失败语义的工具；
5. **Stage 5 Knowledge Retrieval Enhancements**：实现 Home Backlink，并在真实数据规模证明需要后增强 Memory 片段检索；
6. **Stage 6 Connectors And Interaction**：按真实使用场景增加外部服务连接器、文件导入导出、用户审批和更丰富的交互入口，不预先建设通用插件平台。

该顺序不是要求一次性完成全部能力。Stage 1 至 Stage 4 应各自形成独立、可使用的能力闭环；Stage 5 和 Stage 6 只有在实际使用反馈给出明确查询或连接需求时才进入实施。

### Stage 1 Resource Conversion

Stage 1 解决 Workspace 已识别 `document`、但不能把文档转换为可局部读取 Markdown/图片资源的断点。确认后的实现语义见 `docs/design/capabilities.md` 与 `docs/design/capabilities/resource.md`。

Stage 1 建立无独立持久状态的 `capabilities.resource` 和 `resource` domain，暴露两个独立 action：

1. `resource.convert_with_markitdown`：普通 PDF/DOCX 与结构化 Markdown 优先路径；
2. `resource.convert_with_pypdf`：PDF 专用页级文本、图片、附件与无文本页面渲染路径。

两个 action 都只读 `source_link` 并提交显式 `target_link` Markdown 与 sibling `.assets/` 资源包；不调用 LLM、不做 OCR、不产生 base64，也不自动串行调用另一个 action。图片/附件以真实 Workspace resource 保存，正文用 canonical Workspace Link 引用；后续 action 读取图片 Link 时才由 Workspace resolver 构造 ImagePart。

Stage 1 已按以下切面完成：

- **Stage 1A Capability Foundation**：`[capabilities]` 配置、基础 DependencyChecker、effective Action Catalog 可用性过滤；
- **Stage 1B Process And Workspace Foundation**：抽取 ControlledProcessRunner；增加 bounded document read 与可回滚 bundle mutation；
- **Stage 1C Resource Actions**：MarkItDown/pypdf/pypdfium2 worker、两个 executor、Catalog、domain HOW、manifest/context sync；
- **Stage 1D Release And Verification**：默认配置/项目模板、package data、模块/Action/App/wheel 测试和文档收口。

验收要求：

- enabled/disabled 与依赖可用性决定 effective Catalog，启用但缺依赖在启动时显式失败；
- worker 只接受 host 生成的临时路径和结构化请求，超时或 Runtime transfer 复用 Action subprocess 进程树终止；
- source、target、图片和附件全程使用 Workspace Link，bundle 失败不留下半成品；
- 无有效文本但成功生成页面图片时返回 `visual_only`/`partial` 摘要和有界 visual Link hint；
- bundle 提交只产生一次 manifest revision 和一次 workspace snapshot signal；
- ActionResult metadata-only，测试与仓库真实 runtime/workspace/Home 隔离。

### 后续 Stage 的确认入口

- **Stage 2**：确认搜索/抓取供应商、凭据配置、网络访问域、robots/重定向策略、来源引用、正文上限、缓存与隐私边界；
- **Stage 3**：确认首批真实项目工作流、每个具名 task 的固定命令模板、工作目录、参数白名单、环境变量、变更范围、审批和回滚语义；
- **Stage 4**：基于真实任务确认 utility 集合，避免建立无使用场景的工具集合；时间工具还需确认业务时区，结构化格式工具需确认输入输出是否通过值或 Workspace Link；
- **Stage 5**：先确认 Home Backlink 的扫描范围与索引策略；Memory 片段检索需再确认数据规模、来源定位协议、embedding/reranker 依赖和 action 命名；
- **Stage 6**：逐个 connector 确认授权、凭据、读写范围和人工审批；交互入口需保持 App-owned 输入/输出边界，不绕过 Runtime/Context/Action 生命周期。

### Home Backlink

Backlink 是待实现的 Home-owned Link 图能力，不放入通用 Infra，也不通过普通字符串搜索冒充已实现能力。建议边界：

- 输入为一个规范 Home top Link；
- 基于 `runtime override/tombstone -> actual fallback` 的 effective Home 查询引用来源；
- 返回有界 source Link、摘要与结果 digest，不返回整库正文；
- 扫描不应仅为查询而把未使用的 actual 文件复制到 runtime；
- 默认只解释 Home 图，不自动跨入 Memory 或 Workspace；
- 渐进资源是否参与扫描、是否建立持久索引，在实现前单独确认。

### Memory 检索增强

当前 `memory.search` 与 `memory.recall` 已是 Memory-owned native Action，并保持现有行为：

- 精确 `<memory:YYYY-MM-DD>` 已知时调用 `memory.recall`，返回完整但受上限约束的单日 Markdown；
- 精确日期未知时调用 `memory.search(query, top_k)`，流式扫描合法日期文档并以“单日文档”为候选，只返回 Link、日期与有界摘要；
- search/recall 的 ActionResult 都进入当前 TurnTrace，不修改 Background；Phase1 只自动加载精确昨日记忆；
- 当前 search 是候选日期发现，不是片段级语义检索。

后续增强应保留上述日粒度入口，并另行设计片段级语义检索：返回有界片段、所属日期 Link 和可验证来源位置，再由 Agent 判断是否 recall 完整单日文档。是否引入持久索引、embedding provider、增量更新和新的 action 名称，应在实现前结合数据规模与真实查询质量确认。

## 每项能力的实施门槛

- 真实用户场景、domain 归属、`use_when`/`avoid_when` 与 effects 已确认；
- 参数 schema 不以自由字符串绕过路径、命令或网络边界；
- 正常失败映射为局部 ActionResult，配置/环境/不变量失败保持模块边界异常；
- 文本、文件、网络响应、运行时长和并发均有明确上限；
- registrar、Catalog handler、executor 和业务 service 的所有权一致；
- 有模块测试、Phase2/Phase3 集成测试和至少一个 App 工作流验收。

## 待确认

Stage 1 已实施并完成配置、依赖、effective Catalog、受控进程、Workspace bundle、双 action、默认模板、wheel 和隔离测试闭环。下一入口为 Stage 2；其余问题保留在“后续 Stage 的确认入口”、Home Backlink 和 Memory 检索增强章节，在进入对应 Stage 时再展开。后续能力不得借已完成的 Stage 1 提前引入网络、任意命令、持久索引或新的长期状态。

Stage 1 closure audit 已进一步完成：PDF 图片/附件提取不得吞掉 asset count/bytes limit；Resource executor 在 bundle commit point 前响应 cancellation/deadline；staged worker 协议错误稳定映射为局部 `worker_protocol_invalid`；嵌套 capability 配置保留精确 key；ControlledProcessRunner 使用临时文件捕获 stdout/stderr 并只构造有界结果投影，不把 projection limit 夸大为子进程硬输出配额。对应回归测试验证超限和取消都不提交 Workspace、不递增 Manifest、不发布同步信号。
