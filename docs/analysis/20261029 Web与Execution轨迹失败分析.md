# Web 与 Execution 轨迹失败分析

日期：2026-10-29。HTML 规范化与相关异常分类已修复并验证；Execution 形态、编码与网络适配保留分析和待讨论建议，不表示已确认实施。根据维护者补充，最后一次停止由其手工发起。

依据：[AGENTS.md](../../AGENTS.md)、[Web 设计](../design/capabilities/web.md)、[Execution 设计](../design/execution.md)、当前实现与 [2026-10-28/2 原始轨迹](../../reference/traces/turn-trace-2026-10-28-2.zip)。

分析从正常能力链路出发，以轨迹定位现象，用代码和独立复现确认原因。改进应保护通用能力契约，不把本次网址、调用顺序、脚本或模型输出固定成新规则。

## 结论与证据范围

主要 Web 故障来自共用 HTML 处理代码调用了不存在的 lxml 方法；宽泛异常捕获又把编程错误转换成了外部页面错误。Execution 的几类失败原因不同：未启用的解释器、违反 command/source_ref 契约、选错解释器，以及最后一次执行的停止。导出结果将最后一次调用归类为 timeout，但维护者明确说明实际进行过手工停止，不能仅据导出分类认定停止来源。轨迹不能支持最终回答中“出站 HTTP 普遍受限、不是 web 动作本身的问题”的归因。

ZIP manifest 记录 18 个 Cycle、36 次 LLM Task、630 个 Observation，未标记窗口截断。它不是运行目录备份，不含完整进程日志、DNS 结果、网络配置或原始 HTTP 响应。Action result 文件主要是执行摘要；进程失败的详细 payload 可在后续 LLM request 的 `action_result` 消息中找到。未执行的工具意图不计作实际 Action。

以下 ZIP 内路径均相对于 `turn-trace-2026-10-28-2/`。

| 对象 | 实际结果 | 主要证据 |
| --- | --- | --- |
| Kimi Search | 2 次成功 | Cycle 3、13 的 Action result |
| Web Fetch / Discovery | 18 次失败：12 次 invalid_html、3 次 network_request_failed、2 次 private_network_target、1 次 unsupported_url_scheme | Cycle 4–9、14 的 Action result |
| execution.run | 9 次结果：5 次 invalid_request、2 次参数归一化失败、1 次 process_failed、1 次 timeout | Cycle 10、11、14、17 的 Action result |
| Phase 协议 | Cycle 12、16 的 Phase2 和 Cycle 15 的 Phase1 失败；相应意图未进入执行 | 对应 `cycle.json` 的 lifecycle |

## 当前能力与失败链路

Web Fetch 正常流程是 Service 准备受控 worker，worker 下载并规范化 HTML，选定提取器只处理已经下载的内容，再由 Workspace 提交 Markdown。Defuddle 和 Trafilatura 共用下载与规范化路径；Discovery 也使用同一下载函数。Kimi Search 则在独立供应商搜索链路中取得结果，不经过本机 HTML 规范化。

Web owner 用 `WebProcessingError` 表达整理后的局部失败，worker 返回有限协议，Service 解释结果，Action 按 reason/facts 选择 disposition。Workspace 的无法继续的 owner 失败仍通过 Workspace bridge 处理。这条所有权结构可以保留；当前问题集中在共用处理函数和失败分类。

Execution 将显式解释器与 command/source_ref 转为真实进程。run 在当前 Action 等待，start 返回可跨 Cycle 监督的 Job；两者使用相同 ProcessJobBackend。Action runner 持有调用总时限，Job owner 持有进程监督与保留结果，Workspace 持有实际文件。此次分析未发现需要另建执行循环或恢复状态机的证据。

## 已确认：共用 HTML 规范化调用错误

状态：`done`。实现位置：[network.py](../../tinysoul/plugins/capabilities/web/backends/network.py)。

修复前，`normalize_html_links()` 调用：

```python
document.make_refs_absolute(base_url, resolve_base_href=True)
```

本地安装的 lxml 6.1.3 的 HtmlElement 没有该方法，实际 API 是 `make_links_absolute()`。修复前的本地复现确认：完整有效 HTML、普通 HTML 片段、纯文本均在该调用处产生 AttributeError，并被转换成 `invalid_html`。

初次分析用 httpx.MockTransport 返回 HTTP 200、`text/html; charset=utf-8` 和含相对链接的有效页面，调用真实 `fetch_public_page()`，得到相同失败；内存替换为正确 API 后，同一请求成功。此次已正式恢复正确调用，验证相对链接转为绝对 URL，并通过开发代理调用真实 `fetch_public_page()` 成功取得 example.com HTML。两个 Fetch 与 Discovery 共用此修复，不需要分别增加补偿路径。

Git 历史进一步定位到 `d56aff3a`（2026-10-07）：项目统一引用命名时，将第三方方法 `make_links_absolute` 改成了 `make_refs_absolute`。这项修改早于本次轨迹。项目内部使用 ref 的命名规约不能改变外部库协议。

调用链能够解释轨迹的共同表现：

- Fetch 的下载函数在进入任何 extractor 前就会调用该函数，因此切换 Defuddle / Trafilatura 无法避开此缺陷。
- Discovery 的 page_fetcher 使用同一函数；失败处理保留 reason，最终返回 `Discovery seed could not be visited`。
- Kimi Search 不经过该函数，两次搜索成功与抓取失败可以同时成立。

轨迹没有保存每个页面的原始响应或异常链，因此不能逐项证明所有历史页面原本都有效；但当前缺陷是确定性的，覆盖这些能力的共用前置路径，也与跨网站的失败分布一致。不能把它归结为多个网站同时返回坏 HTML。

## 已确认：异常分类掩盖了实现错误

状态：`done`。实现位置：[network.py](../../tinysoul/plugins/capabilities/web/backends/network.py)、[worker.py](../../tinysoul/plugins/capabilities/web/backends/worker.py)、[discovery.py](../../tinysoul/plugins/capabilities/web/backends/discovery.py)；设计同步至 [Web 设计](../design/capabilities/web.md)。

修复前，`normalize_html_links()` 把解析、调用方法和序列化包在一个 `except Exception` 中，全部归为 `invalid_html`；[errors.py](../../tinysoul/plugins/capabilities/web/errors.py) 再将它映射为 `use_fallback`。于是“本地实现调用不存在的方法”被投影成“页面无法处理，可以换提取器”。这直接削弱了模型后续选择的依据。

这次异常没有附加 error_type。Discovery 的 `_PageState` 只保留 failure_reason，seed 失败又被概括成通用反馈。原始异常链留在 worker 内，导出的局部结果不足以区分页面解析问题与本地编程错误。

本次修改将 HTML 解析处的捕获收窄为 lxml 已知解析异常与其输入 ValueError；未知错误交给固定 worker 边界，返回已有 `worker_failed` 和有限 `error_type`，沿既有 Action 映射使用 `stop`。Discovery 的未知页面处理错误也归为 `worker_failed`，不再泛化为 `page_visit_failed`；可预期的 WebProcessingError 仍保留 owner 原因。`stop` 是当前失败的处置语义，不直接触发 Runtime 结束 Turn。

这些改动保留了局部结果、模块边界与 Runtime 转移的分工，不增加恢复层。开发依赖新增 `types-lxml`，用于检查第三方方法与明确异常类型；运行依赖未增加。这不能替代实际 API 行为验证，但能让同类不存在的方法不再只靠运行时发现。

## 其余 Web 失败的可确认范围

状态：`pending`（历史环境原因未证实；当前开发环境的独立验证见后文）。

| reason | 当前代码表达的事实 | 本轨迹不能推出的结论 |
| --- | --- | --- |
| network_request_failed，3 次 | 下载过程捕获 HTTP、OS 或 Unicode 相关异常并归类；出现于 example.com 两次、example.org 一次 | 测试域名被过滤、具体代理错误、TLS 错误或全局断网 |
| private_network_target，2 次 | 对 wikipedia/raw.githubusercontent 的 URL 检查拒绝了本地解析出的非 global 地址 | 目标站点本身是私网、一定误判、一定是代理 fake-IP 或 DNS 污染 |
| unsupported_url_scheme，1 次 | 模型传入 http://，当前 Web 入口只接受 HTTPS | HTTPS 页面抓取失败的根因 |

这些失败早于或独立于 HTML 规范化，应与已确认代码缺陷分开处理。本地 DNS 校验与显式代理解析可能存在实际部署适配问题，但 ZIP 没有保留地址和有效网络配置；若继续调查，应在原运行环境对照既有 Infra 网络配置与真实解析结果。不应依据本次现象直接放宽全部地址校验，或增加猜测性的自动网络切换。

## Execution：逐类归因

### 未启用的 bash 与 Python command

Cycle 10 五个请求都选择 bash；运行世代只启用了 python、powershell、cmd，Engine 在进程启动前拒绝。并非 bash 已运行后 curl 失败。

Cycle 10 的 `phase2/llm/tasks/001/request.json` 中，工具说明已经写明：`Available in this runtime: python, powershell, cmd`，并说明 inline command 用 powershell/cmd，Python 用 source_ref。不能将这些失败归因于系统未提供可用解释器信息。

五个 bash 调用由同一次 Cycle 10 Phase2 响应一起生成，属于同一批次。即使批次串行执行，Action 之间也没有新的模型决策。Cycle 11 的 Phase1 和 Phase2 请求都包含这五条完整 `action_result`，明确反馈 bash 未启用、列出三个可用解释器，并给出 `invalid_request / change_request`。随后模型已改选 Python。因此，这里是同批次重复选择不可用能力，不是收到失败后跨 Cycle 继续重试 bash，也不是 Trace 丢失反馈。

代码链路为 Execution Action 构造局部失败 → [Phase3](../../tinysoul/kernel/loop/phases/phase3.py) 渲染 ActionResult 并发送 Trace signal → Context 安装 TurnTrace → 下一次主循环请求重新装配。轨迹和实现两者相符，无需为本次五个调用增加特殊重试上限或批次恢复状态。

Cycle 11 两个请求使用 `interpreter=python` 与 `command`。Catalog 的 command 分支仅允许 shell，source_ref 分支才允许 Python，因此归一化阶段拒绝，没有进程启动。它符合当前明确契约。

工具的静态 schema 表达全部受支持身份，动态提示表达本世代可用身份，这是当前设计的选择。示例仍有 bash 偏向，可以做语义一致性整理；此次证据不要求改变解释器协议、自动猜测语言或新增按扩展名强制匹配的限制。

### 使用 cmd 解释 Python 源码

Cycle 14 请求明确指定 `interpreter=cmd`、`source_ref=workspace:scripts/net_test.py`。[ExecutionEngine](../../tinysoul/plugins/execution/engine.py) 读取源码快照，按所选解释器生成脚本副本与 argv，故 Python 文本被复制为 CMD 脚本并交给 cmd。

Cycle 15 的 `phase1/llm/tasks/001/request.json` 保留了此结果的完整模型 payload：Job `20261028-2-1`、reason `nonzero_exit`、exit_code `255`，stdout 显示逐行执行 `import socket`、`URLS = [`，stderr 包含 import 命令无法识别。足以确认语言与解释器不匹配；这里没有完成 Python 网络探测。

### 最后一次执行与手工停止

Cycle 17 改为 `interpreter=python` 与既有 source_ref，确实启动 Job `20261028-2-2`。导出记录随后给出 `execution_timeout`、`timeout_seconds=70`，调用记录间隔约 70.1 秒；下一 Cycle 的 Jobs 投影为 cancelled，最后一轮以 answered 结束。维护者补充最后一次停止为手工操作，应作为分析事实保留。

该 ZIP 没有保留对应原始停止请求，不能据此还原手工停止与 Action deadline 的先后或映射关系。先前直接把最后一次结束认定为自动超时不够准确；目前只能确认“发生手工停止，导出结果记录为 timeout”，不能由此认定网络等待耗尽了全部时间，也不能确认停止分类是否存在另一个实现问题。

脚本顺序执行 5 次 DNS 查询、5 个带 15 秒超时的 HTTPS 请求，以及 5 个带 10 秒超时的 TCP 探测；这些操作没有统一的脚本预算，DNS 也未由该脚本设置总时限。它在结构上可能长于 70 秒，但这只是能力使用分析，不是本次实际等待原因的证明。ZIP 未包含第二个 Job 的 stdout/stderr 正文，也没有后续 collect，不能确定它具体停在哪一步。

已有 start / wait / collect 能表达这类时长不确定的执行。可以直接使用这些能力或缩小诊断工作量，无需为网络诊断设计独立执行通道。结束本轮也不要求完成所有诊断，只应准确说明已知与未知。

### Phase 拒绝不等于 Execution 失败

Cycle 12 使用当前 scope 未提供的 `workspace_write`；Cycle 15 在 Phase1 调用业务 Action `workspace.write`；Cycle 16 未选择 workspace 域却生成 workspace.write。对应 PhaseFailure 都明确说明未接受或执行相应响应的意图。不能把其中的 Python／PowerShell 调用算作真实进程尝试；当前下一完整 Cycle 的反馈路径符合规约。

## Execution 形态与抽象取舍

状态：`pending`（建议保留直接 Python；未调整协议或解释器实现）。

当前四个 interpreter 不是四套执行系统。ExecutionEngine 负责资源解析、解释器可用性、argv 和进程环境；ProcessJobBackend 与 JobRegistry 统一监督。command 是 shell 程序，source_ref 是交给指定解释器的源码快照，选定的 interpreter 决定快照后缀和启动方式。它不表示“用该 shell 去启动引用文件所属的另一种语言”。

Python 作为直接脚本入口，与 shell 并列是合理的能力分类：它省去 shell 引号解析，稳定使用配置的 Python executable、独立 args 和 Python 网络覆盖。shell 内启动 Python 已经可行，子进程会继承同一有效环境，不需要新增专门桥接层。

| 选择 | 能力和代价 | 改动范围 |
| --- | --- | --- |
| 保留直接 Python，允许 shell 调用程序 | 两种真实用途并存；复用现有 Job/进程生命周期。需要让示例和工具说明清楚表达 command/source_ref 的区别 | 当前已有能力；语义整理较小 |
| 只保留三种 shell，模型自行构造 Python 命令 | 工具表面少一个身份；Python 路径、引用到物理文件的转换、引号和参数语义转入 shell 命令，失去直接 Python 的独立网络配置入口 | 删除分支不大，但 enum、配置装配、run/start schema、正式配置/说明和测试均需同步，属跨层协议调整 |
| shell-only，但继续由框架保证 Python executable/source_ref/args | 保留脚本能力，又需要按平台构造 shell 包装命令；多数现有 Python 职责仍存在 | 不是简单删除 Python，可能增加包装和引用处理复杂度，缺少当前收益 |

独立复现还发现现有 CMD command 的引号问题：使用 Engine 实际生成的 argv 启动时，`python <不含空格的路径>` 可启动；`python "<同一路径>"` 出现带字面量引号的非法文件名，带引号的 Python executable 也无法识别。当前 Python subprocess 对列表参数的 Windows 转义与 `cmd /S /C` 的命令文本解析存在不匹配。这不是本次轨迹的起因，但在扩大 shell 调用职责前应单独修正，不宜把直接 Python 全部迁移到该路径。本次只记录该问题，未修改启动协议。

建议保留统一 Engine 与现有脚本入口，先整理能力表达，并单独处理已经复现的 shell 引号和编码问题。不增加语言猜测、扩展名禁用规则或每种解释器一套 Job 抽象。

## 编码问题与建议边界

状态：`pending`（已复现；未实施）。

[infra/process/managed.py](../../tinysoul/infra/process/managed.py) 的 `_read_text()` 固定按 UTF-8、errors=replace 读取输出；轨迹第一个 Job 的 stderr 已含 360 个 U+FFFD。原始字节未保存在 ZIP 中，已替换的字符无法从该导出恢复。此问题影响解释，不是 exit 255 的起因。

受控进程把 stdout/stderr 接到二进制文件句柄，Popen 的 `text=True, encoding="utf-8"` 不会转换子进程直接写入这些文件的字节。`PYTHONIOENCODING` 只控制 Python，不能统一 shell 和原生程序。

在当前主机的真实 ManagedProcessRunner 下，CMD 的未知命令中文诊断可按 CP936 正确读取，固定 UTF-8 读取产生 34 个替换字符；同一受控方式加 `chcp 65001` 仍未解决。Windows PowerShell 5.1 的 Console 中文错误输出同样默认不是 UTF-8，显式设置 Console.OutputEncoding 后可得到正确 UTF-8。这证明问题不只是脚本内容，更在输出采集契约。

建议由 Execution 的解释器适配明确输出编码，再由 Infra 的现有进程采集边界执行转换：Python 使用既有 UTF-8 设置；PowerShell 明确设置输出编码并处理脚本文件编码；CMD/原生程序根据实际代码页或显式配置解释，避免依次猜测多种编码。Windows PowerShell 5.1 对非 ASCII 的 UTF-8 无 BOM 脚本也需要适配，不能只调整输出。相关行为见 [Microsoft 字符编码说明](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_character_encoding?view=powershell-5.1)。

只给 collect 增加解码参数改动较小，但同一日志经 Workspace.inspect 读取仍可能损坏。若保持 stdout/stderr 为可通用读取的 Workspace 文本，更一致的方案是在采集时用确定的增量解码器转换为 UTF-8，保留一份正式日志；该方案需要将采集流的结束纳入已有进程 close，改动中等，应先讨论清楚。解释器默认不能推导所有子程序的编码，例如 CMD 启动的 Python 已使用 UTF-8，不应再统一按 CP936 解释。方案应允许已知外部程序明确编码，混合输出则由命令统一，不能承诺自动修复任意编码混用。它不需要新增编码恢复状态机，也不应改变 MCP/ACP 的 UTF-8 协议通道。通过 shell 启动 Python 不能解决此问题，还会加入 shell 自身的诊断输出。

## 开发代理与当前网络验证

状态：当前验证 `done`；历史故障归因及代理下地址校验的适配讨论仍为 `pending`。

仓库 [开发网络配置](../../tinysoul/assets/development/configs/infra/network.toml) 指定 override，HTTP/HTTPS 代理均为 `http://127.0.0.1:7897`，no_proxy 为本机地址。开发 Execution 启用 python、powershell、cmd，关闭 bash，没有模块或 interpreter 网络覆盖。有效策略按 Infra → Execution → interpreter 解析，替换继承的代理提示后交给所有受控进程；shell 的 Python/curl 子进程同样继承。这是仓库模板与当前主机验证，不等于已经取得历史 generation 的有效配置快照。

本次以该配置生成进程环境，进行有界、只读验证：

| 探测 | 当前观察 | 能支持的结论 |
| --- | --- | --- |
| 127.0.0.1:7897 TCP | 可连接 | 当前代理端口存在 |
| 直接 Python urllib 请求 example.com | HTTP 200 | Python 可以使用这套代理环境，不必由 shell 启动 |
| PowerShell 启动同一 Python 请求 | HTTP 200 | shell 继承环境后也可用 |
| 修复后的 Web fetch_public_page 请求 example.com | 成功取得 text/html，592 字符 | 当前 Web 下载及共用规范化主线可达 |
| 系统 curl.exe 请求 example.com | 代理 CONNECT 200，随后 Schannel SEC_E_NO_CREDENTIALS，exit 35 | 已连到代理；当前执行上下文的 TLS 客户端失败，不能等同全局断网 |
| 后续 CMD 启动 Python 请求 | 已进入 urllib，出现 TLS EOF | CMD 能启动程序，但某次网络请求仍失败；不能归因于 interpreter 身份 |
| Python 经代理请求 raw.githubusercontent.com | 有界读取超时 | 不能声称所有目标都经代理可达 |

上述 curl TLS 结果来自当前 Codex 进程环境，不能直接外推原 TinySoul 宿主；没有关闭证书校验。当前 PowerShell 5.1 的 `curl` 是 Invoke-WebRequest 别名，应使用 `curl.exe` 表达 curl 命令行参数；Windows 的空输出文件也不应照搬 bash 的 `/dev/null`。PowerShell 7 才明确支持 HTTP_PROXY/HTTPS_PROXY 环境变量；开发配置的 Windows PowerShell 5.1 HTTP cmdlet 应显式传 `-Proxy`，或在 interpreter 配置中选用 pwsh。见 [Microsoft Invoke-WebRequest 文档](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/invoke-webrequest?view=powershell-7.5) 与 [curl 代理环境变量说明](https://curl.se/libcurl/c/libcurl-env.html)。

DNS/getaddrinfo 和原始 TCP connect 不因 HTTP_PROXY 自动变成代理探测；HTTPS CONNECT 则可由代理处理目标解析。脚本混用这几种操作时，结果应分别解释。当前本机将 raw.githubusercontent.com 解析为 127.0.0.1，en.wikipedia.org 的地址集合包含非 global 的 2001::1，足以触发 Web 当前“本机解析地址全部为 global”的前置检查。可以确认本机 DNS 与代理路由有不同的判断边界，但未检查代理的解析配置，不能认定 fake-IP 或 DNS 污染。是否让显式代理负责目标解析，应作为 Web 地址策略与 Infra 网络契约的适配讨论，本次不直接放宽校验。

## 按维护者要求排除的改动

| 问题 | 状态 | 证据与影响 |
| --- | --- | --- |
| 表达可能已经产生副作用的执行及 timeout 恢复方向 | dropped | 保留原有执行事实和行为，本轮不调整 Action runner 或结果协议。 |
| 新增通用离线成功路径测试 | dropped | 未增加该测试；使用既有门禁、一次性复现和有界实际请求验证本次修复。 |

## 测试证据与改进范围

本次代码修改后完成以下验证：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/test.py --suite fast tests/plugins/capabilities/web/test_web.py tests/plugins/capabilities/web/backends/test_discovery.py tests/plugins/execution/test_engine.py
```

聚焦结果：55 passed、10 deselected。全量 Fast：1317 passed、133 deselected。正式完整门禁 `uv run --locked --extra dev python scripts/test.py --suite full`：1447 passed、3 deselected；`uv run --locked --extra dev ty check` 通过。Full 不包含需显式开启的 external suite，未声称完成真实 Defuddle/Trafilatura/Discovery 的全面供应商验收。

现有 Fetch 成功测试注入模拟 worker；Discovery 成功测试注入已构造的 FetchedPage；网络层测试覆盖 429 和连接异常。它们各自验证的契约有效，但没有覆盖 HTTP 成功后进入真实 HTML 规范化的主线，所以没有发现本次错误。

一次性验证还检查了有效 HTML 相对链接规范化、空 HTML 的明确 ParserError 分类，以及未知 AttributeError 在 worker 边界返回 worker_failed/error_type、对应 stop 处置，未泄漏原始异常文本。网络和编码验证的适用范围见前文，未将这些探测加入测试套件。

本轮实际修改 Web 的三个 backend 文件、Web 设计、本文、开发依赖声明及 uv 锁文件。Execution 协议、进程编码、网络配置、超时/副作用表达和前端均未修改。后续讨论应围绕已经确认的能力表达、CMD 引号、输出编码和代理路由边界展开，不从单次轨迹生成额外强制操作步骤。
