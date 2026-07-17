# 20260715 Agent Capabilities And Action Expansion Plan

## 状态

status: in_progress (Stage 1 and Stage 2 done; Stage 3 baseline confirmed, supervision design in progress)

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
2. **Stage 2 Web Search, Discovery And Fetch（done）**：提供有界搜索、页面发现和网页读取，返回来源、候选 URL、语义信号或 Workspace Link，不在该阶段引入登录、提交表单或其它写操作；
3. **Stage 3 Code And Script Execution（baseline confirmed）**：建立通过 Workspace/Home resource Link 编写脚本、事务式运行 Python 或 bash，以及在后续切面监督长任务的能力；不把模型参数直接拼接为宿主任意命令；
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

### Stage 2 Web Search, Discovery And Fetch

Stage 2 已建立无独立持久状态的 `capabilities.web` 和 `web` domain，确认后的详细语义见 `docs/design/capabilities/web.md`。当前 action 为：

1. `web.search_by_kimi`：独立于 TinySoul LLM task/provider/Context 的 Kimi `$web_search` 封装，结果固定同时包含 Markdown `answer` 和结构化 `results`，不提供 mode；
2. `web.discover_pages`：从一个公开 HTTPS seed 返回同源候选页面，并可在配置上限内递归访问以补充确定性页面信号；
3. `web.fetch_with_defuddle`：已知 URL 的优先本地提取路径，依赖可检测的可选 Defuddle CLI；
4. `web.fetch_with_trafilatura`：同一 fetch 语义的基础 Python fallback。

已落实边界：

- Kimi Search 使用独立 `[capabilities.web.search_by_kimi]` 与 `KIMI_SEARCH_API_KEY`，不复用 `[llm]` 配置、MessageStack 或内部 LLM task；
- search 先保留完整 canonical answer/results；未超过 inline 上限时完整进入 interaction ActionResult，超过 inline 上限时完整规范化结果写入 `workspace:web/search/<invoke-id>-<call-id>.md`，返回 shape-safe preview 与 Link；result/snippet 不在 spill 判断前静默裁剪；
- fetch 只接受公开 HTTPS，逐跳校验 DNS/redirect，限制请求时长、source bytes、redirect 和 output chars，禁用环境代理、cookie 与认证；
- 两个 fetch action 都由 Web worker 统一下载并规范化相对链接，Defuddle/Trafilatura 仅处理 staged HTML；正文总是提交到显式 Workspace Markdown target；
- 图片只保留远程绝对 URL，不下载 `.assets/`；ActionResult 只含有界 excerpt 和 artifact metadata，不调用 LLM；
- 四项 action 分别 enabled/依赖检查/effective Catalog 过滤；Defuddle executable 检测扩展了通用 DependencyChecker；worker 复用 ControlledProcessRunner 并使用最小环境传递专用搜索密钥；
- Web 与 Resource 中间文件共用 `runtime/.staging/`，App 启动清理遗留子目录，action 作用域结束清理当前唯一子目录；该根不进入 Workspace Manifest 或 Daily archive；
- Catalog、domain HOW、默认项目配置、`.env.example`、wheel package data 和隔离测试已闭环。

Stage 2B 已完成 Page Discovery，而不是自动持久化整站正文。`web.discover_pages` 访问一个公开 HTTPS seed，返回该页面可进一步访问的同源候选 URL；可选的 `max_visit_depth` 在配置硬上限内让 Crawlee 递归访问候选并补充 title、meta description、H1、canonical、来源 anchor 等确定性信号。Discovery 不调用 LLM、不自动调用 fetch、不保存访问页面正文；Agent 在后续 Cycle 根据 ActionResult 决定是否调用现有 Defuddle/Trafilatura fetch。Crawlee 只提供 action-scoped RequestQueue、去重、重试和有界调度，实际下载继续使用 TinySoul 的公开 HTTPS/redirect/bytes 边界。默认 depth 为 0、scope 固定 same-origin、robots 强制遵守、query link 默认不扩散，不建立缓存、跨重启 resume 或长期 Crawl 状态。完整 canonical discovery result 受硬上限约束；超过 inline 上限时完整 JSON spill 到 `workspace:web/discovery/<invoke-id>-<call-id>.json`，ActionResult 返回有界 preview 与 `see_more_at`。Catalog、domain HOW、独立 Crawlee 依赖检测、默认项目配置、inline/spill、Workspace signal、相对链接解析、硬 page budget 与可选真实网络 smoke test 均已形成验收闭环。

### Stage 3 Code And Script Execution

Stage 3 已确认以下设计基线：

- Script 是独立 action domain；业务 executor、source resolver、policy、事务 Workspace mirror 和后续 execution job manager 位于 `tinysoul.capabilities.script`。通用进程启动、捕获、取消、deadline 和进程树回收继续复用或重构 `tinysoul.action.backends`，capability 不复制底层 subprocess 机制；
- 临时脚本使用真实 Workspace Link，例如 `workspace:scripts/analyze-data.py`；长期脚本使用既有 Home progressive resource Link `home:how/<skill>/scripts/<script>.py|.sh`，并要求目标 `home:how@<skill>` 已存在。两者不增加平行的 location/lifetime 参数；
- 长期脚本始终通过 Agent Home effective view 读取和修改，执行 runtime override 或 lazy copy，不绕过 overlay 直接读写 actual Home；
- Workspace 临时脚本只有经过显式 `script.promote` 才复制到一个已存在通用 HOW 的 runtime `scripts/`。Home Maintenance 仍只 review active runtime Home 与 actual Home，不扫描 Workspace；promote 形成的 runtime diff 后续按现有 Home Maintenance apply/discard 语义处理。通用 HOW 创建 action 属于后续能力，不由 promote 隐式创建；
- 脚本不直接修改 active Workspace。每次运行基于已 reconcile Workspace 建立 action/job-scoped 事务 mirror，以该 mirror 为 cwd；完成后计算有界 diff，并只通过 WorkspaceEngine 的 bundle mutation 提交。失败、超时、停止、越界或冲突不得把 mirror 的部分结果写入 active Workspace；
- 首版安全等级固定为“事务隔离 + 策略检查”，明确不宣称针对恶意 Python/Bash 的 OS 硬沙箱。Action hook 可做参数、Link、语言、配额与准入检查；Script service 必须对固定 digest 的源码执行语法/策略检查，并使用最小环境、`shell=False`、无交互 stdin、硬 timeout 与进程树终止；
- Python 默认启用；Bash 是按 executable 检测的独立可选能力。Python 与 Bash 使用不同 run action 和 effective Catalog availability，但共享 source/mirror/policy/result 协议；
- execution job 默认 Turn-scoped、不跨重启，同一 Turn 最多一个 `running` job。启动、等待、停止或收尾它的每个 Action 仍须在所属 ActionBatch 内收敛，不能恢复旧式 `ONGOING Action`；Turn/Program 结束必须终止进程树并清理未提交 mirror；
- 脚本正文、完整 stdout/stderr 和运行中大块产物不直接进入 TurnTrace。ActionResult 只返回状态、source Link/digest、execution id、日志游标/有界片段、staged 候选产物的有界路径/metadata、diff/count、冲突或提交摘要；候选产物在 apply 前不是可加载的 `workspace:` Link，成功提交后才返回实际 Workspace Link，并只发布一次 authoritative Manifest snapshot signal。

建议按四个实施切面推进：

1. **Stage 3A Authoring And Source Model**：Script 配置/依赖、两类 source resolver、统一 write/rewrite/patch、显式 promote、domain/action HOW 和 policy；
2. **Stage 3B Transactional Execution**：重构可复用 process primitive，实现 Python/Bash 同步 run、事务 mirror、diff/bundle commit、局部失败和 Workspace signal；
3. **Stage 3C Supervised Execution Job**：在不引入 ongoing Action 的前提下实现 Turn-scoped start/wait/stop/finalize，以及 Cycle pacing、日志/候选产物观察和结束清理；
4. **Stage 3D Release And Verification**：默认配置与项目模板、effective Catalog、模块/Phase/App/wheel 测试，以及 opt-in 的本地真实 Python/Bash smoke。

Stage 3C 进入实现前仍需确认：运行 action 首次让出控制的等待时间、后续 wait 的最小/最大间隔与唤醒条件；运行中 mirror 是否允许其它 action 读取或修改；完成/停止后由哪个 action apply/discard；job 状态如何稳定投影给下一 Cycle；Turn 输出、停止、耗尽和 Runtime transfer 对活动 job 的强制清理顺序。上述策略不得改变 Phase1/Phase2/Phase3 的一般职责，也不得让 Runtime 核心解释脚本正文或 Workspace diff。

### 后续 Stage 的确认入口

- **Stage 3**：固定基线已确认；实施前继续收敛 supervision pacing、运行中可见性、apply/discard 和 Turn cleanup 的剩余语义；
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

Stage 1 与 Stage 2 已完成，Stage 3 的 source/lifecycle/transaction/safety/language 基线已经确认，当前只继续确认监督式 execution job 与 Cycle 的协作语义；Stage 3 不沿用此前“固定测试/构建工作流”的假设。其余问题保留在“后续 Stage 的确认入口”、Home Backlink 和 Memory 检索增强章节，在进入对应 Stage 时再展开。后续能力不得借已完成阶段提前引入持久索引、新的长期状态或未确认的宿主任意命令执行。

Stage 1 closure audit 已进一步完成：PDF 图片/附件提取不得吞掉 asset count/bytes limit；Resource executor 在 bundle commit point 前响应 cancellation/deadline；staged worker 协议错误稳定映射为局部 `worker_protocol_invalid`；嵌套 capability 配置保留精确 key；ControlledProcessRunner 使用临时文件捕获 stdout/stderr 并只构造有界结果投影，不把 projection limit 夸大为子进程硬输出配额。对应回归测试验证超限和取消都不提交 Workspace、不递增 Manifest、不发布同步信号。
