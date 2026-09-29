# Visualization 后端修复复核与前端阶段准入判断

> 日期：2026-09-29；代码基线：`d0b3e11`。
> Review 状态：done；R1–R3：closed；R4：pending。
> 对比基线：`5993913`。本次检查 `a49a6a5` 的实现修复及 `d0b3e11` 的契约/前端计划更新。
> 已重新读取根目录 AGENTS.md、前次 Review、后续改进计划、当前 Endpoint 契约及相关 owner 实现。本次只增加评审文档，不修改业务代码。

## 1. 结论

**可以开始前端对接和改进阶段，但应把 R4 的真实契约校正作为 F0 接口冻结前的任务。当前不能把 `docs/endpoint/contracts/` 全部当作已验证的实际响应使用。**

后端主要功能已具备，上次三项正常导航缺口已经修复；没有发现需要再开一轮后端架构重构的新问题。当前待完成的是公共契约与运行事实的对齐，而不是缺少核心能力。

建议并行推进：前端可以开展视觉、布局、独立组件、设置草稿和渲染注册等工作；后端集中校正响应声明与样例，随即完成 F0 的类型、分页、问答恢复和资源路由接入。不要在前端增加同时兼容“错误样例形状”和“真实响应形状”的分支。

| 项目 | 本次判断 | 实施情况 |
| --- | --- | --- |
| R1 Context roots | 已解决 | 已打开 segment 提供真实 root，descriptor 路由前缀保留原职责 |
| R2 Trace ref / Memory fragment | 原问题已解决 | Trace owner 解析实际节点格式；动态绑定复制后附加 fragment |
| R3 Home canonical refs | 已解决 | direct refs 与 backlink 路径复用 Home canonical 映射 |
| R4 契约交接 | 尚未完成 | 已有 artifacts，但部分样例、JSON Schema、OpenAPI 与实际响应不同 |
| 前端建设条件 | 有条件具备 | 功能基础可用；冻结接入类型前必须校正 R4 |

## 2. 三项修复是否干净一致

### R1：roots 由实际 owner 提供

`kernel/context/segments/protocol.py` 新增窄的 `NavigableSegment`，`TurnSegments` 汇总已打开段的导航入口，Context overview 读取该结果。Trace 返回 `head_ref()`，Session 返回 `session:map`，归档 Workspace 段也提供自己的入口。

这保持了依赖反转：Kernel 组合导航元数据，不解析 Session 图；`ref_prefixes` 仍用于范围路由，没有变成含具体 Turn 身份的动态 descriptor。

实际 Agent/HTTP 复测：overview 返回的 `session:map`、`turn:trace@review-main` 均可直接 inspect，状态为 200；Session 子入口出现在 `items` 中。没有为 UI 阅读增加 Action 执行、load 或额外持久化。

### R2：Trace owner 与动态 locator

`kernel/context/builtin/trace.py` 集中提供 `parse_trace_reference()` 与当前 heap 的 `resolve_reference()`；SDK 组合这些能力，已支持 `turn:trace/<turn_id>/<node_id>`，不会把压缩节点改写成 head。

复测采用真实 TraceHeap 产生压缩节点，owner 校验通过，HTTP resolver 返回 200 并保留原 ref/turn_id。此处核对的是节点身份解析；没有把无活动 Context 的历史定位描述成历史内容仍可读取。

`infra.references.append_locator_fragment()` 复制原 locator 后附加 fragment，不修改共享 binding。活动 Turn 中请求 `memory:current#notes`，实际返回相同 day 与完整 `memory:current#notes`；本轮 SDK 测试也覆盖显式 day 分支。

这些变化在原有 owner 和通用 locator 语义内完成，没有新增一套资源状态。

### R3：Home 返回可继续打开的 canonical Link

`plugins/home/engine.py` 的 `_canonical_markdown_reference()` 复用 `resolve_relative()` 和 Home layout。浏览/inspect 的 direct refs 及 backlink 输入采用同一映射。

复测在临时项目的 `home:skills_action:core/answer` 中放入：

```markdown
[Workspace guidance](../../skills_domain/workspace/DOMAIN.md)
```

现在 `home/content` 返回 `home:skills_domain:workspace`，交给 `resources/resolve` 得到 200；没有再返回错误的 `home:skills_domain/workspace/DOMAIN.md`。实际正文仍由原 Home owner 提供。

## 3. 尚未完成的 R4：契约存在，但部分内容不是实际协议

**优先级：P2，F0 接口冻结前处理。** 这不是要求新增复杂框架；它直接影响普通页面如何读正文、续页、判断完成和应用配置。

### 3.1 样例与实际响应的差异

| 契约文件 | 样例描述 | 实际实现/本次验证 | 前端影响 |
| --- | --- | --- | --- |
| `examples/context-trace-page.json` | 顶层 `children`、`continuation`、`complete` | DisclosurePage 将 child/content/source 序列化到 `items`，续页为可选 `next_continuation` | 可能读取不到导航项或停止续页 |
| `examples/home-effective.json` | `content` 是正文字符串，带 `continuation` | 实际 HTTP 为 `items[{ref,text}]`、`view`、`metadata`；长内容可有 `content_fragment`、`next_continuation` | Home 正文与长文本读取会按错结构实现 |
| `examples/job-output.json` | `state/result.stdout/continuation` | backend.read_output 为 `items[{channel,text}]`、`next_continuation`、`truncated`、`result_locators` | 无法按通道持续读取真实输出 |
| `examples/config-views.json` | apply 的 `state=reload_requested`；含 reset 回执 | 实际 apply 返回 `state=active`、`generation_id`、`pending_reload=false`、changed/matching 字段；重置草稿属于前端本地操作 | 误建第二段等待流程，或寻找不存在的 reset API |
| `examples/config-views.json` | 方案身份为 `preset_id` | 实际方案对象身份为 `id`；apply 请求字段才是 `preset_id` | 运行方案选择器容易取错字段 |
| `examples/turn-finished.json` | User Turn result.status 为 `completed` | 本次真实正常回答为 `answered`，按 TurnOutcomeStatus 序列化 | 完成状态映射错误 |

其中 Home 正文、fragment 页、配置 apply、preset 与 Turn 完成均通过真实 Agent + ASGI HTTP 查询复现；Job 输出和 Disclosure 字段另与当前 owner 序列化代码核对。

本次取得的实际 Home 文本响应具有以下形状（省略正文）：

```json
{
  "ref": "home:skills_action:core/answer",
  "items": [{"ref": "home:skills_action:core/answer#L1-L1", "text": "..."}],
  "view": "content",
  "metadata": {
    "locator": {"link": "home:skills_action:core/answer", "view": "effective"},
    "direct_refs": ["home:skills_domain:workspace"]
  }
}
```

将同一正文扩大后，1024 字符页预算实际返回 `items: []`、`content_fragment.encoding=canonical_json` 与 `next_continuation`。空 items 不代表读取结束。当前 fixtures 没有体现这条正常路径。

最新提交已把 Search 示例改为较接近真实的 `result_ref/source/items/coverage/page` 结构，这个修改方向正确；仍需与真实序列化同源生成，不能用这一项更新推定其它样例已经准确。

### 3.2 OpenAPI / JSON Schema 没有描述主要被消费的字段

位置：`tinysoul/gateway/endpoint/http/schemas/responses.py:84` 起，以及 `docs/endpoint/contracts/schemas/`。

- `PageResponse` 声明了 `children/content/sources/continuation`，却没有声明实际通用读取使用的 `next_continuation`、`content_fragment`。它混用了内部对象概念和 HTTP 序列化形状。
- `SearchResponse` 声明 `operation/candidates/query`，真正的 `result_ref/scope/source/coverage/page` 主要作为 extra 字段透传。
- `TurnResponse` 未描述问题卡片恢复所必需的 `question`、`budget_request`、`wait_reason`、`result`。
- `ConfigResponse` 未描述核心 `fields/activity`；Config apply、Preset、InteractionPage、JobOutput 等也没有完整对应的稳定响应声明。

`extra="allow"` 和 `response_model_exclude_unset` 保住了运行时原输出，因此这些模型未必导致现有 HTTP 直接报错；但它们尚不能承担“前端按类型接入”的职责。前端需要使用的大部分事实仍处于未说明的扩展区域。

另一个实际不一致是：`home-effective.json` 能通过提交的 `page.json`，但交给实际路由使用的 `PageResponse.model_validate()` 会因 `content` 必须为 list 而失败。手写 JSON Schema 允许字符串、Pydantic 声明只允许列表，实际 owner 则将正文放在 items——三者不是同一个边界。

### 3.3 现有契约测试没有验证“契约来自实现”

位置：`tests/gateway/endpoint/test_contracts.py:19` 起。

测试只读取提交的 JSON，再用提交的 Schema 校验；没有运行 Endpoint/SDK 获取实际响应。`page.json`、`configuration.json`、`job.json` 没有必要的 required 约束，当前连空对象 `{}` 都能通过。本次已验证这三项。

因此两项 contract tests 通过只能证明“这些文件相互接受”，不能证明字段、状态或分页协议与生产输出一致。尤其 config apply/reset、Home diff/Memory redirect 的主体及 capabilities 中部分内容没有被这些测试实际校验。

### 3.4 接入说明仍未完全同步

`docs/endpoint/frontend-integration.md` 增加了 contracts 入口，但主体仍把配置流程写作 PATCH + reload，未明确前端主交互采用 apply/presets、active/saved 与本地 reset。其它正式文档中已有较准确说明，应在入口文档统一，而不是让前端自行判断哪个描述是主流程。

后续改进计划虽然已归档为 done，R4 的完成清单与上述事实仍不一致。建议将 R4 验收恢复为待完成，在真实契约补齐后再关闭；R1–R3 的结论不需要回退。

## 4. R4 的最小且完整修订方案

保留现有 owner 序列化，不修改正常业务响应去迎合示意样例。此次收尾只需要以下工作：

1. **以实际输出定义稳定边界。** 普通列表/Disclosure、SearchPage、JobOutput 的续页语义并不完全相同，分别准确描述，复用共同的小结构。不要用一个全部可选的 PageResponse 掩盖区别，也不要为了统一名字重写已有 owner。
2. **声明前端实际消费的固定字段。** 包括普通页的 next_continuation/content_fragment、Search 结果与 coverage、Turn question/budget/result、配置 fields/activity、Preset 身份和匹配状态。正文等动态内容仍可保留 JsonValue；不要重新复制整个插件内部模型。
3. **生成真实小型 fixtures。** 在临时项目和 fake 模型环境中执行 owner/SDK/ASGI 调用，再规范化 ID、时间等动态值。保持字段位置、状态名、空值和续页键不变。生成出的 Home/Trace/Job/问答/配置/Search 样例直接供前端使用。
4. **让校验连接到实际响应。** 至少验证真实响应通过对应公开 schema、OpenAPI 与独立 schema 不冲突；分页样例走完下一页，问答样例读到问题与关联回复。用少量代表性契约测试覆盖，不堆全页面快照。
5. **统一文档与状态。** 删除虚构的 reset 后端回执，更新 apply 主流程、User Turn 状态和各分页协议；补齐真实提问/回复、InteractionPage、Job、MCP/ACP、模型用途观察样例。以修正后的契约作为前端 F0 的输入。

不需要新协议版本、兼容层、全局 DTO 平台或更多运行时防御逻辑。Pydantic/OpenAPI 与独立 schema 可以由同一声明导出；至少应有一致性验证，避免继续独立手写三套形状。

## 5. 前端现在可以怎样推进

| 工作 | 是否可开始 | 接入注意事项 |
| --- | --- | --- |
| 原有视觉风格、对话/工作区增量布局 | 可以 | 保持已确认风格，不增加说明性 Demo 文案 |
| 设置布局、本地偏好、统一草稿、排序控件 | 可以 | 本地 reset 不请求后端；批量应用对应 config/apply |
| QuestionCard、ActionRenderer、CodeBlockRegistry | 可以 | 布局可先做，数据类型使用校正后的真实问题/Action 协议 |
| Home/Memory/Context/运行页组件 | 可以 | 真实 owner 能力已具备；分页与输出读取必须按实际 envelope |
| ResourceRouter | 可以接入已修复路径 | 使用后端 canonical locator，不恢复前端拼接规则 |
| 从当前 contracts 批量生成客户端、冻结 mocks | 暂缓定稿 | 先完成 R4，避免把错误样例固化进页面逻辑 |
| 全链路前端验收 | 契约校正后进行 | 覆盖配置应用、问答、历史恢复、分页、Search、Job 和资源跳转 |

目前没有需要重新讨论的重要架构语义。前端计划新增“按当前 Action Catalog 清理旧 renderer ID”的要求合理，应保留；未知 Action 使用通用结构回退，不为旧动作名称保留兼容映射。

一项非阻塞代码整理：`agent/services.py:700`、`:707` 的 Trace 解析捕获了宽泛 `Exception`。实际预期来自 Context 的有限错误，可以收窄，避免把内部程序错误统一报告为用户引用错误。不必为此增加新异常层级或另开一轮改进。

## 6. 独立验证记录

- 使用独立 worktree，未覆盖上次 Review 或用户代码。
- 环境：Linux、Python 3.13.15、ty 0.0.84；没有 Conda/PowerShell，使用与 Full 相同的 pytest 选择，显式指定 Python 运行 ty。
- 定向测试：**132 passed，7.65 秒**，覆盖 Endpoint、Context、Home 和 locator。
- 类型检查：**All checks passed**。
- 全部非 external 本地测试：**1197 passed、6 skipped、25 deselected，155.65 秒**。5 项 skip 为 Windows 特定行为，1 项因未安装可选 Defuddle CLI；未声称已验证这些环境路径。
- `git diff --check`：通过。测试的两条 warning 来自 jsonschema.RefResolver 弃用提示，不是业务失败。
- 实际探查：Context roots 200；Home canonical direct ref 200；Trace 压缩节点身份解析 200；Memory fragment 保留；命名方案应用 200 且 state=active；User Turn 正常回答 status=answered。
- 未调用真实收费模型或供应商网络测试，未使用任何供应商密钥。

验证命令：

```bash
python -m pytest tests/gateway/endpoint tests/kernel/context tests/plugins/home/test_home_engine.py tests/infra/test_references.py -m 'not external'
python -m pytest -m 'not external' --durations=8 -ra
ty check --python /absolute/path/to/review-venv/bin/python
```

测试通过与 R4 仍待完成可以同时成立：现有测试尚未把实际输出与交接文件连起来。本次不将手写样例校验通过视作前端契约完成。

## 7. 本次文件变更

仅新增本文；未修改实现、fixtures 或用户已经归档的执行计划。

建议 commit：

```text
docs: recheck visualization backend fixes at d0b3e11
```
