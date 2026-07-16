# Web Capability 设计

## 定位

`tinysoul.capabilities.web` 是无独立持久状态的只读外部 Web 能力。它不拥有 Link namespace、缓存、索引或 Runtime/Trap 生命周期；搜索的交互结果进入 TurnTrace，需保留的长结果和网页正文写入现有 `workspace:` 资源。

Web domain 当前暴露三个独立 action：

1. `web.search_by_kimi`：通过独立 Kimi Search provider 取得当前信息，同时返回 `answer` 和结构化 `results`；
2. `web.fetch_with_defuddle`：优先使用本机 Defuddle CLI 提取已知网页；
3. `web.fetch_with_trafilatura`：使用 wheel 基础依赖 Trafilatura 的网页提取 fallback。

两个 fetch action 行为相同但 adapter 的安装方式、提取质量和失败模式不同，因此保留可显式选择的 action，并由 domain HOW 引导优先顺序。它们不会在一次 action 内自动串联或触发新的 Agent cycle。

## Kimi Search 边界

Kimi Search 是 Web capability-owned provider 封装，不是 TinySoul LLM task：

- 不读取 Context、MessageStack、Home HOW 或 `[llm]` provider 配置；
- 独立读取 `[capabilities.web.search_by_kimi]` 和其声明的 `KIMI_SEARCH_API_KEY` 环境变量；
- 在固定 subprocess worker 内执行 Kimi `$web_search` builtin-function loop；
- worker 只接收 query、provider endpoint/model 和各项上限，最终把供应商输出校验为 `{answer, results[]}`；
- `results` 每项固定包含 `title`、`url`、`snippet`，没有 answer/results mode 分支。

Kimi 最终响应先完整校验为 canonical `answer/results`，不在 normalization 阶段按 result 数量或 snippet 长度静默裁剪。`max_result_chars` 是完整 canonical 结果的硬上限，超过时整次 action 局部失败；`max_inline_chars` 只决定交付形态。未超过 inline 上限时完整结果进入 ActionResult；超过 inline 上限时完整 answer/results 写入唯一的 `workspace:web/search/<invoke-id>-<call-id>.md`，ActionResult 返回同一结果的有界 shape-safe preview、完整 `result_count`、`truncated=true`、`see_more_at` 和 usage。preview 可以裁剪 answer、result 数量或 snippet，但所有被裁剪内容都必须存在于 Workspace 文档中。

Kimi Search worker 只获得专用搜索密钥和运行所需的最小进程环境，不继承其它 LLM provider 凭据。provider builtin-function 协议被隔离在 worker 动态边界，供应商协议变化不得扩散到 TinySoul LLM 或 Action 核心。

## Fetch 与提取

Fetch action 接收 `url`、显式 `.md` `target_link`、overwrite 和可选 digest guard。宿主通过固定 worker 完成“网络读取 -> 本地提取 -> staged Markdown”，校验结果后在单次 `WorkspaceEngine.write_bundle()` 中提交。Web 与 Resource 共用 App 装配的项目级 `runtime/.staging/` 根；每次 action 使用唯一子目录，完成、失败或取消后清理，进程中断遗留内容在下次 App 启动时清理。staging 不进入 Workspace Manifest、Daily archive 或 capability 持久状态：

- 只接受公开 HTTPS URL，拒绝 userinfo、localhost 以及解析到非 public IP 的目标；
- 每次跳转重新解析和校验，跳转次数、请求时长、响应 bytes、输出 chars 都有硬上限；
- HTTP client 禁用环境代理、cookie、认证和自动跳转，只接受 HTML/XHTML/plain text；
- HTML 进入 extractor 前把相对 link/image URL 规范化为远程绝对 URL；
- Defuddle 只读取已下载的本地 HTML，不能自行 fetch URL；Trafilatura 也只处理同一 staged HTML；
- Defuddle JSON 在解析前先经过 staged file bytes 上限检查和有界 UTF-8 读取，最终 Markdown 再检查 output chars 上限；
- 图片暂不下载为本地 asset，Markdown 保留远程图片 URL；后续需要查看图片时才由已有加载能力处理；
- 完整正文始终只写 Workspace，ActionResult 返回 Markdown Link、extractor、title、有限 excerpt、字符数、远程图片计数和 warning code，不返回原始 URL 或完整正文。

Defuddle 是可选 executable，默认关闭；启用时 `DependencyChecker` 必须在 App 启动期找到 `defuddle`。Trafilatura 是 wheel 基础 Python 依赖并默认启用。启用但缺依赖属于 App 装配失败；启动后 executable 被移除、网络失败、HTTP 状态、内容类型、资源超限或 extractor 失败属于单次局部 ActionResult。

## 不可信内容和失败

Search answer/results、网页正文、title、snippet 和远程链接都属于不可信外部数据。Web capability 不执行网页脚本、不遵循正文指令、不登录、不提交表单，也不把抓取内容升级为 system/guide prompt。模型只能在普通 interaction result 或 Workspace reference 中读取这些内容。

worker 超时或 Runtime transfer 通过 `ControlledProcessRunner` 终止进程树；commit point 前再次检查 cancellation/deadline。worker 非零退出、无效 JSON、staged path 越界或字段不满足协议收敛为稳定局部失败，并且不得提交 Workspace 或发布 snapshot signal。搜索/抓取的原始异常、绝对路径、密钥、worker stderr 和供应商原始响应不进入模型反馈。

## 后续边界

Crawlee、站点 crawl、robots 策略、页面队列、去重和 crawl budget 属于后续 Stage 2B。它们不能通过放宽当前单页 fetch 入口隐式加入，也不要求新增 backend kind；只有真实 crawl 语义确认后才扩展 Web-owned service/worker 和具名 action。
