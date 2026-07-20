# Web Capability 设计

## 定位

`tinysoul.capabilities.web` 是无独立持久状态的只读外部 Web 能力。它不拥有 Link namespace、缓存、索引或 Runtime/Trap 生命周期；搜索的交互结果进入 TurnTrace，需保留的长结果和网页正文写入现有 `workspace:` 资源。

Web domain 当前暴露四个独立 action：

1. `web.search_by_kimi`：通过独立 Kimi Search provider 取得当前信息，同时返回 `answer` 和结构化 `results`；
2. `web.discover_pages`：从一个 seed 页面发现可进一步访问的同源候选 URL，并可有界递归访问以补充确定性页面信号；
3. `web.fetch_with_defuddle`：优先使用本机 Defuddle CLI 提取已知网页；
4. `web.fetch_with_trafilatura`：使用 wheel 基础依赖 Trafilatura 的网页提取 fallback。

两个 fetch action 行为相同但 adapter 的安装方式、提取质量和失败模式不同，因此保留可显式选择的 action，并由 domain HOW 引导优先顺序。它们不会在一次 action 内自动串联或触发新的 Agent cycle。

## Kimi Search 边界

Kimi Search 是 Web capability-owned provider 封装，不是 TinySoul LLM task：

- 不读取 Context、MessageStack、Home HOW 或 `[llm]` provider 配置；
- 独立读取 `[capabilities.web.search_by_kimi]` 和其声明的 `KIMI_SEARCH_API_KEY` 环境变量；
- 在固定 subprocess worker 内执行 Kimi `$web_search` builtin-function loop；worker 先把 SDK message 转为动态 JSON，再按 Kimi 协议解释 builtin call，不依赖 OpenAI SDK 面向普通 function 的静态 tool-call 类型；
- worker 只接收 query、provider endpoint/model 和各项上限，最终把供应商输出校验为 `{answer, results[]}`；
- `results` 每项固定包含 `title`、`url`、`snippet`，没有 answer/results mode 分支。

Kimi 最终响应先完整校验为 canonical `answer/results`，不在 normalization 阶段按 result 数量或 snippet 长度静默裁剪。`max_result_chars` 是完整 canonical 结果的硬上限，超过时整次 action 局部失败；`max_inline_chars` 只决定交付形态。未超过 inline 上限时完整结果进入 ActionResult；超过 inline 上限时完整 answer/results 写入唯一的 `workspace:web/search/<invoke-id>-<call-id>.md`，ActionResult 返回同一结果的有界 shape-safe preview、完整 `result_count`、`truncated=true`、`see_more_at` 和 usage。preview 可以裁剪 answer、result 数量或 snippet，但所有被裁剪内容都必须存在于 Workspace 文档中。

Kimi Search worker 只获得专用搜索密钥和运行所需的最小进程环境，不继承其它 LLM provider 凭据。provider builtin-function 协议被隔离在 worker 动态边界，供应商协议变化不得扩散到 TinySoul LLM 或 Action 核心。

Kimi builtin tool round 以 `finish_reason=tool_calls`、精确 `$web_search` 名称、非空 call id 和字符串 arguments 共同校验。官方 `builtin_function` 与端点/SDK 可能对同一 `$web_search` 产生的普通 `function` 归一化都可接受，但不能因此接受其它 function。每轮完整 assistant JSON 原样回放，保留存在时的 `reasoning_content` 和供应商扩展字段；tool result 使用供应商返回的原始 arguments 字符串，只另外解析副本执行 JSON 与 search token 上限检查。已知不兼容 `$web_search` thinking 的 K2.5/K2.6 请求显式关闭 thinking，其他模型不增加该 provider option。

动态协议失败可以从 worker 返回有界 shape facts，例如 call type、function/name/arguments 是否存在、是否携带 reasoning content；宿主只允许这些字段和稳定 error type 穿过 subprocess 边界。原始 provider response、arguments、reasoning 正文、密钥与 traceback 始终不得进入 ActionResult 或 Trace。模型可见的失败处置语义仍由 Web Action 单独定义，不由 worker 或通用 Action 核心推断。

Web Action 把稳定 failure reason 映射为 capability-owned 模型恢复方向，并在失败或 timeout 的模型可见 payload 中固定返回 `{failure: {reason, disposition}}`。`disposition` 使用 Web 自有 `StrEnum`，只包含 `retry_same`、`change_request`、`use_fallback` 和 `stop`。HTTP 状态和 provider error type 等有界 facts 只用于本地分类与 trace 诊断，不复制进模型 payload。只有明确的暂时网络/DNS、HTTP 408/425/429/5xx 和已知瞬时 provider error 才是 `retry_same`；参数、URL、安全范围和资源上限问题是 `change_request`；provider/extractor 协议和可替代处理失败是 `use_fallback`；凭据、依赖、worker/Workspace 环境失败及未知原因保守为 `stop`。

该协议不实现自动重试、不保存 provider health、不改变 ActionResult 通用类型，也不强制 Loop 转移。Web domain HOW 负责解释模型应如何消费 disposition：原样重试仅允许一次有界瞬时恢复；`change_request` 必须实质修改调用；`use_fallback` 不得重复同一调用；`stop` 在当前 Turn 停止使用受影响能力。已有证据足够时应继续用户目标，而不是为了尝试其它 Web action 继续扩展检索。

## Page Discovery 边界

`web.discover_pages` 接收 `start_url`、可选 `max_visit_depth` 和有界 path glob include/exclude。它返回 seed 的 title/meta description/H1/canonical，以及去重候选 page 的 URL、depth、visited/candidate/failed 状态、首次来源 URL、anchor text、link title、rel 和访问后可取得的页面 metadata。上述字段是确定性 DOM/HTTP 信号，不包含 LLM 生成的推荐、分类或摘要。

`max_visit_depth=0` 是默认语义：只访问 seed，直接 outgoing pages 作为 candidate 返回，不访问候选。更大 depth 只能在项目配置硬上限内使用；被递归访问的候选可补充页面 metadata，并继续发现下一层 frontier，因此之后由 Agent 选择 fetch 时可能再次下载同一页面。Discovery 与 Fetch 是两个不同 Agent Cycle 中的显式行动，不在 action 内自动串联。

Crawlee 只拥有 action-scoped `BasicCrawler`、Memory RequestQueue、URL 去重、重试、并发/速率和运行统计；不使用 Crawlee 默认 HTTP client、browser、storage persistence 或自动 `enqueue_links` 网络路径。每个实际 seed/递归页面和 robots 请求继续通过 Web-owned 公开 HTTPS 下载边界，redirect 后仍必须处于 seed same-origin。候选只来自 `<a href>`，fragment 被移除；query link 默认不扩散，include/exclude 只解释为有界 path glob。robots 强制遵守，模型不能关闭。Discovery 不执行脚本、表单、下载、登录或跨域访问，不建立缓存或跨重启 resume。

完整 discovery canonical result 先受 candidate/page/字段长度与 `max_result_chars` 硬上限约束；不在形成 canonical result 前静默裁剪 candidate。未超过 `max_inline_chars` 时完整进入 ActionResult；超过时完整 JSON 写入 `workspace:web/discovery/<invoke-id>-<call-id>.json`，ActionResult 返回同一 shape 的有界 preview、完整计数、`truncated=true`、`see_more_at`。除 overflow JSON 外，Discovery 不写 Workspace，也不保存访问页面正文。结果 URL 和 metadata 都是不可信 interaction data，后续 fetch 必须重新执行完整 URL/network 校验。

Crawlee 是 `web-crawl` wheel extra 和开发测试依赖，项目模板默认禁用 Discovery；启用前应安装 `tinysoul[web-crawl]`。当前支持并约束 `crawlee>=1.8,<2`，避免主版本动态协议变化直接进入 worker。启用 action 但当前解释器缺少 Crawlee 时，App 在 effective Catalog 装配期显式失败。

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

Playwright/browser rendering、跨域 discovery、sitemap loader、持久 RequestQueue、缓存、跨重启 resume、WARC 和自动整站正文提交不属于首版 Page Discovery。它们不能通过扩大 `web.discover_pages` 参数隐式加入，也不要求新增 backend kind；出现真实场景时应增加清晰 action 或独立设计长期状态边界。
