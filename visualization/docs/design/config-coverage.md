# 配置覆盖清单（W3 产物）

> 建立：2026-09-29。本文是前端设置页与 v2 catalog/config/actions 的对账清单。后端事实来源：`tinysoul/infra/config/`、`docs/endpoint/configuration.md`、资源模板和各 owner 的 config 类型。遇本文与后端 catalog/endpoint 不一致，以后端实际行为为准并更新本文。

## 1. 配置系统事实模型

### 1.1 来源与优先级

配置由四类 source 合并，**后列优先**（后者覆盖前者）：

1. **project TOML**：项目 `tinysoul.toml` 主文件 + `config.include` 声明的 include 文件；唯一的主体可写来源，按文件给出 source_id（如 `project:configs/llm/models/gpt.toml`）。模型 family 可通过 `create_source` 增加新的 `configs/llm/models/<family>.toml` 文件，并沿同一 include 图加载。
2. **dotenv**：项目 `.env` 文件；可写（path 为原始变量名，值必须是字符串）。被 `credential_reference` 字段引用的凭据值在读取投影中脱敏为字符串 `"<redacted>"`（fields 项另带 `redacted: true`）。
3. **environment**：进程环境变量，仅 `TINYSOUL_` 前缀的变量参与映射（可映射为 dotted 配置键）；只读。
4. **overrides**：CLI 启动覆盖；只读。

全部 `config.*` 路径（`config.include`、`config.env_file`、`config.document_sets`）与全部 `agent.*` 路径（见 §7.6）是进程独有：可读、不可经 endpoint 改写。Endpoint 自身的监听地址、token、journal 等不走配置文件，只在 config 读取投影中提供 `process_shell{host, port, instance_id, writable:false}` 只读项。

### 1.2 原子性与集合规则

PATCH 的 `path` 不表示任意深的 TOML 树路径：

- catalog 中 `value_kind = "object"` 的字段是**原子值**：`action.retrieval` 整张 map、MCP server 的 `tools`/`env`/`env_refs`/`headers`/`header_refs`、LLM `adapter_options.extra_body`、ACP agent 的 `env`/`env_refs` 都按整对象提交；含点的远端工具名/Action ID 是 map 原子键，不展开为子路径。
- `value_kind = "object_list"` / 数组字段整体提交：`action.models.bindings`、`infra.model_services.providers/models/uses` 三个数组、`llm.models.<id>.providers` 等。前端按稳定 id/consumer 识别条目，编辑后提交整个数组。
- collection（`llm.providers`、`llm.models`、`llm.tasks`、`capabilities.expand.servers`、`capabilities.subagent.agents`）按 key 逐对象展开；新增对象用 `create_template` 作为表单起点。catalog 的 `create_source` 可选：Provider、任务链等使用固定来源，LLM 模型按 family 从 saved + draft 来源中解析目标。删除受 `delete_policy` 约束。

### 1.3 编辑与激活流程

- `PATCH /v2/config`（或 SDK `patch_config()`）：候选校验 + 保存文件，返回 `state=saved, pending_reload=true`，**不替换当前 Generation**。
- `POST /v2/config/reload` / `POST /v2/config/apply`：激活已保存配置，重建运行世代。仅在 Agent idle 且无排队根 work 时可激活，否则 `409 config.activation_unavailable`；候选保存不受此限制。
- apply 接受 `operations`（与 PATCH 相同语义）或 `preset_id`，二选一；成功返回 `state=active, generation_id, pending_reload=false` 及 `changed_fields/changed_sources/matching_presets`，可附带 `cleanup_diagnostics`（旧资源清理提示，不改变应用成功语义）。
- `GET /v2/config?view=saved|active`：两者均含 `activity`（can_reload 及原因）、`sources`、effective `fields`（每项含 `value/source/writable/redacted?`）、Runtime generation/activation、`runtime.llm.providers` 凭据就绪投影（`credential_state: configured|missing`）、`process_shell`。
- `GET /v2/config/catalog`：surfaces、field groups、collections、field/document descriptors、choices、references，以及 `rules.llm.adapters`（各 adapter 支持的 adapter_options 规则）。
- `GET /v2/config/actions?scenario=user|home_reflection|memory_reflection`：当前 Generation 的 Action catalog 投影，含 visibility/selection 解析值与来源、granted/supported/available、runtime policy、tool.schema、execution、model_uses（含 binding）、retrieval，以及文档编辑的 `source/editable_paths`。

校验时机：候选 PATCH/apply 校验配置形态、跨引用（模型→Provider、链→模型、binding→consumer/target）、启用对象的就绪性（Provider 启用要求 `api_key_envs` 至少解析到一个非空值，否则 `422 config.invalid` 且 `details.key` 指向 `llm.providers.<id>.api_key_envs`；MCP/ACP 启用要求 command/url、本地依赖、引用可解析），**不探测远端服务、不触网**。运行时能力（granted/supported/available）由当前 active Generation 决定，未应用的草稿不改变它。

## 2. 模型与服务（计划 §16 / P11）

### 2.1 LLM Provider —— collection `llm.providers`

| 路径 | 类型/约束 | 默认（模板） | 可改性 | 影响 |
| --- | --- | --- | --- | --- |
| `llm.providers.<id>` 键 | 稳定 ID；禁点、禁首尾空白、禁纯数字 | openai/kimi/deepseek/glm/minimax/orca/… 均 `enabled=false` | 可增删改（`create_source: project:configs/llm/providers.toml`） | 模型 providers 链的可用端点 |
| `.enabled` | boolean | false | 可写；启用时凭据必须可解析，否则 422 | 该 Provider 是否参与装配 |
| `.endpoints.<api-mode>.base_url` | string；模式来自 `rules.llm.api_modes` | 按模板 | endpoint 表格编辑 | 各 API 模式的 SDK 根地址 |
| `.endpoints.google-generate-content.api_version` | 可选 string | SDK 默认值 | 可写 | Google 连接版本，不属于 model option |
| `.headers` / `.header_refs` 及 endpoint 下同名项 | 请求头 map；refs 的值为环境变量名 | 空 | 整体提交 | 共享请求头与入口覆盖 |
| `.api_key_envs` | string_list，`credential_reference` | 按模板 | 可写；编辑的是**环境变量名**，凭据值走 dotenv 草稿 | 凭据解析 |

LLM Provider 按 API mode 提供入口，共用凭据；不枚举专属 adapter。模型 adapter 的 API mode 来自后端 catalog，支持相同模式的 Provider 才进入候选。四类 API 的 SDK 均已接入。凭据就绪状态从 `runtime.llm.providers` 投影获得（configured/missing），配置启用不表示远端连通性已验证。

### 2.2 LLM 模型 —— collection `llm.models`

| 路径 | 类型/约束 | 可改性 | 影响 |
| --- | --- | --- | --- |
| `llm.models.<id>` 键 | 同上 ID 规则；新模型写入所选 family 的实际来源，新 family 创建 `configs/llm/models/<family-name>.toml` | 可增删改 | 任务链与用途引用的对象 |
| `.adapter` | 单选，来自 `rules.llm.adapters` | 可写 | 通用 API adapter 或专属 adapter；Provider 只需支持其 API mode |
| `.family` | string（默认空），仅显示元数据 | 可写 | 列表分组，不影响可用性 |
| `.collapsed` | boolean（默认 false），仅显示元数据 | 可写 | 列表默认折叠，不影响可用性 |
| `.providers` | 有序 `{provider, provider_model}` 列表，非空 | 整体提交；`provider_model` 是远端模型名，非 Provider ID | Provider Chain 顺序 |
| `.context_window_tokens` | integer | 可写 | Context 压缩比例的分母 |
| `.capabilities` | string_list：`text_input/image_input/image_remote_url/json_object_output/tool_calling/reasoning_output/prompt_cache` | 可写 | 任务链 `required_capabilities` 的满足判断 |
| `.adapter_options.variant` | enum：k2 / k3（advanced） | 按 adapter descriptor 显示 | Kimi 专属变体 |
| `.adapter_options.thinking` | enum，候选来自 API mode / adapter | 可写 | 思考模式 |
| `.adapter_options.choices.reasoning_effort` | string_list，逗号分隔输入 | 可写 | 模型声明的候选档位；Google 映射 thinking level |
| `.adapter_options.choices` / `.choice_rules` | 字符串候选与有限条件收窄 | 可写 | 模型候选、固定值及选项组合由后端 catalog 统一校验 |
| `.reasoning_effort` | 候选中的单一值，可清空 | 主面板选择 | 删除已选档位后提示重新选择或清空，不静默换档 |
| `.adapter_options.native_replay` | enum：none / content / encrypted / signed（advanced） | 可写 | 供应商原生回放模式 |
| `.adapter_options.reasoning_summary` | enum：auto / concise / detailed（advanced） | 可写 | 推理摘要 |
| `.adapter_options.verbosity` | enum：low / medium / high（advanced） | 可写 | 输出详略 |
| `.adapter_options.prompt_cache_mode` / `.prompt_cache_ttl` | API mode 对应的模式与 TTL | 按有效 catalog 显示 | OpenAI Chat `30m`、Responses `30m/12h`；Anthropic `5m/1h`；Google 秒数 TTL |
| `.adapter_options.prompt_cache_boundaries` / `.prompt_cache_ttls` | Context 名称列表 / 名称到 TTL 的映射 | 按有效 catalog 显示 | Background、Trace、Working 前缀；Google 只选一个显式资源前缀 |
| `.adapter_options.thinking_budget_tokens` / `.thinking_display` / `.include_thoughts` | number / enum / boolean | 按 requires/excludes 显示 | 思考预算或摘要展示；Google budget 与候选档位互斥 |
| `.adapter_options.reasoning_mode` / `.reasoning_context` / `.reasoning_split` / `.store` / `.do_sample` / `.user_id` | 各按 catalog 类型 | 按 API mode、adapter、variant 显示 | 模式或供应商特有行为 |
| `.request_overrides.temperature` / `.top_p` / `.max_output_tokens` | number / number / integer | 可写 | 覆盖任务级采样与输出预算 |

选项规则由后端组合 API mode → adapter → variant，并提供 `source`、`requires`、`excludes`。切换模式清理失效的依赖选项；父对象草稿内的子字段修改仍写回同一草稿，替换父对象同时撤销旧子字段操作。Google 远端缓存名由后端 generation 内资源管理器持有，不进入模型表单或 TOML。

切换 adapter 先确认，默认勾选“保留目标 adapter 支持的选项”。前端按目标有效 catalog 保留兼容的普通值、筛选候选，并保留整条仍适用的条件规则；不通过删除规则条件扩大适用范围。无效选值（含顶层 effort）清除，不自动换档。显式空候选仍表示不支持；原候选全部不适用时移除旧声明。固定选项使用目标 adapter 的定义；extra_body、断点 TTL 覆盖等对象选项需要重新配置。取消勾选则重置选项、候选、规则和 effort，仅建立目标必需的 variant。切换 variant 复用同一整理逻辑。兼容的 provider bindings 沿既有规则保留，所有改动仍作为草稿提交，后端承担最终校验。

Anthropic 模型能力读取是显式的只读请求，前端只呈现所选 provider binding 返回的建议；只有维护者采纳后才修改本地草稿，仍经原配置 PATCH 与 reload 链路保存和生效。查询结果属于发起请求时的模型、adapter、binding 和连接；这些对象切换或组件退出后，旧请求的成功、失败和结束回调均失效，不修改当前建议、错误或加载状态。

### 2.3 LLM 任务链 —— collection `llm.tasks`

| 路径 | 类型/约束 | 默认（模板 frame-stage1/2/llm-action） | 影响 |
| --- | --- | --- | --- |
| `llm.tasks.<id>.models` | 非空引用列表，指向 `llm.models` | 按模板 | 依次尝试的模型 |
| `.required_capabilities` | string_list，链内每个模型须满足 | `["text_input"]` | 候选过滤 |
| `.answer_format` | enum：none / text / json_object | json_object | 输出协议 |
| `.tool_use` | enum：disabled / optional / required | disabled | 工具调用策略 |
| `.temperature` / `.top_p` / `.max_output_tokens` | number / number / integer | 以项目当前 TOML 为准 | 采样与输出上限 |
| `.max_retries_per_provider` / `.retry_wait_seconds` / `.provider_switch_wait_seconds` / `.model_switch_wait_seconds` | 重试与切换等待五项 | 1 / 1.0 / 0.0 / 2.0 | 失败恢复节奏 |
| `.max_cycles` | integer | 10 | 单链内模型-Provider 轮次；**与 Turn 级 `loop.user.max_cycles` 是不同控件** |
| `.prefer_successful_provider_seconds` / `.prefer_successful_model_seconds` | number | 600 | 成功备份偏好窗口 |

Phase1/Phase2 的任务链绑定不在本 collection，见 §3.1。

### 2.4 专用 Provider/模型/用途 —— `infra.model_services`

catalog value_kind 为 object_list，三个数组**各自整体提交**；UI 按稳定 `id` 识别条目，数组下标不是身份。

| 路径 | 条目字段 | 约束 | 影响 |
| --- | --- | --- | --- |
| `infra.model_services.providers` | `id`、`adapter`、`base_url`、`api_key_env`、`enabled`、`timeout_seconds`、`max_retries`、`proxy` | adapter：openai_embedding / typesafe_system_one；max_retries 0..5；**单数** `api_key_env`（区别于 LLM 复数 `api_key_envs`）；有 `proxy` | Embedding/decision model 连接、代理与凭据 |
| `infra.model_services.models` | `id`、`kind`、`provider_bindings[{provider_id, model}]`、`dimensions`、`batch_size` | kind：embedding / decision；embedding 必填 dimensions>0、decision 禁止 dimensions；batch_size 1..256；provider_bindings 有序 | 专用模型与 Provider 路由 |
| `infra.model_services.uses` | `id`、`kind`、`model_id` | 一对一绑定一个模型；序列化字段是 `id` 不是 `use_id` | 上层引用的稳定逻辑用途 |

被 `home.search.embedding_use` / `memory.search.embedding_use`（§5.3/§5.4）和 Action 的 `embedding_similarity` binding target 引用。模板含 bigmodel（GLM embedding-3）与 typesafe 两个示例 Provider，均 `enabled=false`。

### 2.5 凭据

无独立配置树。凭据值一律存于 dotenv source（path=原始变量名，值必须字符串），被 `credential_reference` 字段引用：LLM `api_key_envs`、专用 Provider `api_key_env`、Web Kimi `api_key_env`、MCP `env_refs/header_refs`、ACP `env_refs`。读取投影脱敏为字符串 `"<redacted>"`（effective `fields` 项另带 `redacted: true`）；前端只用脱敏占位显示，未修改不生成 operation，输入新值才 set，删除须显式操作，不回写 `***`。

### 2.6 生图

后端**没有** image_generation 配置面。按计划保留“尚未接入”预留页，不提供任何保存/测试控件，不提交该类型配置。

## 3. 行为与调用（计划 §17 / P12）

### 3.1 Phase 调用分配

| 路径 | 类型 | 默认 | 影响 |
| --- | --- | --- | --- |
| `loop.cycle.phase1_task_profile` | reference → `llm.tasks` | frame-stage1 | Phase1（更新语境、选择行动域）所用任务链 |
| `loop.cycle.phase2_task_profile` | reference → `llm.tasks` | frame-stage2 | Phase2（域内生成 ActionCall）所用任务链 |

不存在 decision model Phase 切换；框架 Phase 与 Action 内部用途是两层配置。

### 3.2 Action 模型用途 —— `action.models.bindings`

catalog value_kind = object_list，**整数组提交**；source_id 为 `project:configs/action/routing.toml`。每条绑定：

- `consumer`：代码声明的固定集合，模板共 15 个：`core.reason.generate`、`core.answer.generate`、`workspace.compose.generate`、`workspace.describe.generate`、`workspace.analyze.generate`，以及五个 Search Action（home/memory/core.context/expand/workspace）各自的 `.search.select` 与 `.search.rerank`。
- `implementation`：llm_task / decision / embedding_similarity。各 consumer 允许的集合由代码声明：LLM 生成类仅 llm_task；select/rerank 支持 llm_task 与 decision；home/memory 的 rerank 额外支持 embedding_similarity。
- `target`：`{task_profile = <llm.tasks id>}` 或 `{use = <infra.model_services.uses id>}`。
- `options`：按实现类型，`max_output_tokens`（LLM）或 `relevance_threshold` 0..3（decision model select）。

每 consumer 的实际 implementations/options 约束/embedding_owner/当前 binding 从 `GET /v2/config/actions` 的 `model_uses` 读取；scenario 切换只改能力视图，同一 consumer 只有一份草稿。

### 3.3 Search 策略 —— `action.retrieval`

catalog value_kind = object，**整张 map 原子提交**；source_id 为 `project:configs/action/retrieval.toml`；含点 Action ID 是 map 原子键。已登记的五个 search action 及模板默认值：

| Action | sources（模板） | operations | allowed_context | 备注 |
| --- | --- | --- | --- | --- |
| `home.search` | query/backlinks/directory/refs/result | filter/select/rerank | none + current | scope all/agent/skills |
| `memory.search` | 同上 | 同上 | none + current | 类别 all/daily/entity/concept/fact/note + document_query |
| `core.context.search` | 同上 | 同上 | none + current | scope all/trace/session |
| `expand.search` | query/directory/refs/result（**无 backlinks**） | 同上 | 仅 none | server_scope + lexical_syntax；MCP 语义发现由 directory→select/rerank 表达 |
| `workspace.search` | 同 home | 同上 | none + current | resource_scope + lexical_syntax |

每个 policy 对象的可编辑字段：

| 字段 | 类型/约束 | 模板默认 |
| --- | --- | --- |
| `sources` | 五值子集 | 全量（expand 无 backlinks） |
| `operations` | filter/select/rerank 子集；为空仍允许纯 source | 全量 |
| `max_steps` | 1..32 | 8 |
| `query.channels` | lexical / embedding 子集；embedding 通道依赖 owner `embedding_use` | `["lexical"]` |
| `select.allowed_context` / `rerank.allowed_context` | none / current 子集 | 见上表 |
| `select.max_input_chars` / `rerank.max_input_chars` | integer | 65536 |
| `filter.*` | 属性契约由 owner typed 声明生成，无模型选择器 | — |
| `max_snapshot_chars` | integer | 4194304 |
| `page.max_items` / `page.max_chars` | integer | 50 / 8192 |

规则：可用 search action 必须有 policy；policy 不得超出代码声明能力。不 PATCH `action.retrieval.home.search.page` 等子路径。

### 3.4 Cycle 与 Reflection

| 路径 | 类型 | 默认（模板） | 归属页 |
| --- | --- | --- | --- |
| `loop.user.max_cycles` | integer | 20 | 行为与调用 → 预算 |
| `reflection.home.max_cycles` | integer | 20 | 行为与调用 → 预算 |
| `reflection.memory.max_cycles` | integer | 20 | 行为与调用 → 预算 |
| `context.max_image_bytes` | integer | 10485760 | 数据与知识 → Context |
| `context.compression_trigger_ratio` | number | 0.8 | 同上 |
| `context.compression_target_ratio` | number | 0.5 | 同上 |
| `context.trace_chunk_chars` | integer | 12288 | 同上 |
| `context.trace_branch_factor` | integer | 4 | 同上 |
| `context.trace_min_hot_entries` | integer | 2 | 同上 |
| `context.max_trace_inspect_chars` | integer | 8192 | 同上 |
| `session.max_background_chars` | integer | 24576 | 数据与知识 → Context |
| `reflection.timezone` | string | Asia/Shanghai | 行为与调用 → Reflection 调度 |
| `reflection.archive_root` | string | archive | 同上 |
| `reflection.schedule.enabled` | boolean | true | 同上 |
| `reflection.schedule.daily_time` | string（HH:MM） | 00:15 | 同上 |
| `context.system_text` | string | "You are TinySoul." | 数据与知识 → Context（稳定身份文本） |
| `context.journal` | string | ""（advanced） | 同上 |

## 4. 工具与连接（计划 §18 / P13 前半）

### 4.1 execution

| 路径 | 类型 | 默认 | 影响 |
| --- | --- | --- | --- |
| `execution.enabled` | boolean | false | execution 域动作注册 |
| `execution.interpreters.{python,bash,powershell,cmd}.enabled` | boolean | 仅 python=true | 各解释器可用性 |
| `execution.interpreters.<id>.executable` | string | 同名命令 | 实际可执行文件 |
| `execution.max_runtime_seconds` | integer | 1800 | 单次执行总时限 |
| `execution.max_output_bytes` | integer | 2097152 | 输出上限 |
| `execution.max_collect_chars` | integer | 4096 | Action 结果内联输出 |
| `execution.max_source_chars` | integer | 102400 | 脚本源码上限 |
| `execution.max_command_chars` | integer | 20480 | 命令行上限 |
| `execution.max_args` / `max_arg_chars` | integer | 64 / 4096 | 参数数量/长度 |

### 4.2 jobs

| 路径 | 类型 | 默认（common 模板） | 约束 |
| --- | --- | --- | --- |
| `jobs.retained_capacity` | integer | 16 | 保留结果容量 |
| `jobs.per_turn_live_capacity` | integer | 1 | live ≤ retained |

### 4.3 Web —— `capabilities.web`

| 路径 | 类型 | 默认 | 影响 |
| --- | --- | --- | --- |
| `max_source_bytes` / `max_output_chars` / `max_excerpt_chars` | integer（advanced 部分） | 5242880 / 1048576 / 600 | 共享下载/存储/摘录上限 |
| `request_timeout_seconds` / `max_redirects` / `user_agent` | number / integer / string | 30 / 5 / TinySoul-Agent/0.1 | 共享请求行为 |
| `search_by_kimi.enabled` / `.base_url` / `.api_key_env` / `.model` | boolean / string / credential_reference / enum | false / api.moonshot.cn / KIMI_SEARCH_API_KEY / kimi-k2.6 | Kimi 网页搜索 Action 注册；choices 为 kimi-k2.5、kimi-k2.6 |
| `search_by_kimi.max_query_chars` / `.max_result_chars` / `.max_inline_chars` / `.max_tool_rounds` / `.max_search_tokens` / `.max_output_tokens` | integer（advanced） | 4096 / 102400 / 12288 / 6 / 100000 / 8192 | 搜索边界 |
| `discover_pages.enabled` 及 `max_visit_depth` / `max_pages` / `max_candidates` / `max_links_per_page` / `max_result_chars` / `max_inline_chars` / `max_concurrency` / `max_tasks_per_minute` / `max_request_retries` / `max_crawl_seconds` / `allow_query_links` | 按 catalog | false / 1 / 20 / 100 / 200 / 102400 / 12288 / 2 / 30 / 1 / 90 / false | 页面发现 Action 注册与边界（concurrency ≤ pages 等由代码校验） |
| `fetch_with_defuddle.enabled` / `fetch_with_trafilatura.enabled` | boolean | false / true | 抓取实现注册 |

### 4.4 资源转换 —— `capabilities.resource`

| 路径 | 类型 | 默认 | 影响 |
| --- | --- | --- | --- |
| `max_source_bytes` / `max_output_chars` / `max_assets` / `max_total_asset_bytes` / `max_pdf_pages` | integer | 20971520 / 1048576 / 64 / 52428800 / 300 | 转换边界 |
| `render_pdf_pages` | enum | on_no_text | choices 为 disabled/on_no_text |
| `convert_with_markitdown.enabled` / `.formats` / `.extract_images` / `.extract_attachments` | boolean / string_list ⊂ {pdf,docx} 非空 / boolean / boolean | true / [pdf,docx] / true / true | MarkItDown 转换 Action |
| `convert_with_pypdf.enabled` / `.extract_images` / `.extract_attachments` | boolean | true / true / true | PyPDF 转换 Action |

### 4.5 MCP —— `capabilities.expand`

| 路径 | 类型 | 默认 | 影响 |
| --- | --- | --- | --- |
| `timeout_seconds` / `max_tools` / `max_catalog_bytes` / `max_result_bytes` / `max_inline_chars` / `max_search_chars` / `page_size` | number / integer | 45 / 2000 / 4M / 8M / 16384 / 61440 / 30 | 共享目录与调用边界 |
| `capabilities.expand.servers.<id>` | collection；create_source `project:configs/capabilities/expand.toml`；新条目 enabled=false | — | MCP 服务 |
| `servers.*.enabled` / `.description` | boolean / string | — | 注册与说明 |
| `servers.*.transport` | enum：stdio / streamable_http | stdio | 传输 |
| `servers.*.command` / `.args` / `.cwd` | string / string_list / string | — | stdio 启动；启用校验可执行文件，不触网 |
| `servers.*.url` | string | — | streamable_http 地址 |
| `servers.*.env` / `.headers` | object 原子值 | — | 可见固定值 |
| `servers.*.env_refs` / `.header_refs` | object 原子值，`credential_reference`；值为环境变量名，装配时解析并覆盖同名固定值 | — | 凭据引用 |
| `servers.*.tools_default` / `.tools` | boolean / object 原子 map（含点远端工具名为原子键） | true / {} | 工具选择 |

### 4.6 ACP —— `capabilities.subagent`

| 路径 | 类型 | 默认 | 影响 |
| --- | --- | --- | --- |
| `max_connections` / `connect_timeout_seconds` / `max_runtime_seconds` / `stop_timeout_seconds` / `max_output_chars` / `max_collect_chars` / `max_brief_chars` | integer / number | 4 / 30 / 3600 / 10 / 1048576 / 12288 / 24576 | 连接与委派边界 |
| `capabilities.subagent.agents.<id>` | collection；create_source `project:configs/capabilities/subagent.toml`；新条目 enabled=false | — | ACP 目标 |
| `agents.*.enabled` / `.description` / `.command` / `.args` / `.env` / `.env_refs` / `.auto_approve` | 按 catalog（env/env_refs 为 object 原子值，env_refs 是 credential_reference） | — | 目标定义；auto_approve 使用适配器自动批准，否则请求回到父 Agent |

## 5. 数据与知识（计划 §18 / P13 后半）

### 5.1 Workspace

| 路径 | 类型 | 默认 | 备注 |
| --- | --- | --- | --- |
| `workspace.root` | string（advanced） | runtime/workspace | 当日工作区根；日切归档语义不变 |
| `workspace.max_files` | integer | 100 | manifest 跟踪上限 |
| `workspace.max_read_chars` / `max_write_chars` / `max_image_bytes` | integer | 8192 / 32768 / 5242880 | 读写/图片边界 |
| `workspace.ignore_dirs` | string_list（advanced） | .git 等 8 项 | 调和忽略目录 |
| `workspace.watch.enabled` / `.debounce_ms` | boolean / integer（advanced） | true / 200 | 文件监听；正式操作不依赖监听 |
| `workspace.search.max_query_chars` / `.max_scan_chars` | integer | 256 / 1048576 | 词法搜索边界 |
| `workspace.analysis.max_intent_chars` / `.max_reference_links` / `.max_source_chars` / `.max_chars_per_reference` / `.max_answer_chars` | integer | 2048 / 8 / 24576 / 12288 / 4096 | analyze Action 边界 |

### 5.2 Session

| 路径 | 类型 | 默认 | 备注 |
| --- | --- | --- | --- |
| `session.root` | string（advanced） | runtime/session | 当日 Session 根 |
| `session.max_background_chars` | integer | 24576 | Context 背景投影预算 |
| `session.max_inspect_chars` | integer（advanced） | 8192 | inspect 单页上限 |

### 5.3 Home

| 路径 | 类型 | 默认 | 备注 |
| --- | --- | --- | --- |
| `home.root` / `home.runtime_root` | string（advanced） | home / runtime/home | actual Home 与跨日 overlay 根 |
| `home.max_read_chars` / `home.max_write_chars` | integer | 8192 / 32768 | 渐进读取/单次写入上限 |
| `home.max_skill_catalog_chars` | integer（advanced） | 8192 | Skill 目录投影 |
| `home.search.scan_limit` / `.max_resource_chars` / `.max_embedding_cache_chars` | integer | 1000 / 131072 / 16777216 | 搜索与可重建向量缓存 |
| `home.search.embedding_use` | string，引用 `infra.model_services.uses`（embedding kind），可空 | 模板未设置 | 主编辑入口在 Home 设置；专用用途页仅显示被谁使用并跳转 |

### 5.4 Memory

| 路径 | 类型 | 默认 | 备注 |
| --- | --- | --- | --- |
| `memory.root` | string（advanced） | memory | 持久文档与派生缓存根 |
| `memory.max_active_chars` | integer | 12288 | 活动 Memory.md 上限 |
| `memory.documents.max_{daily,entity,concept,fact,note}_chars` | integer | 32768/16384/16384/4096/24576 | 五类持久文档上限 |
| `memory.documents.redirect_max_hops` | integer（advanced） | 8 | redirect 链上限 |
| `memory.inspect.max_page_chars` | integer（advanced） | 8192 | inspect 单页上限 |
| `memory.search.max_embedding_cache_chars` | integer（advanced） | 16777216 | 可重建向量缓存 |
| `memory.search.embedding_use` | 同 Home | 模板未设置 | 主编辑入口在 Memory 设置 |

## 6. Action catalog 文档编辑面

文档集 `action.catalog` 由项目 `tinysoul.toml` 的 `config.document_sets` 声明，catalog 中以 `document_field` 描述；source_id 形如 `project-document:action.catalog:<相对路径>`。每个 domain/action 的可编辑与只读边界：

| 对象 | 可编辑字段 | 只读契约字段（contract 组） |
| --- | --- | --- |
| domain | `description`、`selection_hint`、`visibility.default`、`runtime.timeout_seconds` | `name`、`runtime.parallel_policy`、`runtime.hooks`、`runtime.result.trace_mode` |
| action | `tool.description`、`semantic.use_when`、`semantic.avoid_when`、`semantic.effects`（enum_list：read_only/additive/modifying）、`semantic.examples`、`visibility.default`、`runtime.timeout_seconds` | `name`、`domain`、`tool.schema`、`runtime.parallel_policy`、`runtime.hooks`、`runtime.result.trace_mode`、execution/executor、model_uses 声明 |

`visibility.scenarios` 对象经同一 PATCH 文档事务编辑；显式启用未授权（not granted）动作会被拒绝保存。`runtime.enabled` 和旧 loop/reflection 动作开关表不再接受写入。Actions 页从 `GET /v2/config/actions` 读 `source/editable_paths` 取得真实可写位置。

## 7. 系统与诊断（计划 §18 / P13 系统页）

### 7.1 只读进程项

| 路径 | 默认 | 只读原因 |
| --- | --- | --- |
| `agent.interactive` | true | 进程独有（CLI 交互模式） |
| `agent.exit_commands` / `agent.stop_turn_commands` | ["exit","quit"] / ["stop","cancel"] | 进程独有 |
| `agent.retained_outcomes` | 32 | 进程独有 |
| `agent.output.mode` / `agent.output.max_model_detail_chars` | normal / 20480 | 进程独有 |
| `config.include` / `config.env_file` / `config.document_sets` | 主文件声明 | 配置来源自身，进程独有 |
| environment / overrides 两个 source | — | 进程环境与 CLI 覆盖不可经 endpoint 改写 |
| `process_shell{host, port, instance_id}` | 当前监听 | Endpoint 监听不走配置文件；只读投影 |

### 7.2 可写系统项

`context.system_text`、`context.journal` 及 Context 容量字段在“数据与知识 → Context”页集中编辑；`reflection.timezone` / `archive_root` / `schedule.*` 归行为设置的 Reflection 调度。

## 8. 运行方案（presets）捕获范围

Endpoint：`GET/POST /v2/config/presets`、`GET/PUT/DELETE /v2/config/presets/{id}`；方案文件由后端存于 `configs/presets/`，前端不直接读写。捕获范围的精确键清单：

**必选**：

- `llm.tasks` 中捕获时的各 profile（每条完整配置，按 ID 更新）
- `action.models.bindings` 中捕获时的各 consumer（完整 implementation/target/options，按 consumer 更新）
- `loop.cycle.phase1_task_profile`、`loop.cycle.phase2_task_profile`
- 每个已登记 retrieval policy 的 `query.channels`

**可选 budgets**（`include_budgets`）：

- `loop.user.max_cycles`、`reflection.home.max_cycles`、`reflection.memory.max_cycles`、`session.max_background_chars`
- `context.max_image_bytes`、`context.compression_trigger_ratio`、`context.compression_target_ratio`、`context.trace_chunk_chars`、`context.trace_branch_factor`、`context.trace_min_hot_entries`、`context.max_trace_inspect_chars`
- 每个 retrieval policy 的 `max_steps`、`max_snapshot_chars`、`page.max_items`、`page.max_chars`，以及已开放 select/rerank 的 `max_input_chars`

**不包含**：LLM 模型目录（含 family/collapsed）、Provider 连接与凭据、`infra.model_services.*`、Home/Memory `embedding_use`、各类路径、`system_text`、Reflection 调度、visibility、retrieval 的 sources/operations/allowed_context、知识正文、本地外观。方案内的 `null` 表示恢复 owner 默认，不是 `set(null)`（PATCH 协议禁止 null 值）。

创建表单只有名称、说明和包含预算；重新保存只选择是否包含预算。捕获统一读取当前配置文件，不提供 active/saved/draft 来源选择。未应用草稿不进入方案，也不因捕获而丢失。

方案详情分“方案内容 / 应用变化”两页：内容直接呈现有序模型链、参数、路由与全部声明预算；变化由后端按声明范围返回当前值→方案值。`matches_current` 表达当前配置是否满足声明，不推断唯一运行中方案。设置和聊天共用 `PresetApplyDialog`，每次应用先重新读取差异，只提交 `{preset_id}`；空差异仍可应用。存在草稿时在同一弹窗明确处理，失败保留，成功后清理。后来新增的任务/consumer 不参与旧方案差异，应用仍保留它们。待激活状态由全局配置状态页管理。

模型管理页与任务首模型、追加、替换共用 `ModelSelectionList`；任务行通过 `ModelPicker` 弹出候选。family 胶囊、搜索和折叠开关只过滤列表，任务行保持实际模型 ID。默认隐藏 collapsed 候选，搜索可找到并显示折叠标记；未分组也是可筛选项。首模型须明确选择；追加去重、单行替换保持其它位置及顺序。编辑均进入既有共享草稿，新 family 文件、模型和任务引用可同批提交，不额外建立模型选择提交流程。

## 9. 与计划及现有前端文档的不一致点

1. **catalog choices 已对齐**：`capabilities.resource.render_pdf_pages` 现在声明并接受 `disabled/on_no_text`；前端应直接消费 catalog choices。
2. `visualization/docs/design/settings.md` 与当前 Settings 实现使用 `/v2/config*`；字段标签和交互以 catalog/ConfigDraft 为准。
3. 工具与连接分组覆盖 Web、资源、Execution/Job、ACP 与 MCP；字段可写性仍由实际 source 和 catalog 决定。
4. **`agent.*` 在 catalog runtime.toml 中有字段声明但全部进程独有只读**；系统页只读项须以 config 读取投影的 `writable:false` 为准，不凭 catalog 存在性做成可写控件。
5. **Kimi 搜索 model 已声明 choices**：后端 catalog 提供 kimi-k2.5/kimi-k2.6；表单应消费 choices，不开放自由文本。
6. **LLM Provider 无 `proxy` 字段，专用 Provider（`infra.model_services.providers`）有**；两个表单可复用控件，但 LLM 使用 `endpoints`/`api_key_envs`，专用服务使用 `adapter`/`api_key_env`，不强行合并协议。
7. **计划 §19 的简写键名**（`compression_trigger/target_ratio`、`trace_chunk_chars/branch_factor/min_hot_entries/max_inspect_chars`）对应真实完整键 `context.compression_trigger_ratio` 等（见 §8），语义一致，仅书写省略。
8. **模板中 expand.search 无 backlinks source**（其余四个 search action 有）；MCP 配置面不显示反链入口，与计划 §17.3 “MCP 不自动获得 Embedding”一致。

以上均不改变计划语义；实施时以本清单与 catalog 为准。

## 10. 对话/对话记录/对话详情的配置面结论

主对话（P01）、提问/追加/回复卡片（P02）、历史对话与 Session（P03）**不需要任何配置原语**：

- 对话页的交互行为（新轮/追加/回复/补额/取消）由 API-02 与 TurnSnapshot 状态驱动，无配置项；`agent.interactive`、`exit_commands`、`stop_turn_commands` 等终端行为键是进程独有只读，不进入设置表单。
- 问题卡片协议（选项数上限 8、choice/text answer）由后端固定协议决定，不可配置。
- 历史/Session 页只有读取分页；`session.max_background_chars` 在“数据与知识 → Context”编辑，`session.max_inspect_chars` 仍归“数据与知识 → Session”（§5.2），对话页自身不暴露。
- 对话页唯一与配置相关的入口是运行方案快捷选择器（§19 / API-06/07），方案内容本身在设置中管理。

即：P01–P03 的实现不依赖任何新增设置控件，只需消费运行方案列表/应用与 Turn 状态。

## 11. 编辑归属汇总（落实计划 §15.2）

| 配置对象 | 主要编辑入口 | 其它页面行为 |
| --- | --- | --- |
| `llm.providers` / `llm.models` / `llm.tasks` / `infra.model_services.*` | 模型与服务各对象页（§2） | 被引用位置给摘要与跳转 |
| `loop.cycle.phase1/2_task_profile` | 行为与调用 → Phase 调用分配（§3.1） | 任务链页显示引用位置 |
| `action.models.bindings` 条目 | 行为与调用 → Actions 对应 consumer 分区（§3.2） | 按 consumer 撤回本页修改；不复制条目 |
| `action.retrieval` 条目 | 行为与调用 → Search 配置（§3.3） | 其它页跳转；整 map 原子提交 |
| `home/memory.search.embedding_use` | 数据与知识 → Home / Memory（§5.3/§5.4） | 专用用途页显示绑定并跳转 |
| MCP servers / ACP agents | 工具与连接 → MCP / ACP（§4.5/§4.6） | 运行观察只读实际连接/目录 |
| 凭据值 | 模型与服务 → 凭据（§2.5），统一 dotenv 草稿 | Provider/工具页引用同一编辑流程 |
| Cycle 与 Reflection 键 | 行为与调用 → Budgets/Reflection（§3.4） | 概览/方案显示摘要 |
| Context 组合与容量键 | 数据与知识 → Context | Session/Home 页面显示只读归属与跳转 |
| Workspace/Session/Home/Memory owner 键 | 数据与知识各页（§5） | — |
| Action catalog 文档字段 | 行为与调用 → Actions 协议详情（§6） | 契约字段只读展示 |
| 进程独有只读项 | 系统与诊断（§7） | 显示只读归属 |
