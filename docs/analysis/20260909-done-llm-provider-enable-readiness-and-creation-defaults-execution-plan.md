# LLM Provider 启用前置条件与创建默认值执行计划

状态：`done`

日期：2026-09-09

## 背景与现状结论

当前 LLM 配置把三件不同的事情耦合在了加载阶段：配置拓扑是否正确、Provider 是否被用户启用、Provider 当前是否能从运行环境解析到凭据。`TaskConfigParser` 会按 enabled Provider 过滤 Task 的 Model Chain，过滤为空即报错；`build_provider_registry` 又会在装配 enabled Provider 时强制解析 API key。结果是标准配置在没有启用 Provider 时不能形成完整 Runtime Generation，development 配置则会因为默认启用了多个无凭据 Provider 而在启动阶段失败。前端必须先连接后端才能进入 Credentials/Providers 设置页，因此形成了配置引导闭环上的阻塞。

配置激活期间的相同问题发生在 LLM Generation 装配阶段。`TinySoulAppBuilder._build_llm` 会重新解析已经进入 `AppConfigPlan` 的 LLM 配置，并把缺失凭据的 `ConfigError` 直接转换为 Runtime 异常；Endpoint 因此只能返回通用 `500 config.activation_failed`，而不是带配置字段信息的 `422 config.invalid`。

Visualization 还有三项确定的创建默认值问题：New Model 对话框默认选择列表首个既有 Model 而不是 Blank；新 Model、切换 Adapter 和添加 Provider 都可能写入固定的 `provider_model = "model"`；新 Provider 原样复制静态 catalog 模板，因此初始凭据名始终是 `PROVIDER_API_KEY`。

## 已确认设计语义

### Provider 配置、凭据与启用

- `api_key_envs` 是 Provider 持久配置的一部分，可以在对应环境变量均不存在或为空时长期保存。
- disabled Provider 不要求存在凭据。它仍可被 Model Binding 引用，也可以保留在 Task Model Chain 的可达拓扑中。
- `enabled = true` 表示当前配置快照已经满足本地调用前置条件：至少一个 `api_key_envs` 名称能在 Generation 的 `runtime_env` 中解析到去除外围空白后非空的值，并且对应 Adapter 可以完成本地装配。
- 启用不是远程健康检查。它不保证 key 被远端接受、网络可达或 `provider_model` 确实存在；这些仍在真实调用时按现有 ProviderError、Provider Chain 和 Model Chain 流程处理。
- 前端在已知凭据缺失时提示并拒绝提交 enable；后端候选配置校验仍是权威边界，必须拒绝任何客户端提交的无凭据 enable。
- 拒绝 enable 时不写入配置、不创建新 Generation，现有 Runtime 保持活动；响应为 `422 config.invalid`，不是 Runtime `500`。

### 无凭据启动边界

- Task 配置描述的是静态 Model 顺序和恢复策略，不要求进程启动时已经存在 enabled Provider。零 enabled Provider 是合法、可配置但暂时不能执行 LLM Task 的状态。
- package-owned standard 配置中的 Provider 默认 disabled，因此 standard 项目在没有任何凭据时可以启动后端、连接前端并进入设置页。用户可以先在 Credentials 写入 key，再启用 Provider。
- development 配置继续默认启用项目维护者使用的 Provider 与 `search_by_kimi`，便于凭据已经准备好的开发环境直接使用。它明确要求启动前提供对应开发凭据，不承诺空 `.env` 启动。
- 如果现有项目被手工写成 `enabled = true` 且所有声明 key 均缺失，这仍是显式无效配置，初次启动继续按 LLM 配置失败处理。本计划不引入绕过完整 Runtime Generation 的“配置恢复模式”，也不在内存中静默把 enabled 改成 disabled。

### Task Chain 与运行时路由

- `LLMConfigParser` 保留 Task 中配置的完整 Model Chain，只校验 Model 引用、能力和静态 Provider/Adapter Binding 拓扑，不按 enabled 状态重写配置事实。
- `LLMTaskRunner` 在一次 Task 开始前，从当前不可变 ProviderRegistry 投影出可路由 Model Chain：只有至少一个 Binding 已在 Registry 注册对应 Adapter 的 Model 才进入尝试序列。
- 不可路由 Model 没有发生真实模型尝试，不发布伪造的 provider/model failed Observation，也不消耗 provider/model switch wait。
- 有效链继续完整复用现有顺序：同 Provider 有界重试、切换 Provider、切换 Model、暂时性错误进入后续 Model Chain cycle，以及成功 Provider/Model 的限时偏好。
- 有效链为空时直接形成现有 `ModelChainExhaustedError`，经 `RuntimeLLMBridge` 使用既有 `llm.model_chain_exhausted` 失败类型结束当前 Turn；不新增 Runtime reason，也不让服务进程退出。
- `current_model_capabilities` 与实际 Task 使用同一可路由链投影，避免能力预览指向 disabled Provider 支撑的 Model。

### Provider 凭据就绪投影

LLM 模块拥有凭据引用的解释和就绪状态，Infra 仍只提供合并后的 `runtime_env`，Endpoint 只做只读协议映射。引入 LLM-owned frozen 状态对象和 `StrEnum`：

- `ProviderCredentialState.CONFIGURED = "configured"`
- `ProviderCredentialState.MISSING = "missing"`
- `ProviderCredentialStatus` 保存 `provider_id`、状态和声明的环境变量名，不保存或暴露 key 值。

该状态由 `ProviderSpec` 与当前 Generation 的 `runtime_env` 确定，并随 Generation 一起替换。它既能正确识别项目 `.env`，也能识别进程环境提供的 key；前端不得只检查可写 dotenv source 来猜测 Provider 是否可启用。

`GET /v1/config` 的运行时投影扩展为：

```json
{
  "runtime": {
    "generation_id": "generation-id",
    "activity": "idle",
    "activation": "stable",
    "llm": {
      "providers": [
        {
          "id": "orcarouter",
          "credential_state": "missing",
          "api_key_envs": ["ORCAROUTER_API_KEY"]
        }
      ]
    }
  }
}
```

`enabled` 继续来自唯一的配置字段事实，不在运行时投影复制。前端组合配置字段与 credential state 展示以下状态：

| 配置状态 | 凭据状态 | 展示与行为 |
| --- | --- | --- |
| disabled | missing | `Credential required`，Enable 被前端拒绝并引导到 Credentials |
| disabled | configured | `Ready to enable`，允许 Enable |
| enabled | configured | `Enabled`，Provider Adapter 已进入当前 Registry |
| enabled | missing | 不允许形成候选 Generation，后端返回 `422 config.invalid` |

## 配置激活与失败归属

### 候选校验

`AppConfigPlan` 继续作为一次 Generation 的唯一跨模块已验证配置快照。LLM section 只解析一次；`_build_generation` 将 `plan.llm` 传给 LLM 装配，不再由 `_build_llm` 重复解析同一动态输入。

在真实配置驱动的 LLM Runner 下，App 的计划编译边界调用 LLM-owned enabled Provider credential validation：

```text
候选 source 合并
  -> LLM 静态配置解析
  -> enabled Provider 凭据前置条件校验
  -> 跨模块配置引用校验
  -> Generation 业务对象装配
```

测试或嵌入方通过 `with_llm_runner` 显式注入 Runner 时，继续跳过真实 Provider 凭据要求；该入口已经替代配置驱动的 LLM 调用，不应反向要求测试凭据。

无凭据 enable 使用 `ConfigError`：

- message 明确指出 Provider 和需要配置的变量名；
- key 为 `llm.providers.<id>.api_key_envs`；
- 不携带 key 值、traceback 或原始异常；
- Endpoint 复用现有 `_config_error` 映射为 `422 config.invalid`。

初始进程装配中同一错误仍由现有 App/Runtime bridge 映射为 LLM configuration failure 和 startup failure。真实 Adapter 装配不变量、依赖失败或其它非配置运行错误仍可成为 `500 config.activation_failed`；不能为了改善无 key 提示而吞掉这类边界异常。

### 三层失败语义

- 缺失 Provider key 且尝试 enable：配置动态边界失败，使用 `ConfigError`，不是局部 TaskResult，也不是 ProviderError。
- 运行中没有任何可路由 Model：LLM 模块边界的 Model Chain exhaustion，经既有 Runtime bridge 改变当前 Turn 控制流。
- 远程鉴权、限流、网络、响应解析和模型级错误：继续由 ProviderError 分类，进入 Provider/Model fallback；本计划不改变其重试策略。

## Visualization 交互设计

### Provider 页面

- Provider 摘要和详情读取 `runtime.llm.providers` 的凭据状态，区分 `Credential required`、`Ready to enable` 与 `Enabled`。
- 用户把 `.enabled` 从 false 改为 true 时，页面先检查权威状态投影。若为 missing，不提交 PATCH，显示：`Configure one of ORCAROUTER_API_KEY in Credentials before enabling this provider.`
- 提示通过现有 toast action 导航到 Credentials；Provider 页面由 SettingsPage 接收一个窄的 `onOpenCredentials` 回调，不让页面直接拥有全局导航状态。
- 状态可能在前端读取后发生变化，因此后端仍执行相同校验。外部客户端或竞态触发的 `422` 使用后端安全 message 显示。
- Credentials 将纯空白值视为未配置，与后端去除外围空白后的非空规则保持一致。

### New Model 默认 Blank

- 每次打开 New Model 对话框都把 template 重置为 `""`，下拉框默认显示 `Blank model`。
- Blank 表示不复制既有 Model，不表示生成违反 LLM parser 不变量的空对象。创建仍从 catalog 的基础结构取得 context window、capabilities 等必需字段，并选择首个已声明 Provider 及其 Adapter。
- Blank Model 的首个 `provider_model` 默认使用用户刚输入的 TinySoul Model ID，创建前仍可在后续编辑器中修改。
- 用户主动选择已有 Model 模板时，完整复制模板的 Model 配置和 Provider Chain；本计划不删除显式 clone 能力。

### Model Provider 默认远端名称

默认值仅用于减少录入，不改变 `provider_model` 是 endpoint 不透明标识、后端无法静态确认其存在的设计：

| 场景 | 默认 `provider_model` |
| --- | --- |
| Blank Model 首个 Binding | 新 Model 的 TinySoul ID |
| 为现有 Model 添加同 Adapter 的备用 Provider | 当前 Provider Chain 首项的 `provider_model` |
| 切换 Adapter，目标 Provider 曾有 Binding | 该 Provider 原有的 `provider_model` |
| 切换 Adapter，没有可复用 Binding | 当前 TinySoul Model ID |
| 从已有 Model 模板创建 | 保留模板的完整 Binding 值 |

添加备用 Provider 时复用链首远端名称符合“同一个 Model 在不同代理端点通常沿用同一远端 ID”的主要场景；用户仍可立即编辑。切换 Adapter 时不复用另一个 Adapter 下的远端名称，避免把例如 DeepSeek 模型名默认发送给 GLM Adapter。

### New Provider 默认凭据名

新 Provider 仍显式写入完整配置，不给 Infra catalog 增加字符串模板语言。Visualization 在复制 create template 后覆盖 `api_key_envs` 首值：

```text
orcarouter  -> ORCAROUTER_API_KEY
my-proxy    -> MY_PROXY_API_KEY
123proxy    -> PROVIDER_123PROXY_API_KEY
```

规则为：Provider ID 转大写，把连续非 ASCII 字母数字归一化为单个下划线并去除首尾下划线；结果以数字开头时加 `PROVIDER_`；无法得到 ASCII stem 时使用 `CUSTOM_PROVIDER`；最后追加 `_API_KEY`。它只生成合法、可编辑的建议值，不扩大现有 Provider ID 语法，也不尝试推断厂商专用名称。

## 模块与文件改动预览

### LLM 与 App

- `tinysoul/llm/config.py`、`config_sections.py`：移除 `require_enabled_providers` / `enabled_provider_ids` 和加载期链过滤，保留完整配置链。
- `tinysoul/llm/config_types.py`：统一非空 key 解析、enabled Provider 凭据校验和 JSON 安全凭据状态领域对象；不保存 secret。
- `tinysoul/llm/provider/factory.py`、`registry.py`：复用既有“只装配 enabled Provider”和 `(provider, adapter)` 唯一注册语义，无需增加平行校验或状态。
- `tinysoul/llm/task.py`：在 Task 和能力预览入口使用同一可路由 Model Chain 投影；空有效链复用既有 exhaustion bridge。
- `tinysoul/app/builder.py`：计划编译时校验 enabled Provider 凭据，以 `plan.llm` 装配 Runner，去掉 LLM section 二次解析。
- `tinysoul/app/generation.py`：保存当前 Generation 的 LLM Provider credential status 只读投影，供 Endpoint 读取。

### Endpoint

- `tinysoul/endpoint/engine/contracts.py`：在 Generation 只读协议中声明 LLM credential status snapshot。
- `tinysoul/endpoint/engine/configuration.py`：把 snapshot 映射到 `GET /v1/config.runtime.llm.providers`；Endpoint 不解析 env、不拥有状态。
- `docs/endpoint/configuration.md`：同步新增响应字段、enable 无 key 的 `422` 和不持久化语义。

### Package profiles 与说明

- standard profile 保持 Provider 默认 disabled；development profile 保持 Provider 与 `search_by_kimi` 默认 enabled，不为无凭据启动改写其开发语义。
- `README.md` 与 `tinysoul/assets/project/README.md`：说明 standard 可无凭据启动设置界面；development 必须先提供其默认启用能力所需的凭据。
- `docs/design/llm.md`：把加载期 enabled 过滤改为静态链与运行时可路由链分层，并记录 enabled 的凭据不变量。

### Visualization

- `visualization/src/types/configuration.ts`：增加 Provider credential status 响应类型。
- `visualization/src/features/settings/model.ts`：增加凭据状态查询、默认 provider model 和默认 Provider env 名称的纯派生 helper。
- `ProvidersSettingsPage.tsx`、`SettingsPage.tsx`：增加状态展示、enable 前置提示和 Credentials 导航。
- `ModelsSettingsPage.tsx`：New Model 默认 Blank，替换三处固定 `"model"` 占位值，并向 ProviderChainEditor 传入 Model identity。

不新增 ProviderAdapterBinding，不改变 Adapter/API style、ModelProviderBinding、Provider Chain 或 RetryPolicy 的既有语义；不增加配置兼容别名、前端重复业务状态或通用模板引擎。

## 测试计划

测试只覆盖稳定契约和关键交互，不为所有 Provider、字符组合或相同分支增加重复防御性用例。

### Backend 聚焦测试

- LLM config：零 enabled Provider 时完整 Task Model Chain 仍被保留；未知引用、Adapter 不匹配等静态错误继续失败。
- Provider credential：disabled + missing 合法；enabled + missing 产生带准确 key 的 `ConfigError`；多个 env 中任一去除空白后非空即可通过。
- Task runner：不可路由 Model 不发生调用和等待；后续可路由 Model 仍按原顺序执行；全部不可路由映射为现有 model-chain-exhausted Runtime 失败。
- App builder：空凭据的 standard package profile 可以形成 Generation；显式 enabled + missing 在初始构建和候选校验边界分别保持既有 Runtime/ConfigError 映射。
- Endpoint：状态不泄露 key 值；无凭据 enable 返回 `422 config.invalid` 且配置文件和 generation id 不变。
- Initializer：standard 保持 credential-bound Provider disabled；development 保持维护者 Provider 与 Kimi Search enabled。

### Visualization 聚焦测试

- Provider missing 时 enable 不发送 PATCH，提示包含 env 名称并可进入 Credentials；configured 时正常提交。
- New Model 对话框每次打开默认 Blank，Blank 首项使用新 Model ID。
- 添加备用 Provider 复用链首 `provider_model`；Adapter 切换不错误复用其它 Adapter 的远端名称。
- New Provider 的一个代表性普通 ID 和一个数字开头 ID 生成合法 env 名称。

### 门禁

实施期间先运行对应 backend pytest 路径和 Visualization 定向测试，再运行：

```powershell
.\scripts\test.ps1
cd visualization
pnpm.cmd test
pnpm.cmd build
cd ..
.\scripts\test.ps1 -Suite Full
.\scripts\typecheck.ps1
```

若项目脚本执行策略受限，按 `AGENTS.md` 使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File` 调用，不把执行策略失败误判为测试失败。

## 实施步骤

### 一：LLM 配置与凭据不变量

- [x] 移除 Task parser 的 enabled Provider 过滤和相关公共参数。
- [x] 建立 Provider 凭据解析、状态投影和 enabled 校验的单一语义实现。
- [x] 让 AppConfigPlan 候选校验在真实 LLM 装配时执行 enabled 凭据校验。
- [x] 让 LLM Builder 消费 `plan.llm`，删除重复配置解析路径。

### 二：可路由 Model Chain

- [x] 为 TaskRunner 建立不修改配置事实的有效链投影。
- [x] 对齐 `run` 与 `current_model_capabilities` 的可路由模型选择。
- [x] 保证空链复用现有 Runtime failure，且不可用 Model 不产生虚假尝试或等待。

### 三：Runtime 状态与 Endpoint

- [x] 将 LLM-owned credential status 固定在 AppRuntimeGeneration 快照中。
- [x] 扩展 Endpoint Generation protocol 和 `GET /v1/config` 投影。
- [x] 验证状态只包含 Provider ID、env 名称与稳定状态，不包含 secret。
- [x] 同步 Endpoint 文档。

### 四：初始化配置与说明

- [x] 保持 standard/development 已确认的默认 enabled 状态，不用模板变化规避凭据不变量。
- [x] 更新 initializer 契约和项目 README，验证 standard 空凭据启动以及 development 缺失必需凭据时严格失败。

### 五：Visualization Provider 体验

- [x] 增加 credential status 类型与纯派生 helper。
- [x] 增加 Provider 状态摘要和详情提示。
- [x] 无 key 时拒绝 enable，并提供前往 Credentials 的操作；保留后端权威校验错误展示。
- [x] 统一 Credentials 对空白值的判断语义。

### 六：Visualization 创建默认值

- [x] New Model 每次打开默认 Blank。
- [x] Blank Model 使用 Model ID 作为首个远端名称。
- [x] 添加备用 Provider 复用链首远端名称，Adapter 切换使用目标 Provider 原值或 Model ID。
- [x] New Provider 使用 ID 派生合法 env 名称。

### 七：文档、验证与核对

- [x] 更新 LLM 设计、Endpoint 协议和根 README。
- [x] 运行聚焦测试、Fast、Visualization tests/build、Full 和 typecheck；Visualization 未配置独立 lint script，TypeScript 检查由 build 执行。
- [x] 核对配置写入、Generation 原子激活、Runtime bridge 与 UI 状态没有重复事实或兼容分支。
- [x] 记录实际实施位置和验证结果；计划状态和文件名均标记为 `done`。

## 实施核对

- LLM 配置由 `LLMConfigParser` 一次解析为 `AppConfigPlan.llm`；enabled 凭据不变量在 App 候选计划边界调用 LLM-owned 校验，初始启动映射为既有 LLM configuration startup failure，Endpoint mutation 映射为 `422 config.invalid`。
- Provider 凭据状态由 `ProviderSpec` 投影并固定在 `AppRuntimeGeneration`，Endpoint 只序列化 Provider ID、状态和 env 名称。`enabled` 未被复制为第二份状态，secret 也未进入投影。
- Task 配置不再按 enabled Provider 改写 Model Chain；`LLMTaskRunner` 对调用和能力查询使用同一可路由链。空有效链复用 `llm.model_chain_exhausted`，Provider/Model 重试、切换、cycle 和偏好状态实现未分叉。
- standard 模板仍保持所有 LLM Provider disabled；development 模板仍保持维护者 Provider 与 Kimi Search enabled。现有 initializer generation 契约和新增 App 启动测试共同覆盖该边界。
- Provider 设置页只做基于当前 Generation 状态的提前引导，后端仍为权威校验；拒绝路径不调用 PATCH。写入凭据后的 configured 状态和 enable 成功路径也已验证。
- Model/Provider 创建默认值全部是前端基于现有 catalog 与当前对象的局部派生，没有引入模板语言、兼容字段或后端重复状态。

验证结果：

- Backend 聚焦：LLM config/task 58 passed；App/Endpoint 40 passed；新增启动、拒绝和成功激活路径通过。
- Fast：964 passed，2 skipped，26 deselected。
- Full：969 passed，2 skipped，21 deselected。
- Backend typecheck：`All checks passed!`
- Visualization：136 tests passed；`tsc && vite build` 通过。构建仅保留现有大 chunk 提示，不影响本次契约。
- `git diff --check` 通过。

## 完成标准

1. 新建或 reset 的 standard 项目在无凭据时可启动后端并连接设置前端；development 保持默认 Provider/Kimi Search enabled，并在缺失其必需凭据时严格启动失败。
2. disabled Provider 可以长期缺少 key；任何 enabled Provider 在当前 Generation 中都至少解析到一个非空 key。
3. 无 key enable 在前端有明确引导，在后端返回 `422`，不落盘也不替换 Generation。
4. Task 配置保留完整链，运行时只尝试当前可路由 Model；原有 Provider/Model 重试与偏好策略不回归。
5. New Model 默认 Blank，所有新 Provider Binding 不再使用固定 `"model"` 占位符。
6. New Provider 得到由自身 ID 派生且合法的默认 env 名称。
7. Endpoint、设计文档、package templates、代码和测试描述同一现行事实。
8. 完整本地门禁通过，执行计划逐项核对并记录结果。
