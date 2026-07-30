# Resource Capability 设计

## 定位

`capabilities.resource` 负责 Workspace 资源之间的本地转换和提取。它不拥有新的 Link namespace，不维护独立索引，不把转换正文放入 Context，也不调用 LLM 识别文档。

Resource capability 不建立独立 Action Domain。转换属于对 Workspace 资源的操作，因此并入宽泛的 `workspace` Domain，并提供：

```text
workspace.convert_with_markitdown
workspace.convert_with_pypdf
```

两个 action 都把输入文档转换为 Markdown 与关联 Workspace 资源包，并独立收敛为成功、部分成功、失败或超时。它们不是自动串行 fallback，也不会为图片处理开启额外 Agent Cycle。

## 选择语义

`workspace.convert_with_markitdown` 面向普通 PDF/DOCX 和适合结构化 Markdown 的文档。它使用 MarkItDown 作为主转换 adapter，并用格式专用 extractor 补充图片和附件。

`workspace.convert_with_pypdf` 只处理 PDF，强调页级文本、嵌入图片、附件和页面可追踪性。pypdf 负责 PDF 文本与嵌入资源，pypdfium2 负责在无有效文本时把页面渲染为 PNG；页面渲染不是 pypdf 自身能力。

`home:how_domain:workspace` 同时说明一般 Workspace 操作和转换选择倾向：普通文档和结构化输出优先 MarkItDown；PDF 专用提取、页级追踪、图像型页面或嵌入资源优先 pypdf。两个 action 都是确定性本地 action，不含内部 LLM Task，因此不消费 action HOW。Capability 仍由 `tinysoul.capabilities.resource` 拥有配置、依赖、转换 service 和 `resource.*` backend handler；Domain 与 Capability 不要求一一对应。

## 输入输出

两个 action 使用同一稳定参数协议：

```text
source_link: required Workspace document Link
target_link: required Workspace .md Link
overwrite: optional boolean, default false
expected_source_digest: optional stale-source guard
expected_target_digest: optional overwrite guard
```

模型不能传入绝对路径、Workspace root、临时目录、解析器 argv、任意 Python 代码或 source format override。格式由 Workspace record 的 suffix/media type 与 action 支持范围确定。

输出以 target 为主文档，并使用确定性 sibling 目录保存资源：

```text
workspace:converted/report.md
workspace:converted/report.assets/image-001.png
workspace:converted/report.assets/attachment-001.xlsx
workspace:converted/report.assets/page-003.png
```

图片、渲染页面和附件统一进入 Markdown 末尾的 `Extracted Resources`，使用 canonical Workspace Link；资源 label 保留可确定的页面或原文件名信息。无有效文本但页面可渲染时，Markdown 对每页给出有界占位，并在资源段列出页面图片 Link，结果状态为 `visual_only` 或 `partial`，不是 OCR 失败。

转换过程不产生 `ImagePart` 或 base64。Agent 后续把生成的图片 Link 用作 `reference_links` 时，WorkspacePromptReferenceResolver 才读取图片并构造 ImagePart，LLM provider adapter 再编码供应商传输格式。

## Workspace 协作

Resource 不能直接通过 `WorkspaceEngine.path_for()` 绕过资源边界。Workspace 提供：

- bounded document read/stage，校验 kind、大小、digest 和并发变化；
- bytes/text bundle write，预检全部 Link、覆盖和 digest guard；
- 单锁内 staging、原子单文件替换、完整 reconciliation 和失败整体回滚；
- 新目标继承 source retention；覆盖目标保留原 target retention；
- bundle 提交后返回同一 revision 的 records/manifest。

转换 executor 在成功提交 bundle 后发送一次 `context.workspace.sync`。WorkingContext 因而在同一 Phase3 信号消费边界获得 Markdown、图片和附件摘要；ActionResult 仍只返回执行摘要。

覆盖转换使用 target 对应的 `.assets/` 前缀作为该转换产物范围。提交前计算新资源集合；旧产物中不再存在的文件由同一个 bundle mutation 删除，避免重复转换留下失效图片。

`source_link` 在整个转换中保持只读；如果 source 本身位于 target 的 `.assets/` 所有权前缀下，转换在 worker 启动前拒绝，避免覆盖清理把输入误判为旧产物。禁用页面渲染或渲染失败时，只有生成标题/占位而没有实际文本、图片或附件不构成可提交输出。

## ActionResult

成功或部分成功 payload 只包含：

```json
{
  "source_link": "workspace:incoming/report.pdf",
  "markdown_link": "workspace:converted/report.md",
  "converter": "pypdf",
  "content_status": "partial",
  "generated_resource_count": 4,
  "visual_review_required": true,
  "visual_reference_links": [
    "workspace:converted/report.assets/page-003.png"
  ],
  "warning_codes": ["page_text_unavailable"]
}
```

`visual_reference_links` 与 warning 都有上限；完整生成资源列表由 Markdown 与 Workspace manifest 表达。ActionResult 不返回 Markdown 正文、图片字节、base64、附件正文或 worker stdout。

## Subprocess

第三方文档解析位于固定 package worker 中。Action backend 抽取 `ControlledProcessRunner`、`ProcessRequest` 与 `ProcessOutcome`，统一负责进程启动、deadline、取消回调、进程树终止和 stdout/stderr 的有界结果投影。子进程输出直接进入临时文件，进程结束后只按 UTF-8 字符上限读取前缀并设置 truncated 标记，避免 `communicate()` 在宿主内存聚合完整输出；该限制不是子进程硬输出配额，真正的超限终止策略需在出现相应外部 action 时独立定义。

现有 `subprocess.default` 是 ExecutorRegistry 中的通用 handler identity，不是项目配置字段。SubprocessActionExecutor 继续把 catalog options 转为 ProcessRequest 并把 outcome 映射为普通 ActionResult；两个 Resource executor 使用同一个 ControlledProcessRunner，执行 Workspace staging、固定 worker 请求、worker manifest 校验和 bundle 提交。业务模块不复制 `Popen`、`taskkill` 或 timeout 逻辑。

worker 只接收 host 生成的临时输入/输出路径和有界结构化请求。模型参数不能直接成为 argv。worker 不读取项目配置、不修改 Workspace、不构造 ActionResult，只生成临时 Markdown、资源与 JSON manifest。

Resource executor 在 source staging 前、worker 返回后以及 Workspace commit 前检查 Action cancellation/deadline。取消在 bundle commit point 前收敛为 timeout，临时输出随 staging 目录清理，不发布 Workspace signal；`write_bundle()` 一旦开始则作为不可取消的原子提交区完成或回滚，避免取消把多文件 bundle 留在中间状态。

## 配置与依赖

项目配置位于 `configs/capabilities.resource.toml`：

```toml
[capabilities.resource]
max_source_bytes = 20971520
max_output_chars = 1000000
max_assets = 64
max_total_asset_bytes = 52428800
max_pdf_pages = 300
render_pdf_pages = "on_no_text"

[capabilities.resource.convert_with_markitdown]
enabled = true
formats = ["pdf", "docx"]
extract_images = true
extract_attachments = true

[capabilities.resource.convert_with_pypdf]
enabled = true
extract_images = true
extract_attachments = true
```

配置只表达期望能力。Resource 根据 effective settings 推导 MarkItDown/pypdf/pypdfium2/Pillow requirement；Infra DependencyChecker 对照当前解释器检测 distribution 与 module。启用 action 缺少依赖时 App 启动失败，禁用 action 不检测依赖并从 effective Catalog 移除。

基础依赖随 TinySoul wheel 安装，dependency check 仍用于检测损坏环境、错误解释器和后续 optional capability。运行时不自动 pip install。

## 失败与限制

以下为局部 ActionResult：不支持的 suffix、source/target Link 无效、source 过大、加密或损坏文档、输出/资源数量超限、目标冲突、worker 失败、无文本且无可提交图片、bundle 写入冲突。

如果部分页面或嵌入资源无法提取，但仍有安全、可用输出，则提交完整 bundle，状态为 `partial` 并返回稳定 warning。只有完整输出通过 UTF-8、非空、字符上限、asset count/bytes、Link 范围和 digest 校验后才允许提交。

配置非法、启用 action 缺少依赖以及 Catalog/registrar 装配矛盾属于启动或模块边界失败。worker 非零结果和 staged output/manifest 协议错误属于当前调用的局部 ActionResult，后者使用稳定 `worker_protocol_invalid` reason，不能泄露绝对路径或原始 traceback。Runtime transfer 原样传播；subprocess 超时或 commit point 前的取消收敛为 Action timeout 并清理临时目录，不留下半成品 Workspace 资源。
