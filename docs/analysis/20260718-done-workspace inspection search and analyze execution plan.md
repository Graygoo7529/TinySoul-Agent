# 20260718 Workspace Inspection Search And Analyze Execution Plan

## 状态

status: done

## 背景

Workspace 当前把资源 Link 和摘要投影到 WorkingContext，并只允许具体 action 在内部临时读取正文。该边界避免了文件正文被自动或无界地放入 Context，但也使 Agent 无法在已知行范围时读取片段、无法按字面量定位工作区内容，也缺少一个基于明确 Workspace references 生成有界分析结论的 Workspace-owned LLM action。

现有实现已经具备以下基础：

- `WorkspaceEngine.read_text_slice` 提供 1-based 行读取和字符上限；
- `WorkspacePromptReferenceResolver` 可以把明确 Workspace text/image Link 转换为临时 PromptBlock；
- ActionResult 支持 foldable trace projection，Context 以 compact canonical message 和完整 visible overlay 表达可折叠结果；
- `LLMActionTaskRunner` 支持 Workspace executor 构造 TaskPrompt 后执行禁用工具调用的 action-internal LLM task；
- WorkingContext 持有当前 Workspace Manifest revision 的资源摘要，Phase2 可以据此选择明确 Workspace Links。

本计划在不引入目录 Link、持久搜索索引、embedding、regex 或嵌套 Action 工具调用的前提下，增加显式、有界、可定位的 Workspace inspection 能力。

## 已确认语义

1. 禁止的是文件正文被隐式、自动或无界地投影到 Context；显式有界范围可以偶然覆盖一个很短的完整文件。
2. `workspace.read` 按明确 Workspace text Link 和 1-based 闭区间读取片段，并以 cursor 支持超长单行的连续读取。
3. `workspace.search_text` 支持单文件、目录和整个 Workspace 三种显式 scope；执行单行字面量搜索，返回来源 Link、digest、关联起止行、命中行和包含查询文本的有界片段。结果正文不足以继续容纳时返回额外的有界行号 hints。
4. `workspace.analyze` 只接受 Phase2 已选择的一个或多个明确 Workspace text `reference_links` 和一个 `intent`，不接受目录或整个 Workspace scope，也不在 Phase3 重新选择资源。
5. `workspace.analyze` 对 references 使用“完整引用或局部失败”语义：任一文件或合计正文超过 action source budget 时不调用 LLM，而是返回有界 ActionResult，提示 Phase2 缩小 Link 集合或先使用 read/search。
6. `workspace.analyze` 只执行一次 action-internal LLM task，返回有界 `answer` 和经过验证的来源定位；不修改 Workspace、不发布 Workspace snapshot。
7. `workspace.read` 与 `workspace.search_text` 的正文结果使用 Catalog 声明的 foldable trace mode：当前 Turn 可见完整结果，Context 压力下移除正文 overlay，Session 只持久化 compact locator。Workspace 是可变且按日归档的，因此 compact locator 不承诺跨日恢复原正文。
8. `workspace.analyze` 返回的是有界整理结论，使用 standard trace；原始 reference 正文只存在于 action-internal prompt。

## Action 折叠框架

Catalog 在具体 action 的 runtime 配置下声明结果 trace 行为：

```toml
[runtime.result]
trace_mode = "foldable"
```

稳定模式只有：

- `standard`：完整 model payload 是 canonical trace，Session 持久化完整结果；
- `foldable`：compact payload 是 canonical trace，完整 model payload 是当前 Turn 的 visible overlay；Context pressure 或显式 fold 会移除 overlay，Session 始终只接收 compact canonical payload。

Catalog 配置只决定生命周期行为，不能从任意 JSON 自动推断应保留字段。业务 executor 对成功结果提供 `compact_payload` 与有界、去重的 `origin_refs`；Action runner 依据当前 ActionSpec 校验并形成最终 trace projection。foldable action 的成功结果缺少投影数据、standard action 返回投影数据或投影结构非法，均属于 Catalog/实现不一致的 Action invariant。failed/timeout 结果不折叠。

现有 `context.trace.recall` 和 `session.history.recall` 迁移到同一声明式行为。Context signal、TraceEntry 和 TurnSummary trace record 将单数 `origin_ref` 泛化为 `origin_refs`，以支持一个搜索结果来自多个 Workspace resources。Session 不增加 action-specific 折叠逻辑。

## workspace.read

模型侧参数：

```json
{
  "link": "workspace:src/service.py",
  "start_line": 120,
  "end_line": 180,
  "max_chars": 2000,
  "cursor": 0,
  "expected_digest": "optional sha256"
}
```

- `link`、`start_line`、`end_line` 必填；范围为 1-based 闭区间；
- `cursor` 是指定行范围内的 0-based 字符续读位置，默认 0；
- `max_chars` 可选且只能收紧 Workspace 配置硬上限；
- `expected_digest` 可选，用于 search -> read 或连续读取时拒绝陈旧来源；
- 只接受当前 Manifest 中的 UTF-8 text resource；document 必须先转换，image/binary 不接受；
- 不修改文件或 Manifest，不发送 `context.workspace.sync`。

成功结果包含 Link、digest、请求范围、实际范围、正文、是否截断、截断原因、next cursor/position 和 EOF 事实。compact payload 保留相同定位信息但删除正文。

现有按行 helper 在遇到超长单行时可能先构造完整行，再应用字符上限。实现需要改为固定字符块的增量 UTF-8 文本扫描，使读取、行号跟踪、cursor 和搜索共用同一有界扫描基础，不构造无界单行。

## workspace.search_text

模型侧参数：

```json
{
  "query": "WorkspaceContractError",
  "scope": {"kind": "directory", "prefix": "workspace:tinysoul/workspace/"},
  "case_sensitive": true,
  "top_k": 8
}
```

scope 必须显式提供：

- `file`：`link` 是一个当前 Manifest text resource；
- `directory`：`prefix` 使用 `workspace:<relative-posix-directory>/` 形式，只作为目录选择器，不是 Workspace resource Link；
- `workspace`：不接受额外 locator，搜索当前 Manifest 中全部 text resources。

搜索仅接受有界、非空、单行字面量 query。首个实现不接受 regex。候选资源按 Link 稳定排序，命中按行号排序；重叠或相邻上下文窗口合并为 fragment。长行 excerpt 围绕实际命中位置裁剪，并在行范围之外补充字符列定位，保证返回正文包含 query。

完整结果区分：

- `fragments`：Link、digest、范围、命中行和正文；
- `line_hints`：正文预算不足后保留的 Link、digest 和命中行；
- `truncated`：命中结果多于 result projection budget；
- `coverage.complete`：扫描是否在 scan budget 内完成。

result budget 与 scan budget 是不同边界。达到 result budget 时仍可在候选上限内保留 compact hints；达到 scan budget 时返回 partial success 和明确 coverage reason。compact trace payload 删除 fragment 正文，保留 query、scope、全部已返回 locator、digest 和 coverage。

## workspace.analyze

模型侧参数固定为：

```json
{
  "intent": "分析这些文件中 ActionResult 的折叠和 Session 持久化过程",
  "reference_links": [
    "workspace:tinysoul/action/core/result.py",
    "workspace:tinysoul/context/trace.py"
  ]
}
```

- `intent` 是有界非空字符串；
- `reference_links` 必填、非空、去重，只接受明确 Workspace text Links；
- Phase3 不扩展目录、不替换 Link、不重新选择资源；
- Link 数量、单文件字符数、合计 source 字符数和 answer 字符数由 Workspace analysis settings 硬限制；
- references 必须完整进入 action-internal prompt；Link 数量、单 source 或总 source 超限时不调用 LLM，分别返回 `reference_count_exceeded`、`reference_chars_exceeded` 或 `source_chars_exceeded` 局部失败与有界 Link/size/digest 诊断；
- action-internal LLM 固定禁用工具调用，并由 Workspace executor 构造 intent、references 和输出协议 PromptBlocks；
- LLM 只返回 `answer` 与 `source_ids`，executor 校验 source ids 只能引用实际输入，再映射为 Link、digest 和完整行范围；
- 非法 JSON、超长 answer、虚构来源或 task failure 收敛为局部 ActionResult；
- 成功结果使用 standard trace，持久化有界 answer、sources 和 coverage，不携带原始正文。

该 action 与 `core.reason` 的区别是固定的 Workspace-only 参数、完整引用或失败的 owner budget、固定 grounded answer 协议、digest/范围来源和 Workspace-owned failure/HOW。若实现只对 `core.reason` 改名而不提供这些契约，则不应保留该 action。

## 配置

Workspace 顶层继续保留通用 `max_read_chars`。新增嵌套 search/analysis settings，项目配置与 `tinysoul init` 模板保持一致：

```toml
[workspace.search]
max_query_chars = 256
max_scan_chars = 1000000
candidate_limit = 100
default_top_k = 8
max_top_k = 16
context_lines = 2
max_excerpt_chars = 600
max_result_chars = 8000

[workspace.analysis]
max_intent_chars = 2000
max_reference_links = 8
max_source_chars = 24000
max_chars_per_reference = 12000
max_answer_chars = 4000
```

所有配置值由 Workspace 模块解析并拒绝未知键；调用参数只能收紧相应上限。具体默认值在实现和真实测试中保持一致，不能由 Action Catalog backend options 形成第二套业务配置。

## 实施切面

### Slice 1: Action Result Lifecycle

状态：completed

- 增加 Catalog runtime result trace policy；
- 分离 runtime trace mode 与 executor 提供的 compact projection data；
- 泛化 `origin_refs`；
- 在 Action runner 收敛成功结果时验证策略；
- 迁移 Context/Session recall action；
- 验证 Context pressure、显式 fold 与 TurnSummary/Session 只持久化 compact payload。

### Slice 2: Bounded Workspace Read

状态：completed

- 增加共享的有界增量文本扫描结构；
- 完善 range/cursor/position/digest 结果模型；
- 实现 `WorkspaceEngine.read_text_range` 和 action executor；
- 增加 Catalog、foldable compact projection 和 Trash restore bridge；
- 覆盖长行、UTF-8、CRLF、EOF、范围越界、cursor、digest 和 kind 边界。

### Slice 3: Deterministic Text Search

状态：completed

- 增加 Workspace-owned scope/result/search service；
- 实现 file/directory/workspace scope 校验；
- 实现字面量大小写搜索、fragment 合并、长行命中窗口、hints 与双预算；
- 增加 executor、Catalog 和 foldable projection；
- 覆盖目录段边界、ignored/internal、symlink、非法 UTF-8、partial coverage 和稳定排序。

### Slice 4: Workspace Analyze

状态：completed

- 增加完整 reference bundle read 和 analysis prompt builder；
- 增加一次性 `workspace.analyze` LLM action executor；
- 校验 source budget、answer 和 source ids；
- 增加 Catalog、domain/action HOW 和 standard result；
- 覆盖超限不调用 LLM、来源约束、task failure、Context compression protected links 和无 Workspace mutation。

### Slice 5: Integration And Release Verification

状态：completed

- 更新 AGENT、Action/Workspace 设计文档和能力扩展进度；
- 同步当前项目与 package project template 配置；
- 增加 Catalog/Phase/App 工作流测试；
- 运行全量 pytest、`scripts/typecheck.ps1`、wheel build 和隔离 package data 验证；
- 全部完成后将本文状态改为 `done` 并按文档规则重命名为 `20260718-done-workspace inspection search and analyze execution plan.md`。

## 实施结果

- Action Catalog 已增加 `ActionResultRuntimeSpec` 与 `[runtime.result] trace_mode`；runner 校验 standard/foldable 成功结果，Context signal、TraceEntry 和 TurnSummary 使用复数 `origin_refs`。Context/Session recall action 已迁移，Session canonical trace 不接收 visible overlay。
- Workspace 已增加固定字符块的 range/cursor text scanner、`WorkspaceEngine.read_text_range`、确定性 `WorkspaceTextSearchService` 和完整 reference analysis preparation。公开 action 为 `workspace.read`、`workspace.search_text` 与 `workspace.analyze`。
- read/search 的 executor 提供删除正文后的 compact locator；analyze 只执行一次 action-internal LLM task，校验非空 answer、非空且唯一的 supplied source ids，并返回 Link/digest/完整行范围。
- 当前项目与 init 模板已同步嵌套 search/analysis 配置、Catalog package data、Workspace domain HOW 和三个 action HOW；AGENT、Action/Workspace 设计文档与能力扩展计划已同步。
- 全量 `pytest tests` 通过；真实网络/供应商测试按仓库既有条件跳过。全量 `ty check` 通过，wheel 构建、package-data 断言、隔离安装和 `tinysoul init` 验证通过。

## 验收边界

- WorkingContext 和 BackgroundContext 仍不保存 Workspace 正文；
- read/search 的正文只通过显式 ActionResult visible overlay 进入当前 Turn，Session trace 不保存正文；
- analyze 的原始 references 只进入 action-internal prompt；
- 所有路径只通过 Workspace Link/scope 类型和 Engine 门面解释；
- mutation action、Workspace snapshot、Trash、Daily archive 与单写者一致性语义不改变；
- 普通参数、范围、类型、预算和 LLM 协议问题收敛为局部 ActionResult；Workspace IO/invariant 与 Runtime transfer 保持 owner bridge 语义；
- 不建立持久搜索索引、embedding provider、目录 Link、regex、递归 Action 或新长期状态。
