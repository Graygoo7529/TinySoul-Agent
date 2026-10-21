# Configuration

本页描述 Agent 配置的结构化查询、编辑和激活协议。前端读取后端投影、维护本地草稿并提交修改；配置 owner 校验候选并经 Infra 写回项目文件，Endpoint 只映射协议。新增文件须进入受管加载范围，保存与生效遵循下述 PATCH/apply/reload 语义。整体职责见 [统一配置链路](../design/infra.md#统一配置链路)。

## Read

- `GET /v2/config?view=saved|active`：默认 saved；active 来自最后成功发布的配置快照，saved 读取当前配置文件。两者都包含 activity、sources、effective fields、Runtime generation/activation、LLM Provider 凭据就绪状态和 process shell projection。pending_reload 比较保存值与活动值。
- `GET /v2/config/catalog`：Infra 维护的 surfaces、field groups、collections、field/document descriptors、choices 和 references。
- `GET /v2/config/actions?scenario=user`：当前 Runtime Generation 指定情景的 domain/action 定义、visibility、selection、granted/supported/available、runtime policy、tool schema、execution、model_uses、retrieval、source binding。scenario 支持 user、home_reflection、memory_reflection，默认 user；未知情景返回 422 config.invalid_scenario。

Action catalog 是配置页面的运行时投影，不是聊天 Action API；它由当前 Generation 的 ActionEngine 生成，Endpoint 不缓存。

`GET /v2/config/catalog` 的 collection 条目中，`create_source` 是可选字符串；未声明时省略该字段。Provider、任务链等保留固定创建来源；`llm.models` 不声明默认文件，由前端根据 family 与当前 saved + draft 来源选择目标。`allow_create` 独立表达是否允许创建，不能以缺少固定来源判断集合不可创建。新文件使用 `create_source` 操作，已加载空文件直接使用 `set`；同批向一个新文件添加多个模型只声明一次创建。PATCH 操作始终携带明确的 source_id。

selection 的 enabled/source 表示按“动作情景→域情景→动作 default→域 default→true”解析出的值与来源。unavailable_reason 为 not_granted、executor_unavailable、hidden 或 null。用户通过同一 PATCH 文档事务编辑 visibility.default 或 visibility.scenarios 对象；runtime.enabled 和 loop/reflection 的旧动作开关表不再接受。三个情景共用候选校验，显式启用未授权动作时拒绝保存，单纯域默认选择不增加授权。

`execution` 只含 executor 身份与 options，不再包含 backend kind/handler。`model_uses` 按 consumer 返回 operation、implementations、各实现的 options 约束、embedding_owner 和当前 binding；binding 含 consumer、implementation、target、options。`retrieval` 返回已登记的 source、operation、属性范围、Context 选项和分页/输入预算；tool.schema 由同一 retrieval policy 编译。模型侧 ActionCall 选择六个操作函数的组合、抽象语义和业务参数；操作内部的 implementation/provider/model 由用途配置透明绑定，Search 请求不携带这些内部实现选择。

`GET /v2/config/catalog` 描述 `action.models.bindings`、`action.retrieval` 和 `infra.model_services.providers/models/uses`。Action retrieval policy 只声明六个高层操作的来源、步骤、范围和预算；各操作内部的 implementation/provider/model 由对应 model-use binding 配置，Search 请求不携带这些选择。PATCH 以完整对象替换值；provider 的 api_key_env 是环境变量名称，对应凭据值脱敏。专用 model 的 provider_bindings 按数组顺序切换；Embedding 的 dimensions/batch_size 属于 model；use 通过 model_id 绑定一对一能力。Home 的 `home.search.embedding_use` 与 Memory 的 `memory.search.embedding_use` 引用同一模型目录中的逻辑用途，各自维护索引。

配置形态、consumer、实现/target/options 和来源支持的 source/operation 在候选编译时校验；已选模型依赖在有效动作装配和激活前校验。未选专用目录可以保留未就绪凭据。当前结构见 [模型使用与检索设计](../design/action-model-retrieval.md)，本轮契约与验收见 [检索执行计划](../analysis/done/20260927-done-检索统一内容流与来源契约执行计划.md)。

`runtime.llm.providers` 是当前 Runtime Generation 的只读、无 secret 投影。每项包含 Provider `id`、`credential_state`（`configured` 或 `missing`）以及声明的 `api_key_envs`；它不复制 `enabled`，后者继续由 effective fields 表达，也不返回任何凭据值。

`GET /v2/config/catalog` 也描述 `capabilities.expand.servers.*` 与 `capabilities.subagent.agents.*` 的集合、传输/命令、环境引用和有界运行限制。`env`/`headers` 保存可见的非敏感固定值；凭据使用 `env_refs`/`header_refs`，其 value 为环境变量名称，由 owner 装配时解析并覆盖同名固定值。引用名称可见，对应 dotenv/environment 的值在 sources/effective fields 中脱敏。候选 PATCH 只检查配置形态、本地依赖、可执行文件和引用是否就绪，不启动外部服务或枚举远端工具；首次 Action 才建立连接。

MCP `tools` 是完整对象值，`tools_default` 提供默认选择、单项覆盖。编辑含点或数字的远端工具名称时，PATCH 路径止于 `capabilities.expand.servers.<id>.tools`，把工具选择映射整体作为 value；这些名称不被展开为配置路径。所有 catalog 标记为 object 的字段均保留这种对象边界。

## 检索配置与结果

action.retrieval 的 catalog value_kind 为 object。home.search、core.context.search 等含点 Action ID 是 map 内原子键，不是层级路径。前端读取当前完整 map，修改其中的 Action，再以 source_id=project:configs/action/retrieval.toml、path=action.retrieval、op=set 提交整个 value；其它 Action 项也须保留。保存后仍按普通 reload 流程激活，不 PATCH action.retrieval.home.search.page 等子路径。

retrieval.where 与 tool.schema 来自 owner 的 typed 属性声明：日期允许 YYYY-MM-DD 的值或 before/after，集合属性允许包含条件。Memory query 显式提供 document_ref 变体；refs 可没有 steps，也可直接 filter/rerank。MCP query 表达 literal/regex，directory → select/rerank 表达没有词面预筛的语义发现。具体允许能力以当前情景 catalog 为准。

某个 Action 的 retrieval.operations 为空时，仍可调用已开放的 source；其 tool.schema 允许省略 steps 或传入空数组，非空步骤不合法。客户端应以实际 catalog 中的操作集合和 schema 为准。

SearchPage 是 Action/SDK 结果；页面 POST search 直接返回同一契约，见 [浏览与定位](inspection.md)。其契约如下：

| 内容 | 客户端解释 |
| --- | --- |
| result_handle、continuation | 前者指向完整最终集合，后者只定位成员页面；均绑定所属运行生命周期 |
| items[].content_coverage | 来源内容快照为 full、excerpt 或 metadata |
| items[].preview_coverage | 此页实际预览的覆盖，不能代替来源或模型输入事实 |
| items[].evaluation | 当前请求最后一次模型步骤的 op、step_index、input_coverage 及可用分数；无模型步骤可以省略 |
| items[].evidence | 真实片段的 ref、text、kind、location、basis、matches；空 basis 是普通内容预览 |
| evidence[].matches | 相对片段 text 的零起始 start、尾后 end，保留代表性命中种类和可选真实关系；不承诺列举全文全部出现位置 |
| coverage | 来源扫描与通道覆盖、本次步骤统计及最终成员数；分页不删候选 |

LLM 的 basis 为实际输入片段指认，Embedding 为真实向量贡献，decision model Score 不产生片段指认；不能把任何普通预览称作模型理由。result 派生保留来源内容及覆盖，清除旧模型评估后执行本次步骤，原视图仍保持旧评估。内部单元 ID 和模型短 ID 不暴露为持久资源身份。全文深读使用所属 owner 的 Inspect/read/describe。

## Mutation

`POST /v2/config/apply` 接受非空 `operations` 或 `preset_id`，必须且只能提供其中一种。候选统一校验并 prepare generation 后，原子保存文件并发布；发布前失败恢复此次事务触及的文件，保留调用前已经存在的 pending 配置。只有 idle 且没有排队根 work 时可激活。成功响应为 `state=active`、`generation_id`、`pending_reload=false`，并带 `changed_fields`、`changed_sources`、`matching_presets`。`reload` 沿同一发布流程激活已保存配置。

`GET/POST /v2/config/presets`、`GET/PUT/DELETE /v2/config/presets/{id}` 管理运行方案，方案记录存于 `configs/presets/`。

- 创建请求为 `name, description?, include_budgets=true`。从当前配置文件捕获，不接收来源选择或草稿操作；保存方案只写方案文件。
- PUT 默认只修改名称/说明；提供 `capture: {include_budgets: true|false}` 时从当前配置重新保存定义。DELETE 只删除方案文件。
- 列表返回 `presets` 数组，摘要包含 `id/name/description/included_scopes/matches_current/validation_issues/created_at/updated_at/schema_version`；详情另含 `definition` 和可用时的 `changes`。
- `matches_current` 只比较方案声明项与当前配置文件。有效方案的 `changes=[]` 表示声明项一致；其它配置不参与匹配。
- `changes` 每项为 `{path: string[], before: JsonValue, after: JsonValue}`。path 是分段路径，含点 consumer ID 保持为一个段；模型顺序用完整有序数组表达，binding 按 consumer 对齐。before 为 null 表示未设置，after 为 null 表示恢复默认；响应保留这些 null，默认值由业务 owner 解释，不展开为猜测值。
- 无法构造或校验候选时返回 `validation_issues`，省略 `changes`。客户端应显示不可比较并禁止确认应用，不能把缺失字段当成空差异。

方案声明每条任务 profile 的完整配置、每个已捕获 Action consumer 的完整 binding、Phase1/2 路由，以及检索策略的 query.channels；可选包含执行与语境预算。应用时把这些声明项写回当前配置：任务按 profile、binding 按 consumer 更新，检索和预算只覆盖声明字段。任务中未声明的可选参数恢复默认；后来新增的任务、binding、检索 consumer 及未声明字段保留。空任务/绑定声明不表示清空整个集合。

方案只通过稳定 ID 引用模型，不捕获 `llm.models`、Provider 连接及凭据、专用模型目录、知识库 embedding_use、能力授权、路径或内容。只读来源或缺失依赖使候选不能符合声明时拒绝应用。预览与应用共用配置候选构造、校验和声明比较；读取详情不写文件。应用请求仍是 `{preset_id}`，服务端重新读取当前文件并沿既有流程保存和加载；差异为空也可应用。不提供预览 token 或第二套运行态 diff，文件与运行态的差异由全局配置状态负责呈现。

设置页与聊天入口共用应用预览弹窗。有本地草稿时在同一弹窗中选择先处理、丢弃后应用或取消；预览与捕获均不包含草稿。应用成功后才清除明确同意放弃的草稿。未知方案为 404 config.preset_not_found，当前不可激活为 409 config.activation_unavailable，其余配置问题为 422 config.invalid。

LLM model 的 `family`（默认空）与 `collapsed`（默认 false）只提供显示元数据，不改变链顺序或模型可用性。模型管理、任务首模型及追加/替换共用带 family 胶囊、搜索和折叠开关的候选列表；明确点选才产生模型 ID 草稿。

`PATCH /v2/config` 接受 `operations` 数组。每项是：

```json
{"op":"create_source","source_id":"project:configs/llm/models/qwen.toml"}
```

或：

```json
{"op":"set","source_id":"project:configs/llm/models/gpt.toml","path":"llm.models.gpt-sol.providers","value":[{"provider":"openai","provider_model":"gpt-5.6-sol"}]}
```

或：

```json
{"op":"delete","source_id":"project:configs/llm/models/deepseek.toml","path":"llm.models.deepseek-pro.adapter_options"}
```

`create_source` 只声明一个尚不存在、位于项目 `configs/` 下且可由 include 图加载的 TOML 来源；同一批次随后用 `set` 写入模型。`set` 的 value 是不含 null 的递归 TOML/JSON value；`delete` 不携带 value。未知 op、缺失/多余字段和 `set(null)` 返回 `422 request.invalid`。PATCH 与 SDK 的 `patch_config()` 都只校验并保存候选，返回 `state=saved, pending_reload=true`，不替换当前 Generation。随后调用 `POST /v2/config/reload`（无请求体）或 SDK `reload_config()` 激活；成功返回 `state=active, pending_reload=false`。活动或等待中的 Turn、Reflection、daily transition 或既有 activation 使 reload 返回 `409 config.activation_unavailable`；候选保存仍可用。不要求 revision。

Provider 在 `llm.providers.<id>.endpoints.<api-mode>` 配置 base_url、headers/header_refs，共用 provider 的 api_key_envs 和可选请求头；Google GenerateContent endpoint 可选 `api_version`（默认由 SDK 使用 v1beta），该字段属于连接配置，不属于 model adapter option。Model 只选择一个 adapter，按该 adapter 的 api_mode 筛选兼容 Provider，并用有序 providers 数组保存 provider/provider_model。`GET /v2/config/catalog` 的 `rules.llm.api_modes/adapters` 返回四种模式、组合后的 common_options/variants、选项 source 和 runtime_available/reason；前端不另存供应商规则。四种 API mode 均可由 Registry 创建真实 SDK adapter；Anthropic/Google 的请求、工具、推理状态回放和缓存行为由 adapter 负责。Model 顶层 reasoning_effort 从 adapter_options.reasoning_efforts 声明中选择；request_overrides 和 task settings 支持 top_p。Endpoint table、Provider Chain 和选项沿原有草稿/diff/PATCH 提交，候选配置失败整批不持久化。

每个 option 的 `requires` 是「其它选项名 → 允许值数组」，`excludes` 是互斥选项名数组；后端使用同一规则校验，前端据此筛选可添加项并清理模式变更后失效的依赖项。`native_replay` 的候选按模式收窄为 none/content、none/encrypted 或 none/signed；Google explicit cache 的远端资源名不属于配置字段。候选档位编辑与顶层选定值分开，移除已选档位后必须重新选择或清空。

disabled Provider 可以在没有凭据时长期保存。把 Provider 改为 enabled 时，候选配置必须能从其 `api_key_envs` 中解析到至少一个非空值；否则 PATCH 返回 `422 config.invalid`，`details.key` 指向 `llm.providers.<id>.api_key_envs`，配置文件和当前 Generation 均保持不变。该校验只表示本地装配就绪，不探测远端服务。

`.env` 作为 `dotenv` source 读取和写入；dotenv mutation 值必须是字符串。进程环境和进程外壳配置可读但不可由该 endpoint 改写。
