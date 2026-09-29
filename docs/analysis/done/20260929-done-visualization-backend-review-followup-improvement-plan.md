# Visualization 后端 Review 收口改进执行计划

> 日期：2026-09-29；状态：done。  
> 依据：`docs/analysis/done/20260929-done-visualization-backend-review-5993913.md`、根目录 `AGENTS.md`、当前 Endpoint/Context/资源 owner 实现。  
> 目标：在不引入第二套调度、检索、资源存储或 UI 专用状态体系的前提下，修正正常导航断链，并完成可依赖的前端 v2 接口交接。

## 1. Review 判断与范围

本次 Review 提出的 R1～R4 均合理，但性质不同：

| 项目 | 判断 | 性质 | 本计划处理 |
| --- | --- | --- | --- |
| R1 Context `root_refs` | 合理 | 真实正常路径断链 | 修复 |
| R2 Trace 压缩节点与 Memory fragment | 合理 | 统一 Resource resolve 丢失 owner 身份/锚点 | 修复 |
| R3 Home direct refs | 合理 | Home owner 的 canonical Link 映射重复且结果不一致 | 修复 |
| R4 Endpoint 契约交接 | 合理 | 代码主路径基本存在，但机器可核对协议和样例不足 | 补齐 |

这些问题不要求重新设计 Agent、Turn、Context、Search 或 Endpoint 生命周期。现有 owner、
generation/day lease、只读浏览、SearchPage/DisclosurePage 和 Observation 语义保留不变。
本轮只处理从现有真实事实到前端入口的投影一致性。

## 2. 设计约束

1. `SegmentDescriptor.ref_prefixes` 继续只表示 Context 路由范围，不再把它误称为可点击根节点。
2. 可导航 root 必须由实际打开的 segment owner 提供；Kernel 不硬编码 `session:map`、Trace 语法或 Home Link。
3. Resource resolve 只复用 owner 的身份解析和已有绑定，不建立万能 Resource Gateway，不复制资源内容。
4. Home、Memory、Trace 的 canonical/reference 规则仍由各自 owner 负责；`infra.references` 只保留通用 Markdown 和 locator 基础能力。
5. `ResourceLocator` 的动态绑定、day、turn、view 和 fragment 必须保持可解释；不得把历史或动态引用替换为当前 latest。
6. Endpoint 契约层只描述对外稳定边界。固定外壳可以有薄的 gateway response schema；多态正文继续引用 owner 的 SearchPage/DisclosurePage/JsonValue，不复制业务模型。
7. 只补正常主路径、空态、等待/提问、完成和代表性失败；不为没有真实消费者的极端恢复场景增加协议。

## 3. R1：Context 提供真实可打开 roots

### 3.1 目标语义

`GET /v2/turns/{turn_id}/context` 返回的 `segments[].root_refs` 必须是可以直接交给同一
Turn 的 `/context/inspect` 的公开 root。`ref_prefixes` 仍仅供 Context 内部路由和能力声明。

已知正常 root：

- Session segment：`session:map`；
- Trace segment：`turn:trace@<turn_id>`；
- Archived Workspace segment：`workspace_archive:<day>`；
- 没有公开导航入口的 segment：`[]`，不虚构路径。

### 3.2 实施步骤

1. 在 `kernel/context/segments` 增加窄的导航协议，例如 `NavigableSegment.navigation_refs()`，
   不改变 `InspectableSegment` 的 owner inspect 契约。
2. `TraceSegment` 返回 `TurnTraceHeap.head_ref()`；`SessionSegment` 返回
   `session:map`；`ArchivedWorkspaceSegment` 在存在 archive view 时返回 archive root。
3. `TurnSegments` 提供按已打开 segment 汇总 navigation refs 的只读方法；未知或无内容 owner
   返回空 tuple，不由 Kernel 拼接字符串。
4. `ContextEngine.installed_overview()` 将 `root_refs` 改为上述 owner 投影；保留
   `available_refs`、`loaded_refs`、`protected_refs` 原语义。
5. 更新 `docs/design/context.md`、`docs/endpoint/inspection.md` 和 Endpoint 样例，明确
   descriptor route 与 navigation root 的区别。

### 3.3 验证

- Overview 中每个返回的 root 在同一 Turn 内直接 inspect 成功，或返回 owner 定义的空内容。
- 覆盖 Session map、Trace head、压缩 Trace branch/leaf、归档 Workspace root。
- Inspect 前后 Context 的 installed segments、selection/protection 和 Context 生命周期不变。
- 不新增 load、evict、seal、模型调用或持久化副作用。

## 4. R2：Resource resolve 复用 Trace owner 身份并保留 Memory fragment

### 4.1 Trace 身份

Trace owner 公开支持以下身份，Resource resolve 必须保留原字符串和 Turn 绑定：

- head：`turn:trace@<turn_id>`；
- compact branch/leaf：`turn:trace/<turn_id>/<node_id>`；
- head 下的 entry/action/input fact：`turn:trace@<turn_id>#entry/...`、
  `#action/...`、`#input/...`。

Context/Trace owner 提供窄的 `resolve_reference`/身份校验入口。Endpoint 不解析 Trace 内部
节点，也不把 leaf/branch 归一化为 head。Resource locator 只表达 `ref`、`turn_id`、可用
`day`；正文继续由 Context inspect 读取。已关闭的 live Context 仍保持既有不可读边界。

### 4.2 实施步骤

1. 在 Trace owner 内集中维护公开 ref 的解析/校验，复用 `head_ref()`、node 表和已有
   entry/action/input 身份规则；不要在 `agent/services.py` 写第二套正则和节点语义。
2. 为 `ContextEngine`/Trace segment 暴露只读身份解析门面，供 SDK Resource resolve 使用；
   解析失败映射为稳定 `resource.invalid_reference` 或既有 Context request failure。
3. 扩展 `AgentRuntimeServices.resolve_resource()` 的 Trace 分支，识别 head、node 和 fact
   ref，校验传入 `turn_id` 与 ref 中 Turn 一致，保留原 ref。
4. 在 `infra.references` 或资源服务内部增加单一的 locator fragment 组合辅助能力：对绑定
   locator 的 `link` 或 `ref` 复制并追加 fragment，不修改 Context/Session 共享 binding。
5. 动态 `memory:current/latest/target` 先解析原有 turn/day binding，再将请求 fragment
   追加到目标 locator；显式 day 分支同样保留 day 和 fragment。不得用当前 latest 重新绑定。
6. 更新 `docs/endpoint/inspection.md`、`docs/endpoint/frontend-integration.md` 的动态资源
   说明，给出 Trace node 和 Memory fragment 样例。

### 4.3 验证

- 真实 TraceHeap 生成的 head、branch、leaf、entry/action/input ref 可 resolve，返回原 ref。
- ref 中 Turn 与显式 `turn_id` 不一致时稳定拒绝。
- Memory 动态引用有 fragment 与无 fragment 的 locator 只在 fragment 上不同，day/turn/view
  绑定不变。
- 解析过程不读取正文、不建立历史 Context 快照、不修改 Context/Session binding。

## 5. R3：Home direct refs 与 canonical Link 统一

### 5.1 目标语义

Home 正文中解析出的每个受支持 direct ref 都必须使用 Home layout 的正式身份：

- top：`home:agent@...`、`home:skills@...`；
- prompt mount：`home:skills_domain:...`、`home:skills_action:...`；
- progressive resource：`home:agent/...`、`home:skills/...`；
- fragment 原样保留。

### 5.2 实施步骤

1. 在 Home owner 内建立一个 canonical markdown reference helper，输入正文和 origin Link，
   通过现有 `resolve_relative()` 与 `layout.link_for_relative()` 完成映射。
2. `browse_content()`、`inspect()` 的 `direct_refs` 统一使用该 helper；不再直接调用通用
   `relative_reference()` 生成最终对外 Link。
3. Home Search backlink/evidence 路径也先经过 Home canonical mapping，再交给
   `ReferenceResolver` 比较，避免 direct refs 与 backlink search 使用两种身份。
4. 不放宽 `HomeResourceLink` 以接受错误的 prompt mount 路径，不在前端添加转换表。
5. 更新 Home owner 测试和 `docs/design/agent_home.md`/Endpoint 样例，覆盖 actual/effective、
   top、resource、domain/action guidance、fragment。

### 5.3 验证

- `home/content` 返回的每个 direct ref 都能通过 `/v2/resources/resolve` 继续打开。
- canonical catalog、content locator、direct_refs 对同一资源使用同一身份。
- 相对链接指向 domain/action guidance 时返回 prompt mount canonical Link。
- actual/effective 只影响 owner 视图，不改变 Link 语法；浏览不写 runtime overlay。

## 6. R4：建立可依赖的 v2 Endpoint 契约交接

### 6.1 契约边界

保留 owner 的 `to_json()` 作为运行时事实序列化来源，不为每个插件重新建立一套业务 DTO。
新增的是 Gateway 对外契约层：

- 固定外壳使用薄的 response schema，必要时挂到 FastAPI `response_model`/OpenAPI；
- 分页、DisclosurePage、SearchPage、Job output 等多态正文使用可校验 JSON Schema 和真实
  fixture，不强行包装成另一套业务对象；
- schema 只约束稳定字段、枚举、`null`/缺省、分页和失效语义；owner 扩展字段保留明确
  extension 边界。

### 6.2 契约文件与文档

新增 `docs/endpoint/contracts/`，至少包含：

1. `README.md`：协议版本、字段稳定性、错误 code、分页/continuation、generation/day
   lease、失效和只读副作用规则；
2. 固定外壳 schema：runtime/status、Turn receipt/snapshot、Config active/saved、Preset、
   ResourceLocator、ContextOverview/SegmentView、InteractionPage、JobSnapshot/Output；
3. 多态页面 schema：DisclosurePage、SearchPage、Home/Memory document、MCP/ACP views；
4. `examples/`：由实际 SDK/ASGI owner 序列化产生、去除 secret 和机器绝对路径的 JSON 样例。

样例至少覆盖：

- active/saved、preset 和 apply/reload；
- queued、pending、ask、choice/text reply、finished Session；
- Context roots、压缩 Trace、continuation；
- Home actual/effective/diff、Memory redirect 和动态 fragment；
- Search evidence/coverage/续页；
- Job output、ACP connection/delegation、MCP server/tool；
- LLM/JEV/Embedding 用途与 observation 关联。

同步更新：

- `docs/endpoint/inspection.md`：补齐 Context/Session/资源/Job 返回结构和样例；
- `docs/endpoint/configuration.md`：补齐 active/saved、apply、reload、preset 流程；
- `docs/endpoint/frontend-integration.md`：统一当前 v2 接入顺序、错误处理和资源路由；
- `docs/endpoint/index.md`：链接 contracts 与样例入口；
- `docs/analysis/20260928-visualization-frontend-implementation-plan.md`：F0 以该契约
  为唯一输入，不再从 Python 内部字典猜字段。

### 6.3 机器校验与 OpenAPI

1. 对稳定固定外壳补 response model 或 OpenAPI response schema，使 `/openapi.json` 不再把
   关键 200 响应全部暴露为空 schema。
2. 对多态 page 通过 JSON Schema 明确公共 envelope；`items` 的 owner-specific 内容保留
   `oneOf`/扩展边界，引用已有 SearchPage/DisclosurePage 语义。
3. 增加契约测试：以真实 Endpoint/SDK 序列化生成代表性响应，使用 JSON Schema 校验；测试
   不比较随机 ID、时间或正文顺序以外的无关细节。
4. 示例生成不调用真实 provider/network，不写入用户 Home/Memory/Workspace；使用测试 fake
   和临时 owner，必要时规范化 identity、时间和路径。

## 7. 实施顺序与交付步骤

### I0：基线与契约冻结

- 重新核对 AGENTS.md、Review、当前 done backend plan；确认 R1～R4 不扩大为新架构。
- 建立 R1～R4 测试矩阵和 endpoint contract 清单。

### I1：Context navigation roots

- 实现导航协议和三个 owner 投影；修改 overview；补 Kernel/Endpoint 正常路径测试。
- 同步 Context/inspection 文档。

### I2：Resource identity/fragments

- 实现 Trace owner identity resolver；修正 Resource resolve；加入动态 Memory fragment helper。
- 补 Resource resolve 与 Context inspect 的跨接口测试。

### I3：Home canonical refs

- 收敛 Home direct refs 和 Search backlink 的 canonical helper。
- 补 Home owner、Endpoint resolve/read 和 actual/effective 测试。

### I4：Endpoint contract artifacts

- 增加薄 response schema/OpenAPI response 描述和 `docs/endpoint/contracts/` schemas/examples。
- 同步 endpoint 文档、frontend-integration 和前端计划 F0 入口。
- 增加 schema validation 和代表性 ASGI/SDK fixture tests。

### I5：收口验证与状态更新

- 运行 Fast 定向测试，再运行 `scripts/test.ps1 -Suite Full` 和 `scripts/typecheck.ps1`。
- 执行 `git diff --check`，检查文档、样例、OpenAPI 与实际响应一致。
- 只有 R1～R4、文档、样例和验证全部完成后，才将本计划改名为带 `-done-` 的文件并移入
  `docs/analysis/done/`；同时修正原 backend plan 的验收说明，不宣称前端已完成。

## 8. 明确不做

- 不恢复 v1 兼容路由；前端直接迁移 v2。
- 不为 Context 历史内容建立第二套持久数据库或 UI 快照库。
- 不建立通用 Resource Gateway、通用 Action RPC、第二套 Search 或第二套 continuation。
- 不把 `ref_prefixes` 改成带 Turn 身份的 descriptor 字段。
- 不为所有 ActionResult 添加通用 `content_preview`。
- 不将 OpenAPI/fixture 生成器扩展成动态插件发现平台；只提供本轮真实消费者需要的稳定契约。

## 9. 完成验收清单

- [x] Context overview 的 root_refs 全部可直接 inspect，且与 descriptor route 分离。
- [x] Trace head/node/fact ref 可 resolve；动态 Memory fragment/day/turn 绑定保留。
- [x] Home direct refs、catalog、content、resolve/read、Search backlink 使用统一 canonical Link。
- [x] `/openapi.json` 对关键固定响应有可用 schema；多态响应有可校验 JSON Schema。
- [x] contracts/examples 覆盖正常、空态、等待/提问、完成、分页和代表性失败。
- [x] frontend-integration 与 v2 frontend plan 不再要求前端猜字段或保留旧兼容分支。
- [x] Full 测试、ty、diff check 通过；本轮变更已完成，待提交的工作区差异属于本轮交付。

## 10. 完成记录

R1–R3 已由 owner 导航协议、Trace 身份解析、动态 locator fragment 保留和
Home canonical markdown helper 落地。R4 已由关键 v2 response models、OpenAPI
输出、contracts schemas/examples、代表性 fixture 校验测试和 endpoint OpenAPI
断言落地。验证结果：`scripts/test.ps1 -Suite Full` 为 1203 passed、25 deselected；
`scripts/typecheck.ps1` 使用 Conda `TinySoul` 的 ty 0.0.84 通过；`git diff --check`
通过。响应模型使用 `extra="allow"` 保留 owner 扩展字段，分页内容仍由原 owner
投影负责，不新增第二套业务 DTO 或资源存储。
