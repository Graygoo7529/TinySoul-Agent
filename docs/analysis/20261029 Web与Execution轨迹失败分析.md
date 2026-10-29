# Web 与 Execution 轨迹失败分析

日期：2026-10-29。分析已完成；下表中的实现问题仍为 `pending`，本文不表示修复已完成，也不是已确认的实施计划。

依据：[AGENTS.md](../../AGENTS.md)、[Web 设计](../design/capabilities/web.md)、[Execution 设计](../design/execution.md)、当前实现与 [2026-10-28/2 原始轨迹](../../reference/traces/turn-trace-2026-10-28-2.zip)。

分析从正常能力链路出发，以轨迹定位现象，用代码和独立复现确认原因。改进应保护通用能力契约，不把本次网址、调用顺序、脚本或模型输出固定成新规则。

## 结论与证据范围

主要 Web 故障来自共用 HTML 处理代码调用了不存在的 lxml 方法；宽泛异常捕获又把编程错误转换成了外部页面错误。Execution 的几类失败原因不同：未启用的解释器、违反 command/source_ref 契约、选错解释器，以及 Action 总时限到期。轨迹不能支持最终回答中“出站 HTTP 普遍受限、不是 web 动作本身的问题”的归因。

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

状态：`pending`。

[network.py](../../tinysoul/plugins/capabilities/web/backends/network.py) 的 `normalize_html_links()` 当前调用：

```python
document.make_refs_absolute(base_url, resolve_base_href=True)
```

本地安装的 lxml 6.1.3 的 HtmlElement 没有该方法，实际 API 是 `make_links_absolute()`。本地离线复现确认：完整有效 HTML、普通 HTML 片段、纯文本均在当前调用处产生 AttributeError，并被转换成 `invalid_html`。

进一步用 httpx.MockTransport 返回 HTTP 200、`text/html; charset=utf-8` 和含相对链接的有效页面，调用真实 `fetch_public_page()`，仍得到相同失败。只在内存中替换为正确 API 后，同一请求成功，链接转换为预期的绝对 URL。没有访问公网，也没有修改业务源码。

Git 历史进一步定位到 `d56aff3a`（2026-10-07）：项目统一引用命名时，将第三方方法 `make_links_absolute` 改成了 `make_refs_absolute`。这项修改早于本次轨迹。项目内部使用 ref 的命名规约不能改变外部库协议。

调用链能够解释轨迹的共同表现：

- Fetch 的下载函数在进入任何 extractor 前就会调用该函数，因此切换 Defuddle / Trafilatura 无法避开此缺陷。
- Discovery 的 page_fetcher 使用同一函数；失败处理保留 reason，最终返回 `Discovery seed could not be visited`。
- Kimi Search 不经过该函数，两次搜索成功与抓取失败可以同时成立。

轨迹没有保存每个页面的原始响应或异常链，因此不能逐项证明所有历史页面原本都有效；但当前缺陷是确定性的，覆盖这些能力的共用前置路径，也与跨网站的失败分布一致。不能把它归结为多个网站同时返回坏 HTML。

## 已确认：异常分类掩盖了实现错误

状态：`pending`。

`normalize_html_links()` 把解析、调用方法和序列化包在一个 `except Exception` 中，全部归为 `invalid_html`；[errors.py](../../tinysoul/plugins/capabilities/web/errors.py) 再将它映射为 `use_fallback`。于是“本地实现调用不存在的方法”被投影成“页面无法处理，可以换提取器”。这直接削弱了模型后续选择的依据。

这次异常没有附加 error_type。Discovery 的 `_PageState` 只保留 failure_reason，seed 失败又被概括成通用反馈。原始异常链留在 worker 内，导出的局部结果不足以区分页面解析问题与本地编程错误。

建议恢复正确 API，并把已知解析失败与实现/依赖失败分开：前者使用 owner 定义的页面反馈；后者沿既有 worker/Action 边界收敛，使用现有有限内部诊断，不冒充可由换网页或换 extractor 修正的问题。不需要增加自动重试、provider health、跨 Cycle 恢复管理器或庞大失败类型树。

## 其余 Web 失败的可确认范围

状态：`pending`（环境原因未证实）。

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

Cycle 11 两个请求使用 `interpreter=python` 与 `command`。Catalog 的 command 分支仅允许 shell，source_ref 分支才允许 Python，因此归一化阶段拒绝，没有进程启动。它符合当前明确契约。

工具的静态 schema 表达全部受支持身份，动态提示表达本世代可用身份，这是当前设计的选择。示例仍有 bash 偏向，可以做语义一致性整理；此次证据不要求改变解释器协议、自动猜测语言或新增按扩展名强制匹配的限制。

### 使用 cmd 解释 Python 源码

Cycle 14 请求明确指定 `interpreter=cmd`、`source_ref=workspace:scripts/net_test.py`。[ExecutionEngine](../../tinysoul/plugins/execution/engine.py) 读取源码快照，按所选解释器生成脚本副本与 argv，故 Python 文本被复制为 CMD 脚本并交给 cmd。

Cycle 15 的 `phase1/llm/tasks/001/request.json` 保留了此结果的完整模型 payload：Job `20261028-2-1`、reason `nonzero_exit`、exit_code `255`，stdout 显示逐行执行 `import socket`、`URLS = [`，stderr 包含 import 命令无法识别。足以确认语言与解释器不匹配；这里没有完成 Python 网络探测。

### 70 秒 Action 总时限

Cycle 17 改为 `interpreter=python` 与既有 source_ref，确实启动 Job `20261028-2-2`，随后得到 `execution_timeout`，constraint 是 `timeout_seconds=70`。下一 Cycle 的 Jobs 投影将该进程记为 cancelled，日志引用仍在。Action timeout 与其主动停止的进程记为 cancelled 分属两个层次，并不矛盾。

脚本顺序执行 5 次 DNS 查询、5 个带 15 秒超时的 HTTPS 请求，以及 5 个带 10 秒超时的 TCP 探测；这些操作没有统一的脚本预算，DNS 也未由该脚本设置总时限。仅逐次网络等待就可能超过 Action 的 70 秒。ZIP 未包含第二个 Job 的 stdout/stderr 正文，也没有后续 collect，不能确定它具体停在哪一步。

已有 start / wait / collect 能表达这类时长不确定的执行。可以直接使用这些能力或缩小诊断工作量，无需为网络诊断设计独立执行通道。结束本轮也不要求完成所有诊断，只应准确说明已知与未知。

### Phase 拒绝不等于 Execution 失败

Cycle 12 使用当前 scope 未提供的 `workspace_write`；Cycle 15 在 Phase1 调用业务 Action `workspace.write`；Cycle 16 未选择 workspace 域却生成 workspace.write。对应 PhaseFailure 都明确说明未接受或执行相应响应的意图。不能把其中的 Python／PowerShell 调用算作真实进程尝试；当前下一完整 Cycle 的反馈路径符合规约。

## 两项独立的实现观察

| 问题 | 状态 | 证据与影响 |
| --- | --- | --- |
| 外部进程文本解码契约不足 | pending | [infra/process/managed.py](../../tinysoul/infra/process/managed.py) 的 `_read_text()` 固定按 UTF-8、errors=replace 读取所有进程日志；轨迹中第一个 Job 的 stderr 已含 360 个 U+FFFD。Python 环境变量不能统一 CMD 和其它程序的输出编码。具体原始编码未包含在 ZIP 中，但模型收到的诊断已丢失字符。应在现有进程/解释器边界明确输出编码，不用多编码猜测链修补。此问题影响解释，不是 exit 255 的起因。 |
| 通用 timeout 直接给 retry_same | pending | [Action runner](../../tinysoul/kernel/action/execution/runner.py) 的 `_timeout_result()` 对所有执行超时给出 retry_same；对于可能已写入文件的 process，仅凭超时不足以得出原样重试建议。应区分框架的超时事实与业务 owner 的恢复方向，沿现有边界调整。本轨迹没有实际重试该超时调用，不能把这点当作本轮循环失败的直接原因。 |

## 测试证据与改进范围

本轮运行已有聚焦 Fast 测试：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/test.py --suite fast tests/plugins/capabilities/web/test_web.py tests/plugins/capabilities/web/backends/test_discovery.py tests/plugins/execution/test_engine.py
```

结果：55 passed、10 deselected。未运行完整门禁、真实供应商或公网测试；未修改业务源码。

现有 Fetch 成功测试注入模拟 worker；Discovery 成功测试注入已构造的 FetchedPage；网络层测试覆盖 429 和连接异常。它们各自验证的契约有效，但没有覆盖 HTTP 成功后进入真实 HTML 规范化的主线，所以没有发现本次错误。

优先改进应限于真实问题：

1. 修复第三方 API 调用，收窄会掩盖编程错误的页面异常分类。
2. 在 Web owner 测试中补一条离线 HTTP 成功路径，覆盖真实 HTML 规范化和相对链接处理；用通用小页面，不复制本次公网轨迹。
3. 保留现有 Engine / Service / Action / Job / Runtime 的分工，分别讨论输出编码和 timeout 恢复方向；不将它们混成新的统一恢复系统。
4. 网络环境问题保持待验证，模型结论与 milestone 应区分观测和推测。当前轨迹曾将 Python 契约概括为“只能用 shell、必须 source_ref”，又将总时限到期当成全局网络故障证据；这些是错误解释，不能成为后续设计的事实前提。

本轮新增的仅为本文分析记录，没有执行修复、修改运行配置或更改前端。
