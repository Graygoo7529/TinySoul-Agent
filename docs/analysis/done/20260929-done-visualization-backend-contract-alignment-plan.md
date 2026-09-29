# Visualization 后端契约对齐与前端交接执行计划

> 日期：2026-09-29；状态：done。依据 [后端复核](20260929-done-visualization-backend-recheck-d0b3e11.md) 建立；C0–C5 的实现、交接材料与本地验证已逐项完成。
> 目标是在前端 F0 接口冻结前，把后端已经提供的正常能力用同一套可验证的 Endpoint 契约、样例和接入说明表达清楚。本计划不改变运行时、owner、Search 语义或前端实现。

## 1. 复核结论

本次 review 的 R4 判断合理，属于真实的契约交接缺口：后端正常能力已经存在，但部分公共响应模型、`docs/endpoint/contracts/` 样例、OpenAPI/JSON Schema 和契约测试没有描述同一份响应。前端如果直接按现有样例生成类型，会把错误结构固化到页面逻辑中。

R1–R3 不需要回退：Context root、Trace/Memory 动态 locator 和 Home canonical ref 已由各自 owner 提供，继续沿用当前实现。R4 也不要求再开一轮后端架构重构，重点是把真实输出固定为清晰的 HTTP 边界并建立最小的真实响应验证。

| review 建议 | 判断 | 本计划处理方式 |
| --- | --- | --- |
| 修正 Disclosure、Home/Memory、Job、Turn、Config 样例 | 合理且必要 | 由实际 SDK/ASGI 路径生成小型正常样例，保留空页、续页和等待状态 |
| 补齐公共响应模型和 OpenAPI/JSON Schema 字段 | 合理且必要 | 以 HTTP Pydantic 模型描述固定字段，OpenAPI 自动输出；独立 Schema 只保留边界校验并做一致性检查 |
| 契约测试需要连接真实响应 | 合理且必要 | 在现有测试中加入代表性 Endpoint/SDK 响应验证，不做全页面快照 |
| 删除虚构的 reset 回执、修正 apply/preset/Turn 状态 | 合理且必要 | 以当前配置和 Turn owner 的实际状态为准，前端本地 reset 不形成后端接口 |
| 重新设计响应 DTO 平台或增加兼容层 | 不合理 | 保留 owner 序列化和现有 v2 路径，不引入第二套业务对象或旧字段别名 |

当前没有发现需要改变的核心设计语义。`ActionResult` 继续由具体 Action 结果族提供可呈现内容；本计划只修正 Endpoint 对已有结果、上下文和运行事实的描述，不增加通用 `content_preview`。

## 2. 统一契约边界

### 2.1 唯一事实来源

owner 的 typed result 和其现有 `to_json()` 是业务事实来源；HTTP Pydantic response model 负责声明前端可依赖的固定字段；FastAPI 由该模型生成 OpenAPI。`docs/endpoint/contracts/schemas/` 作为可独立消费的校验材料保留，但其中固定字段必须与 Pydantic/OpenAPI 一致，并由测试检查，不再独立发明另一套响应形状。

多态 owner 内容仍使用有界 JSON 值，不能把 Session、Home、Memory、Workspace、Job 或 Search 的内部模型复制成新的通用 DTO。字段位置、空值、状态名和续页键属于契约；内部 revision、digest、模型短 ID 和物理路径不进入前端协议。

### 2.2 响应族

| 响应族 | 对外固定语义 | 主要消费者 |
| --- | --- | --- |
| 普通读取页 | 必需 `items`，按 owner 提供 `ref/kind/view`、`next_continuation`、`content_fragment`、`truncated`、`metadata` | Home、Memory、Context/Session Disclosure、Workspace 读取 |
| Context 段正文 | `turn_id/segment_id/messages`，可选 `next_continuation/content_fragment`；复用普通分页机制 | 已安装语境正文阅读 |
| SearchPage | `result_ref/scope/source/items/coverage/page/continuation`；真实 `evidence`、`evaluation` 和覆盖信息保持原结构 | Home/Memory/Workspace Search、Search 结果卡片 |
| TurnSnapshot | Turn 身份与状态、Jobs，以及必有但可为空的 `question`、`budget_request`、`wait_reason`、`result` | 对话恢复、QuestionCard、预算卡片、完成状态 |
| InteractionPage | 普通读取页加 `turn_id/day`，按 live/history 来源提供 generation、状态、待受理输入和结果 | 对话时间线与历史恢复 |
| JobOutputPage | 按 channel 的 `items`、`next_continuation`、`truncated`、`result_locators` | Job 输出面板 |
| Configuration/Preset | Config 状态使用 `view/generation_id/activity/pending_reload/fields/sources`；Preset 独立使用 `id` 与匹配状态，apply 请求才使用 `preset_id` | 设置草稿、整批应用、方案切换 |
| ResourceResolve | canonical locator、能力和来源解析结果 | ResourceRouter、Home/Memory/Workspace 跳转 |

普通读取页和 SearchPage 继续是不同协议。Search 不再继承旧的 `operation/candidates/query` 示例字段；普通页先消费本页 items/fragment，再按 `next_continuation` 判断是否续读，最后一个 fragment 可以没有续页 token。配置的本地 reset 不请求后端，后端只描述实际 saved/active/apply 状态。

### 2.3 生命周期与续页

所有 continuation 与其实际读取内容、generation/day/Turn 或 SDK service lease 绑定。续页返回仍使用 owner 定义的失效原因；前端在失效后重新取得对应对象，不把 token 转换为新的查询或自动重放带副作用的 mutation。SearchPage/DisclosurePage 不再包一层普通分页；Job 输出按各 channel 的独立位置续读。

## 3. 执行步骤

### C0：契约清单和真实响应基线

1. 逐路由记录当前 Endpoint response model、owner serializer、公开文档和已有 fixture，建立字段差异表。
2. 以本地 fake/fixture 模型和临时项目执行 SDK/ASGI 正常路径，取得以下代表性响应：Context trace、Home 长正文/fragment、Memory 文档、Job 多 channel 输出、Turn waiting/question/budget 与 answered、Config saved/active/apply、Preset、Search、ResourceResolve。
3. 对动态 ID、日期、时间和 continuation 做规范化；不删掉字段、空值、状态名或页边界语义。

### C1：HTTP 公共响应模型

1. 收紧 `tinysoul/gateway/endpoint/http/schemas/responses.py` 的固定字段，至少覆盖普通页的 `next_continuation/content_fragment`、SearchPage 的真实字段、Turn 的问题/预算/等待/结果字段、Config 的 `fields/activity` 和 Preset 的 `id`/匹配状态。
2. 对 Job 列表与 Job 输出使用能够表达其实际字段的 response model；普通页仍只承载 owner 内容，不把 Job 或 Search 强行解释成普通页。
3. 保留 `extra="allow"` 作为 owner 扩展边界，但不再用它替代已确认字段的声明；必要的动态对象使用 JSON-safe 的明确类型边界。
4. 更新对应 route 的 `response_model`，确保公开 OpenAPI 与真实 `to_json()` 输出相符。不得修改 owner 正常业务结果来迎合旧样例。

### C2：Schema、样例和接入说明

1. 更新 `docs/endpoint/contracts/schemas/` 中的 page、Search、Turn、configuration、job 相关 Schema，删除虚构 reset 回执和旧 Search 字段，补齐实际固定字段与续页键。
2. 重新生成或规范化 `examples/` 中的 Context/Trace、Home/Memory、Job、Config/Preset、Turn waiting/answered、Search 和资源定位样例；`search-evidence.json` 也必须继续与真实 `SearchPage.to_json()` 同源。
3. 更新 `docs/endpoint/frontend-integration.md`，把 `/v2/config/apply`、saved/active、Preset 和前端本地 reset 说明为主流程；保留 PATCH/reload 的真实边界，不把两者拼成前端自行猜测的流程。
4. 同步 `docs/endpoint/inspection.md`、`configuration.md` 以及前端计划中的接口前置说明，明确空页、fragment、Question/预算和完成状态 `answered` 的含义。

### C3：真实契约验证

在现有 `tests/gateway/endpoint/test_contracts.py` 基础上增加最小代表性验证：

1. 每个核心样例同时通过独立 Schema 和对应 Pydantic response model；固定字段集合、必需字段和字段类型不能只靠 `extra="allow"` 通过。
2. 运行本地 Endpoint/SDK 获取至少一份真实响应，验证其可以被公开 response model 解析，并与相应样例的字段位置、状态和分页键一致。
3. 续页覆盖一条可继续页和一条空 `items` 但仍有 fragment/continuation 的路径；Search 覆盖 evidence/evaluation/coverage/page；Job 覆盖多 channel；Turn 覆盖 question/budget 与 answered；Config 覆盖 apply 后 active 和 preset `id`。
4. 增加 OpenAPI 与独立 Schema 的固定字段一致性检查。动态 owner 内容只检查 JSON-safe 形状，不做全量字段快照。

### C4：前端交接核对

1. 用修正后的样例和 OpenAPI 重新检查前端计划 F0 的 API 类型来源，不为旧样例保留兼容分支。
2. 确认前端可以直接实现：Context/资源渐进读取、真实 Search evidence、Question/Reply/预算恢复、Job 输出续读、Config apply/preset、ResourceRouter 和 Action 结果族 renderer。
3. 将仍未提供的能力只记录为 `visualization/docs/demand/` 的具体缺口；本计划不通过 mock 宣称后端已经实现。

### C5：最终门禁和归档

1. 运行 Endpoint/Context/Home/Memory/Job/Config 定向测试，再运行 `scripts/test.ps1 -Suite Full` 和 `scripts/typecheck.ps1`。
2. 执行 `git diff --check`，检查文档、OpenAPI、Schema、样例和测试没有旧字段、旧状态或 reset 回执残留。
3. 只有 C0–C5 的实现、文档同步和验证均完成后，将本计划改为 `done` 并移动到 `docs/analysis/done/`；R1–R3 的修复结论保持不变。

## 4. 文件范围

预期修改范围仅包括：

- `tinysoul/gateway/endpoint/http/schemas/responses.py` 及确有需要的 route response model 声明；
- `docs/endpoint/contracts/schemas/`、`docs/endpoint/contracts/examples/`；
- `docs/endpoint/frontend-integration.md`、`docs/endpoint/inspection.md`、`docs/endpoint/configuration.md` 及前端计划的契约前置说明；
- `tests/gateway/endpoint/test_contracts.py` 和必要的最小 Endpoint 契约测试。

不修改 `kernel` 调度、Context/Session/Home/Memory/Workspace/Search/Job 的业务所有权，不增加通用 Action RPC、第二套分页/检索协议、旧字段兼容层、前端代码或供应商网络测试。

## 5. 完成判定

- 公开 response model、OpenAPI、独立 Schema、代表性样例和真实响应具有相同的固定字段与正常状态语义。
- 前端无需从日志猜测 Turn 终态、从 `children/content` 猜测 Disclosure 导航、从旧 `candidates` 猜测 Search 结果，或寻找不存在的后端 reset 回执。
- Home/Memory/Context/Workspace、Search、Job、Question、Config/Preset 和 ResourceRouter 的正常主线均有可直接消费的字段、分页和失效边界。
- 现有 owner 语义、R1–R3 修复和 v2 路由保持不变；没有为了契约统一引入第二套业务状态或冗余抽象。

## 6. 实施核对

### C0–C1：响应声明与实际来源

| 实际来源及路径 | 公共声明 | 已校正的差异 |
| --- | --- | --- |
| Home/Memory owner + PageOptions；Context/Session Disclosure | PageResponse | items 必需，声明 view、fragment、next_continuation；不伪造顶层正文或 children |
| SDK Context overview | ContextOverviewResponse | root_refs、加载引用和 measurement 明确声明 |
| ContextEngine.installed_segment；`/v2/turns/{turn_id}/context/segments/{segment_id}` | ContextMessagesResponse | 集合字段是 messages 而非 items；保留原 message_index 和共用分页 |
| SearchPage.to_json；`/v2/home/search` | SearchResponse | 独立 items/evidence、coverage、page，不再声明 candidates/operation |
| SDK TurnSnapshot；`/v2/turns/{turn_id}` | TurnResponse | 等待原因、问题、预算和结果保留显式 null，正常回答为 answered |
| Session interaction projection + SDK live/history 包络 | InteractionPageResponse | 页级 Turn/day 与适用的 state/status/result、pending_items 分开 |
| kernel/jobs + execution/ACP backend；SDK 加 day locator | JobListResponse / JobDetailResponse / JobOutputResponse | 列表、详情、双通道输出与续读分别声明；stop 返回详情而非命令回执 |
| ConfigController + generation activation；`/v2/config/*` | ConfigResponse / ConfigMutationResponse / PresetResponse | fields/activity、saved/active、Preset id 与匹配状态；方案不重复挂到 Config 状态 |

这些声明只在 HTTP 边界描述现有输出，没有修改 owner 存储、运行状态机或 Action 结果语义。

### C2–C4：交接材料与验证

- `schemas/` 从公开响应模型的 serialization schema 导出；固定字段、required 和类型通过与导出结果及实际 OpenAPI 比较验证。动态 owner 内容保持 JsonValue，不复制业务 DTO。
- `test_contracts.collect_contract_responses` 使用临时项目、真实 owner/SDK/ASGI 与受控模型输出，产出 24 组正常响应；仅规范化身份、时间和 opaque token。Home/Memory diff/redirect、ACP/MCP 未配置目录和模型用途观察也有实际来源。
- Home 长正文走完全部 fragment 并解码；Job 验证 stdout/stderr 与不重放的续读；同一 Turn 的 question/budget 同时待决后，经 reply/grant 恢复为 answered，InteractionPage 续页取得关联问题与回复。
- Config apply 的 HTTP 激活、saved/active 和 Preset 响应已验证；小型 ConfigController 样例保留来源、fields 和未设置项的 null，不把本地 reset 写成 API。
- Endpoint 接入文档和前端计划已同步真实字段、分页和结果族。前端 F0 可从 OpenAPI/独立 Schema 与样例接入，不增加旧字段兼容分支。未发现本计划范围内需另提后端能力需求的缺口；未修改前端代码或验证前端页面。

### C5：验收记录

- Endpoint 定向测试：49 passed。
- `scripts/typecheck.ps1`：通过（TinySoul Python 3.13.12 / ty 0.0.84）。
- 全仓 Fast 首次检查：1212 passed、2 failed；失败定位为本轮 PageResponse 收紧后误用于 Context 段正文，已按真实 messages 响应单独声明，原 SDK/HTTP 回归路径复测 2 passed。未放宽 items 要求来掩盖不同响应形状。
- `scripts/test.ps1 -Suite Full`：1220 passed、25 deselected，包含全部非 external 本地测试及 wheel 验收。
- `git diff --check`：通过。未运行真实供应商/network 测试，未使用供应商密钥。

已关闭原 review 的 R4 契约交接项；R1–R3 结论不变。review 提到的 Trace 宽泛异常捕获属于非阻塞整理建议，不在本计划的 HTTP 契约范围内，未将其记作已修改。
