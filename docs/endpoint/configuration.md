# Configuration

## Read

- `GET /v2/config`：activity、sources、effective fields、Runtime generation/activation、LLM Provider 凭据就绪状态和 process shell projection。
- `GET /v2/config/catalog`：Infra 维护的 surfaces、field groups、collections、field/document descriptors、choices 和 references。
- `GET /v2/config/actions?scenario=user`：当前 Runtime Generation 指定情景的 domain/action 定义、visibility、selection、granted/supported/available、runtime policy、tool schema、execution、model_uses、retrieval、source binding。scenario 支持 user、home_reflection、memory_reflection，默认 user；未知情景返回 422 config.invalid_scenario。

Action catalog 是配置页面的运行时投影，不是聊天 Action API；它由当前 Generation 的 ActionEngine 生成，Endpoint 不缓存。

selection 的 enabled/source 表示按“动作情景→域情景→动作 default→域 default→true”解析出的值与来源。unavailable_reason 为 not_granted、executor_unavailable、hidden 或 null。用户通过同一 PATCH 文档事务编辑 visibility.default 或 visibility.scenarios 对象；runtime.enabled 和 loop/reflection 的旧动作开关表不再接受。三个情景共用候选校验，显式启用未授权动作时拒绝保存，单纯域默认选择不增加授权。

`execution` 只含 executor 身份与 options，不再包含 backend kind/handler。`model_uses` 按 consumer 返回 operation、implementations、各实现的 options 约束、embedding_owner 和当前 binding；binding 含 consumer、implementation、target、options。`retrieval` 返回已登记的 source、operation、属性范围、Context 选项和分页/输入预算；tool.schema 由同一 retrieval policy 编译。模型侧 ActionCall 选择六个操作函数的组合、抽象语义和业务参数；操作内部的 implementation/provider/model 由用途配置透明绑定，Search 请求不携带这些内部实现选择。

`GET /v2/config/catalog` 描述 `action.models.bindings`、`action.retrieval` 和 `infra.model_services.providers/models/uses`。Action retrieval policy 只声明六个高层操作的来源、步骤、范围和预算；各操作内部的 implementation/provider/model 由对应 model-use binding 配置，Search 请求不携带这些选择。PATCH 以完整对象替换值；provider 的 api_key_env 是环境变量名称，对应凭据值脱敏。专用 model 的 provider_bindings 按数组顺序切换；Embedding 的 dimensions/batch_size 属于 model；use 通过 model_id 绑定一对一能力。Home 的 `home.search.embedding_use` 与 Memory 的 `memory.search.embedding_use` 引用同一模型目录中的逻辑用途，各自维护索引。

配置形态、consumer、实现/target/options 和来源支持的 mode 在候选编译时校验；已选模型依赖在有效动作装配和激活前校验。未选专用目录可以保留未就绪凭据。当前结构见 [模型使用与检索设计](../design/action-model-retrieval.md)，现有项目切换步骤见 [执行计划](../analysis/done/20260924-done-action-model-retrieval-unification-plan.md)。

`runtime.llm.providers` 是当前 Runtime Generation 的只读、无 secret 投影。每项包含 Provider `id`、`credential_state`（`configured` 或 `missing`）以及声明的 `api_key_envs`；它不复制 `enabled`，后者继续由 effective fields 表达，也不返回任何凭据值。

`GET /v2/config/catalog` 也描述 `capabilities.expand.servers.*` 与 `capabilities.subagent.agents.*` 的集合、传输/命令、环境引用和有界运行限制。`env`/`headers` 保存可见的非敏感固定值；凭据使用 `env_refs`/`header_refs`，其 value 为环境变量名称，由 owner 装配时解析并覆盖同名固定值。引用名称可见，对应 dotenv/environment 的值在 sources/effective fields 中脱敏。候选 PATCH 只检查配置形态、本地依赖、可执行文件和引用是否就绪，不启动外部服务或枚举远端工具；首次 Action 才建立连接。

MCP `tools` 是完整对象值，`tools_default` 提供默认选择、单项覆盖。编辑含点或数字的远端工具名称时，PATCH 路径止于 `capabilities.expand.servers.<id>.tools`，把工具选择映射整体作为 value；这些名称不被展开为配置路径。所有 catalog 标记为 object 的字段均保留这种对象边界。

## Mutation

`PATCH /v2/config` 接受 `operations` 数组。每项是：

```json
{"op":"set","source_id":"project:configs/llm/models.toml","path":"llm.models.primary.providers","value":[{"provider":"openai","provider_model":"gpt-5.5"},{"provider":"openai_proxy","provider_model":"gpt-5.5"}]}
```

或：

```json
{"op":"delete","source_id":"project:configs/llm/models/custom.toml","path":"llm.models.custom.adapter_options"}
```

`set` 的 value 是不含 null 的递归 TOML/JSON value；`delete` 不携带 value。未知 op、缺失/多余字段和 `set(null)` 返回 `422 request.invalid`。PATCH 与 SDK 的 `patch_config()` 都只校验并保存候选，返回 `state=saved, pending_reload=true`，不替换当前 Generation。随后调用 `POST /v2/config/reload`（无请求体）或 SDK `reload_config()` 激活；成功返回 `state=active, pending_reload=false`。活动或等待中的 Turn、Reflection、daily transition 或既有 activation 使 reload 返回 `409 config.activation_unavailable`；候选保存仍可用。不要求 revision。

Provider 使用 `llm.providers.<id>.adapters` 声明一个非空、无重复的 Adapter 列表；Model 使用 `llm.models.<id>.adapter` 选择统一 Adapter，并以 `llm.models.<id>.providers` 的有序对象列表配置 Provider Chain。`api_style` 是 Adapter 的静态属性，不是可写的 Provider 字段；通用兼容端点使用 `openai_compatible_chat`，Responses 由 `openai` Adapter 提供。Provider Chain、Adapter 列表和 Adapter options 均以完整值提交，候选配置校验失败时整批 mutation 不持久化。

disabled Provider 可以在没有凭据时长期保存。把 Provider 改为 enabled 时，候选配置必须能从其 `api_key_envs` 中解析到至少一个非空值；否则 PATCH 返回 `422 config.invalid`，`details.key` 指向 `llm.providers.<id>.api_key_envs`，配置文件和当前 Generation 均保持不变。该校验只表示本地装配就绪，不探测远端服务。

`.env` 作为 `dotenv` source 读取和写入；dotenv mutation 值必须是字符串。进程环境和进程外壳配置可读但不可由该 endpoint 改写。
