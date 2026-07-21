# 20260715 Done - Agent Capabilities Stages 1-3 Execution Plan

## 状态

status: done (Stage 1 Resource, Stage 2 Web, Stage 3 Script, and shared Workspace inspection completed)

依赖（已满足）：Stage 8 发布与初始化闭环、`20260715-done-default agent home content plan.md`。

## 完成范围

本计划记录基于既有 Action backend mechanism 完成的前三个能力阶段：Resource Conversion、Web Search/Discovery/Fetch、Script Authoring/Supervised Execution，以及跨阶段复用的 Workspace inspection。后续能力与 Script/Shell 共用执行层迁移不再追加到本完成记录。

## 组织边界

1. 具有独立链接、持久化或 runtime/trap 生命周期的能力才建立顶层业务模块；
2. 无独立持久状态的轻量能力放在 `tinysoul/capabilities/<capability>/`，由能力包的 service/client/evaluator 承担业务逻辑，由 `actions.py` 提供 ActionEngine registrar/executor 适配；
3. 通用执行机制继续位于 `tinysoul.action.backends`；capability 不重复实现 subprocess、temporary script、LLM task 或 ActionResult 管线；
4. Catalog 只描述真实 domain/action，空 domain、预留 action、未注册 handler 和通用“执行任意模型脚本”均禁止；
5. 需要硬停止的外部工作使用受控 subprocess/script backend；native 仅承载可协作取消且受信任的进程内逻辑。

## 已完成路线

本计划将 TinySoul 定位为本地、项目作用域内的知识工作 Agent，并已按“取得内容、转换内容、受控脚本执行”的顺序完成以下阶段：

1. **Stage 1 Resource Conversion（done）**：在 Workspace Link 边界内把受支持文档转换为可检查、可作为后续 action reference 的 Markdown 与关联资源；
2. **Stage 2 Web Search, Discovery And Fetch（done）**：提供有界搜索、页面发现和网页读取，返回来源、候选 URL、语义信号或 Workspace Link，不在该阶段引入登录、提交表单或其它写操作；
3. **Stage 3 Code And Script Execution（done）**：建立通过 Workspace/Home resource Link 编写脚本、事务式运行 Python 或 Bash，以及在后续 Cycle 监督长任务的能力；不把模型参数直接拼接为宿主任意命令。

各阶段均形成独立、可使用的能力闭环；新的 Shell、Utilities、Knowledge Retrieval 与 Connector 工作由后续执行计划管理。

跨 Stage 的 Workspace inspection 基础已完成：`workspace.read` 提供显式有界 range/cursor 读取，`workspace.search_text` 提供 file/directory/workspace scope 的确定性字面量定位，`workspace.analyze` 只对 Phase2 选择的明确多 Link 执行一次完整引用分析。read/search 正文使用 Action Catalog 声明的 foldable trace 生命周期，Session 只持久化 compact locator；analyze 使用 standard result 且不携带原始 references。该基础不改变 Stage 4 的 utility 范围，也不提前引入 Stage 5 的持久索引、embedding 或 Memory 片段语义搜索。详细执行记录见 `docs/analysis/20260718-done-workspace inspection search and analyze execution plan.md`。

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

1. **Stage 3A Authoring And Source Model（implemented）**：Script 配置/依赖、两类 source resolver、统一 write/rewrite/patch、显式 promote、domain/action HOW 和 policy；
2. **Stage 3B Transactional Execution（implemented）**：重构可复用 process primitive，实现 Python/Bash run、事务 mirror、diff/bundle commit、局部失败和 Workspace signal；
3. **Stage 3C Supervised Execution Job（implemented）**：在不引入 ongoing Action 的前提下实现 Turn-scoped start/wait/stop/finalize，以及 Cycle pacing、日志/候选产物观察和结束清理；
4. **Stage 3D Release And Verification（completed）**：默认配置与项目模板、effective Catalog、模块/Phase/App/wheel 测试，以及本地真实 Python process smoke；
5. **Stage 3E Integrity And Supervision Hardening（completed）**：修复最终审计发现的源码身份、Cycle 节流、Signal 唤醒、日志 staging、异常清理和旧 backend 组织问题，并通过全量与发布验证。

Stage 3C 的监督语义进一步确认为：

- action 集合以 `script.run_python`、`script.run_bash` 启动运行，以 `script.wait`、`script.stop` 监督进程，以 `script.read_candidate` 有界读取 mirror 内 staged 文本候选，并以 `script.apply`、`script.discard` 显式收尾；所有 run 无论是否在首次等待内结束都不自动提交，统一进入 `ready_to_apply` 后再 apply；
- 默认 `initial_wait_seconds=10`、`min_wait_seconds=5`、`default_wait_seconds=15`、`max_wait_seconds=60`、`max_runtime_seconds=1800`、`max_supervision_cycles=32`。项目配置可以在确定性上下界内收紧；模型只能为单次 wait 请求上下界内的等待时长，不能关闭最小间隔、总时长或 Cycle 配额；
- run 在首次等待内完成时立即返回 terminal/ready 状态；否则返回普通 success ActionResult，payload 中 `job_state=running`。wait 在进程结束、新的同 Turn input/control signal 或请求间隔到期时返回；普通 stdout/stderr 增长不逐条发信号，也不能在最小等待间隔前触发新 LLM 调用；
- 每个 wait 返回自上次 cursor 之后的有界 stdout/stderr delta、下一个 cursor、elapsed/terminal 状态和一次有界 mirror diff metadata。完整日志与大块候选仍留在 job staging；`script.read_candidate` 使用 execution id、staged 相对路径与 cursor/max chars 返回有界 UTF-8 slice，不创建临时 Link namespace；
- 下一 Cycle 始终从 Phase1 开始，不建立绕过三阶段主循环的 job 子循环。Phase3 已将 run/wait/stop/read/apply/discard 的 ActionResult 作为 ToolResultMessage 写入当前 TurnTrace；下一 Phase1 从正常 Context 构造看到最新结果和已合并用户追加输入。job 结果不进入 Background，job manager 内存态仍是权威运行事实；
- 运行中允许 Agent 继续使用非 Script action，并允许修改 active Workspace；mirror apply 以启动时逐文件 baseline digest 做冲突校验，无冲突的不同路径修改可以合并，同路径修改、新文件碰撞或删除冲突局部失败并保留 job 等待 discard。一个 Turn 只允许一个 running/unresolved Script job，因此活动 Python/Bash job 存在时拒绝第二个 run；
- apply 只接受 exit code 0 的 `ready_to_apply` job；failed、timed_out 或 stopped job 只能 inspect/read/discard，不能提交部分结果。apply 成功后返回真实 Workspace Link、清理 mirror 并发布一次 authoritative Workspace snapshot；discard 清理全部 staged 状态且不修改 active Workspace；
- `core.answer` 在存在 running 或未 apply/discard job 时由 Script 注册的 execution admission hook 局部拒绝，避免无意丢失 Turn-scoped 工作。User stop、Turn exhausted/failed、Runtime transfer 和 Program shutdown 则强制终止进程树并 discard；cleanup 失败不能替换原始运行转移；
- Loop 通过通用 Turn activity/continuation SPI 支持监督 Cycle：普通 `max_cycles_per_turn` 耗尽后，只有仍在有效总时长和 `max_supervision_cycles` 内的 active job 才能申请有限额外 Cycle；Loop 不读取 Script job、日志或 mirror。Runtime SignalBus 只提供可等待 generation/wakeup 机制，使 wait 能被同 Turn input/control 信号唤醒，不解释业务信号；
- ActionResult 的 status 表示当前 tool operation 是否成功：running/ready 的 run/wait 是 success；进程非零退出、timeout、策略拒绝、冲突或非法状态使用稳定 failed/timeout 结果，并携带有界 job facts。任何结果都不使用 ongoing Action status。

上述确认完成后，Stage 3 已不存在阻塞 Stage 3A-3D 实施的核心语义待确认项。实现中如平台 process-tree、Bash 可用性或 Workspace bundle 现状暴露新的局部约束，应保持上述业务语义并在对应模块设计文档记录，不通过扩大任意命令或路径权限规避。

Stage 3E 进一步确认以下加固语义：

- policy 校验、promote 写入与 process 实际执行必须绑定同一个不可变 `ScriptSource` snapshot。owner resource digest 用于 Link/CAS 身份；解码后的 snapshot 以固定 UTF-8 字节写入 job `source/` 并生成独立 snapshot digest，process 只执行该 digest 已复核的冻结入口，Workspace mirror 仍是 cwd 和唯一 staged 产物边界。Workspace mirror 创建时也必须复核复制文件与 baseline resource digest；不一致时在启动进程前局部失败。`script.promote` 不得在 policy 校验后按 Link 二次读取源码；
- `max_source_chars` 是 Script-owned 可配置的读写共同边界，约束 read、LLM write/rewrite 输出、patch 后完整候选、promote 和 resolver 最终 mutation。Workspace/Home owner 自有上限继续生效，实际写入上限取所有者边界与 Script 边界中的较小者；
- 新增默认 `cycle_wait_seconds=30`。当 job 仍为 `running` 时，相邻 Agent Cycle 的启动间隔不得小于该值；run 的 initial wait 和 Cycle 内其它耗时计入间隔，不机械叠加完整等待。进程结束可立即进入下一 Cycle；
- 只有当前 Turn scope 下、协议可解析的 `context.input.append` 或 `loop.control.request` 可以提前解除运行中 job 的 Cycle/wait 等待。SignalBus 提供带 cursor/predicate 的 non-consuming wait，不消费业务 Signal；日志增长、其它 namespace、其它 Turn、非法 payload 均不得唤醒，也不得由同一旧 Signal 反复唤醒；
- 完整 stdout/stderr 固定保存在当前 project-scoped `runtime/.staging/script-job-*/logs/`，与 mirror/source 同属一个 job staging。底层 managed process 可接受调用方提供的 capture 目录；同步 subprocess 未提供时继续自行拥有临时 capture。任何日志均不建立 Link、不进入 Workspace Manifest 或 Daily archive；
- Script action 的可修正业务失败收敛为稳定局部 ActionResult；Home runtime copy 与 Workspace Trash restore 继续通过各自精确 Runtime bridge；Workspace/Home IO 或 invariant failure 保持 owner module 语义，不能被泛化为 Script 业务失败。Turn activity cleanup 必须在 `finally` 中 best-effort/no-throw，且不能替换已有 Runtime transfer、异常或进程终止原因；
- 删除旧 inline-code `TemporaryScriptExecutor` 与 `script.temporary` 默认注册。`tinysoul/action/backends/process.py` 只提供受监督进程生命周期原语，不注册到 ActionEngine；`subprocess.py` 提供同步 adapter 和 `subprocess.default` executor；`tinysoul.capabilities.script` 拥有 Script source/job 和 action-specific executor。`backend.kind=script` 仍作为执行分类及进程取消策略，不要求存在同名通用 handler。

Stage 3E 验收必须覆盖 source/mirror digest 竞态、promote 单 snapshot、全部 mutation 的 source 上限、相邻 Cycle pacing、合法/非法/跨 Turn Signal 唤醒、process completion 提前唤醒、统一日志 staging、Turn/Runtime transfer cleanup、删除 `script.temporary`，以及完整 pytest、静态类型检查、wheel 构建和隔离安装验证。

Stage 3E 实施结果：`ScriptSource` 现同时保留 owner resource digest 与固定 UTF-8 snapshot digest，run/promote 不再在 policy 后二次读取源码；Workspace mirror 在复制时复核 baseline 字节，准备期变化局部返回 `workspace_mirror_changed`。`max_source_chars` 已进入 resolver mutation 与 policy 双边界，并由 read、write/rewrite、patch、promote 回归覆盖。SignalBus 新增显式 closeable `SignalWatch`，只在 watcher 存活期间保留 non-consuming emissions；Script 仅以当前 Turn 的合法 input/control parser 唤醒，并按默认 30 秒约束相邻 running-job Cycle。`wait_before_cycle` 与 `allow_additional_cycle` 的内部失败均通过 Script Runtime bridge；Script 配置与 Bash 依赖缺失也保持 `script.configuration_failed` 所有权。完整日志固定在 job staging `logs/`，caller-owned capture 由 job 统一清理；Signal watcher、process 和 staging cleanup 独立尝试，Turn cleanup 位于 `finally` 且错误只形成 Observation。旧 `TemporaryScriptExecutor`/`script.temporary` 已删除，process/subprocess/capability 三层职责已对齐。全量 pytest、`ty`、干净 wheel 构建、隔离安装及旧 backend 文件缺失检查均通过。

Stage 3 当前实施映射如下：

- `tinysoul/capabilities/script/` 已包含 settings/dependency、Workspace/Home source resolver、确定性 source policy、authoring prompt、Action executor 和 Turn-scoped job manager；详细模块语义见 `docs/design/capabilities/script.md`；
- `tinysoul/action/backends/process.py` 提供可被同步 subprocess 与监督 job 共用的 process-group-owned managed process、命名 capture、增量读取和进程树终止；原 `ControlledProcessRunner` 已改为复用该原语；
- `tinysoul/workspace/mirror.py` 提供有界 full mirror、候选 diff/read 和逐文件 baseline commit；`WorkspaceEngine.write_bundle` 已支持 delete digest guard，避免检查与删除之间的同路径竞态；
- package Catalog 已增加 `script` domain 与 11 个 action；默认 `[capabilities.script]` 启用 Python、关闭 Bash，当前项目和 `tinysoul init` 模板都包含对应配置；domain HOW 后续已由新计划统一校正为 `home/how_domain/script/DOMAIN.md`；
- AppBuilder 装配 source resolver、mirror service、job manager 和 registrar；TurnRunner 只通过通用 activity controller 请求有限额外 Cycle，并在 Turn 离开时 cleanup，不读取 Script 业务状态；SignalBus 只增加 non-consuming generation wait；
- 隔离测试覆盖 settings、真实 Python success/failure/stop、显式 apply、同路径冲突、不同路径并发保留、额外 Cycle/cleanup、Catalog/App 和 wheel；Bash 仍按 executable 配置 opt-in，不把开发机存在性硬编码进测试。

## 完成结论

Stage 1 closure audit 已完成：PDF 图片/附件提取不会吞掉 asset count/bytes limit；Resource executor 在 bundle commit point 前响应 cancellation/deadline；staged worker 协议错误稳定映射为局部 `worker_protocol_invalid`；嵌套 capability 配置保留精确 key；ControlledProcessRunner 使用临时文件捕获 stdout/stderr 并只构造有界结果投影，不把 projection limit 夸大为子进程硬输出配额。对应回归测试验证超限和取消都不提交 Workspace、不递增 Manifest、不发布同步信号。

Stage 2 已完成 Kimi Search、同源页面发现、Defuddle/Trafilatura fetch、inline/spill、依赖检测、公开 HTTPS 边界、Workspace artifact 与发布验证。Stage 3A-3E 已完成源码 snapshot 身份、Home/Workspace Link authoring、显式 promote、事务 mirror、Turn-scoped job、Cycle pacing、信号过滤、日志 staging、apply/discard、异常清理和发布验证。

截至本计划关闭时，当前代码仍以 `backend.kind=script` 和 Script-owned job manager 表达监督执行。这是本计划的已实现终点，不是后续共享执行层的最终命名。后续完成的 `supervised_process` 迁移和独立 Shell domain 记录于 `docs/analysis/20260719-done-agent supervised execution and capability expansion plan.md`；Utilities、Knowledge Retrieval 和 Connectors 候选方向已转入 `docs/analysis/20260721 application integration next stage plan.md`。
