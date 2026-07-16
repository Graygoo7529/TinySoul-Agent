# 20260715 Agent Capabilities And Action Expansion Plan

## 状态

status: pending

依赖（已满足）：Stage 8 发布与初始化闭环、`20260715-done-default agent home content plan.md`。

## 目标

基于现有 Action backend mechanism 扩充真实、可维护的 Agent 能力。该计划不以保留 domain 或展示 backend 为目标；只有具备明确用户价值、输入输出协议和安全边界的 action 才进入内置 Catalog。

## 组织边界

1. 具有独立链接、持久化或 runtime/trap 生命周期的能力才建立顶层业务模块；
2. 无独立持久状态的轻量能力放在 `tinysoul/capabilities/<capability>/`，由能力包的 service/client/evaluator 承担业务逻辑，由 `actions.py` 提供 ActionEngine registrar/executor 适配；
3. 通用执行机制继续位于 `tinysoul.action.backends`；capability 不重复实现 subprocess、temporary script、LLM task 或 ActionResult 管线；
4. Catalog 只描述真实 domain/action，空 domain、预留 action、未注册 handler 和通用“执行任意模型脚本”均禁止；
5. 需要硬停止的外部工作使用受控 subprocess/script backend；native 仅承载可协作取消且受信任的进程内逻辑。

## 推荐推进路线

本计划将 TinySoul 定位为本地、项目作用域内的知识工作 Agent。推进顺序优先补齐“取得内容、转换内容、受控执行、确定性处理”，再扩展知识图检索、外部连接器和交互界面。以下 Stage 只表示本能力扩展计划内部的顺序，不复用此前 Daily Lifecycle 的 Stage 编号；每个 Stage 都必须在语义确认、实现和验收完成后再进入下一项：

1. **Stage 1 Document Conversion**：在 Workspace Link 边界内把受支持文档转换为可检查、可作为后续 action reference 的 Markdown 资源；
2. **Stage 2 Read-only Web Research**：提供有界搜索和网页读取，返回来源 Link、摘要与引用信息，不在该阶段引入登录、提交表单或其它写操作；
3. **Stage 3 Controlled Project Tasks**：只暴露项目拥有的具名工作流和固定参数，不提供任意 shell 字符串或模型自行拼接命令；
4. **Stage 4 Deterministic Utilities**：补充数学、时间、编码和结构化格式转换等具有明确 schema、纯输入输出和稳定失败语义的工具；
5. **Stage 5 Knowledge Retrieval Enhancements**：实现 Home Backlink，并在真实数据规模证明需要后增强 Memory 片段检索；
6. **Stage 6 Connectors And Interaction**：按真实使用场景增加外部服务连接器、文件导入导出、用户审批和更丰富的交互入口，不预先建设通用插件平台。

该顺序不是要求一次性完成全部能力。Stage 1 至 Stage 4 应各自形成独立、可使用的能力闭环；Stage 5 和 Stage 6 只有在实际使用反馈给出明确查询或连接需求时才进入实施。

### Stage 1 Document Conversion

#### 目标与建议边界

Stage 1 解决 Workspace 已能识别 `document`、但文档不能进入 action 内部 task prompt 的现有断点。推荐建立一个无独立持久状态的 `document` capability，并新增一个具名转换 action；以下是待维护者确认的实施建议，不表示已经实现：

- domain/action 建议使用 `document.convert`，只表达文档到 Workspace 文本资源的确定性转换，不同时承担总结、改写、OCR 校对或 Home/Memory 写入；
- 输入、输出都使用 Workspace Link。`source_link` 必须指向已存在且受支持的 `document` resource，`target_link` 必须是 Markdown 文本目标；模型不传入绝对路径、临时目录、解析器命令或物理 Workspace root；
- Workspace 继续拥有 Link 解析、资源读取、原子写入、manifest reconciliation、retention 和 Trash 语义；document capability 只拥有格式识别、解析、规范化及转换结果，不直接维护第二套文件索引；
- 转换正文写入 `target_link`，ActionResult 只返回有界元数据，例如 source/target Link、输入/输出 digest、页数或段落数、输出字符数和有界 warning，不把完整正文写入 TurnTrace；
- 转换是确定性本地能力，不需要 LLM Task。转换后的 Markdown 可由现有 `workspace`/`core` action 通过 `reference_links` 在其局部 task prompt 中读取；
- 不受信任文档的解析必须有文件大小、页数或结构规模、输出字符数和运行时长上限。需要硬停止的解析工作应在受控子进程中执行，并复用 Action 的取消/超时语义；
- unsupported format、encrypted/password required、scanned content requiring OCR、limit exceeded、empty extraction 和 target conflict 属于局部 ActionResult 失败；依赖未安装、配置非法、Workspace 不变量破坏属于装配或模块边界失败；
- 默认不得覆盖已存在目标；若允许覆盖，应使用显式 `overwrite`，并确认是否同时要求 source/target digest guard。转换失败不得留下半成品目标或未清理的临时文件。

#### 建议组织结构

若上述边界确认，建议建立：

```text
tinysoul/capabilities/document/
  __init__.py
  actions.py       # ActionExecutor 与 registrar 适配
  service.py       # 转换编排、限制和结果模型
  errors.py        # capability contract/invariant/processing failure
  parsers/         # 按已确认格式拆分的解析适配器

tinysoul/action/catalog/document/
  domain.toml
  actions/convert.toml
```

AppBuilder 只解析该能力的配置、构造 service 并调用 registrar；parser 依赖、文档格式细节和 Workspace 写入编排不得进入 AppBuilder。若 worker 需要子进程隔离，应使用固定入口和结构化输入，不把模型参数直接变成 `argv` 或 shell 命令。

结合当前实现，子进程隔离还需要两个受控的基础边界：

1. Workspace 增加有字节上限的 document read/stage API，返回 Link、media type、suffix、bytes/digest 等稳定对象；capability 不直接用 `WorkspaceEngine.path_for()` 绕过资源类型、大小和一致性检查；
2. Action subprocess backend 将进程终止、超时、stdout/stderr 上限与原始 process outcome 抽成内部可复用执行原语，现有 `SubprocessActionExecutor` 继续负责把该 outcome 映射为普通 subprocess ActionResult；document executor 使用同一原语运行固定 worker，再校验 worker 结果并通过 `WorkspaceEngine.write_text()` 原子提交 Markdown。

worker 应只读取 host 生成的临时输入并写入 host 指定的临时输出；host 在转换前后校验 source digest，在完整输出通过 UTF-8、非空和字符上限校验后才写入 `target_link`。这使解析进程不能直接修改 Workspace manifest，也不会让大段 Markdown 经过 Action stdout 或 TurnTrace。

#### 验收范围

- parser/service 单元测试覆盖正常提取、空内容、损坏/加密/不支持文档和各项限制；
- action 测试覆盖 Workspace Link 校验、目标冲突、overwrite/digest、metadata-only feedback、超时与失败后无半成品；
- Action Catalog/registrar 测试保证 handler、domain 和 schema 一致；
- Phase2/Phase3 集成测试证明模型只传 Link，Phase3 转换后 manifest 出现新的 Markdown resource；
- App 工作流验收证明“扫描文档 -> 转换 -> 作为 reference 使用”闭环成立；测试使用隔离的项目目录和 fixture，不依赖仓库真实 runtime/workspace。

#### Stage 1 待确认

1. **输入格式**：建议先支持文本型 PDF 与 DOCX；是否同时纳入 PPTX、XLSX、HTML、RTF 或其它格式？
2. **OCR**：建议 Stage 1 不提供 OCR，扫描型 PDF 返回稳定 `ocr_required`；是否接受该边界？
3. **Markdown 保真度**：需要保留哪些结构，例如标题、段落、列表、表格、超链接、脚注、分页标记、图片占位和文档元数据？
4. **嵌入资源**：图片和附件是忽略、生成有界占位，还是提取为独立 Workspace resource？
5. **依赖交付**：解析依赖作为主安装依赖，还是定义 `document` optional extra，并在依赖缺失时不注册 action 或启动失败？
6. **资源上限**：需确认单文件字节数、最大页数/结构节点、输出字符数、action timeout 和 warning 数量上限；这些限制是内置常量还是项目 TOML 配置？
7. **目标写入**：建议目标必须显式传入 `.md` Link、默认拒绝覆盖并支持可选 `overwrite`；是否需要 `expected_source_digest`、`expected_target_digest`，以及输出 retention 是显式参数、继承 source 还是固定为 `day`？
8. **解析隔离**：是否接受所有第三方文档解析都通过固定 worker 子进程执行，以获得硬超时和进程级隔离？
9. **格式选择**：action 是否只根据 source media type/suffix 自动选择 parser，还是允许显式 `source_format` 用于处理缺失或错误 MIME？
10. **HOW 投影**：建议依靠 Catalog 的 tool/semantic 定义和框架自动维护的 `home:how_domain:document`，不新增通用 HOW；`document.convert` 不含内部 LLM Task，因此不需要 action HOW。是否接受该边界？

### 后续 Stage 的确认入口

- **Stage 2**：确认搜索/抓取供应商、凭据配置、网络访问域、robots/重定向策略、来源引用、正文上限、缓存与隐私边界；
- **Stage 3**：确认首批真实项目工作流、每个具名 task 的固定命令模板、工作目录、参数白名单、环境变量、变更范围、审批和回滚语义；
- **Stage 4**：基于真实任务确认 utility 集合，避免建立无使用场景的工具集合；时间工具还需确认业务时区，结构化格式工具需确认输入输出是否通过值或 Workspace Link；
- **Stage 5**：先确认 Home Backlink 的扫描范围与索引策略；Memory 片段检索需再确认数据规模、来源定位协议、embedding/reranker 依赖和 action 命名；
- **Stage 6**：逐个 connector 确认授权、凭据、读写范围和人工审批；交互入口需保持 App-owned 输入/输出边界，不绕过 Runtime/Context/Action 生命周期。

### Home Backlink

Backlink 是待实现的 Home-owned Link 图能力，不放入通用 Infra，也不通过普通字符串搜索冒充已实现能力。建议边界：

- 输入为一个规范 Home top Link；
- 基于 `runtime override/tombstone -> actual fallback` 的 effective Home 查询引用来源；
- 返回有界 source Link、摘要与结果 digest，不返回整库正文；
- 扫描不应仅为查询而把未使用的 actual 文件复制到 runtime；
- 默认只解释 Home 图，不自动跨入 Memory 或 Workspace；
- 渐进资源是否参与扫描、是否建立持久索引，在实现前单独确认。

### Memory 检索增强

当前 `memory.search` 与 `memory.recall` 已是 Memory-owned native Action，并保持现有行为：

- 精确 `<memory:YYYY-MM-DD>` 已知时调用 `memory.recall`，返回完整但受上限约束的单日 Markdown；
- 精确日期未知时调用 `memory.search(query, top_k)`，流式扫描合法日期文档并以“单日文档”为候选，只返回 Link、日期与有界摘要；
- search/recall 的 ActionResult 都进入当前 TurnTrace，不修改 Background；Phase1 只自动加载精确昨日记忆；
- 当前 search 是候选日期发现，不是片段级语义检索。

后续增强应保留上述日粒度入口，并另行设计片段级语义检索：返回有界片段、所属日期 Link 和可验证来源位置，再由 Agent 判断是否 recall 完整单日文档。是否引入持久索引、embedding provider、增量更新和新的 action 名称，应在实现前结合数据规模与真实查询质量确认。

## 每项能力的实施门槛

- 真实用户场景、domain 归属、`use_when`/`avoid_when` 与 effects 已确认；
- 参数 schema 不以自由字符串绕过路径、命令或网络边界；
- 正常失败映射为局部 ActionResult，配置/环境/不变量失败保持模块边界异常；
- 文本、文件、网络响应、运行时长和并发均有明确上限；
- registrar、Catalog handler、executor 和业务 service 的所有权一致；
- 有模块测试、Phase2/Phase3 集成测试和至少一个 App 工作流验收。

## 待确认

当前只进入 Stage 1 决策，需先确认“Stage 1 待确认”的十项语义。Stage 2 至 Stage 6 的问题保留在“后续 Stage 的确认入口”、Home Backlink 和 Memory 检索增强章节，在进入对应 Stage 时再展开；后续能力不得借 Stage 1 的实现提前引入网络、任意命令、持久索引或新的长期状态。
