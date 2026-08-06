# Infra 设计

## 定位

Infra 提供项目底层运行设施。它不表达具体业务语义，也不拥有上层模块的领域配置。

Infra 当前负责配置环境、JSON 动态边界、受控文件系统读写、Python 依赖可用性检查、owner-neutral 的 `BusinessDay` 值对象，以及 provider-neutral 的文本 embedding 配置和窄客户端协议。每项基础能力都保持小而明确的边界，避免反向了解 Loop、Action、LLM、Memory、Workspace 或具体 capability 的业务细节；业务时区、业务日切策略、检索融合、日志和通用进程运行不属于 Infra 当前职责。

## 配置边界

配置加载机制属于 Infra；具体配置项属于使用它的模块。

例如，Infra 可以提供读取配置、合并来源、类型转换、配置树访问和错误报告的机制，但不应把 LLM provider catalog、Action 策略、Loop 语义或 Workspace 规则集中放进 Infra。

各模块应定义自己的配置结构和默认值。应用入口或组合层负责构建统一配置环境，再把相关配置交给模块。模块内部不应依赖导入时生成的全局配置对象。

## 配置来源

配置应支持多种来源，并保持明确优先级：

1. 代码默认值
2. 项目配置文件
3. 本地环境文件
4. 系统环境变量
5. 显式传入覆盖

后面的来源覆盖前面的来源。覆盖关系必须可解释，错误报告应能指出配置值来自哪里。

项目配置文件用于可读、可写、可提交的非敏感配置。本地环境文件用于密钥、本机差异和开发环境临时值。系统环境变量用于部署、持续集成和命令行覆盖。显式传入覆盖用于测试或上层调用。

项目配置由 `tinysoul.toml` 作为入口，显式 include `configs/*.toml` 与 `configs/llm.models/*.toml`。app/action/context/home/memory/embedding/loop/workspace 和 LLM provider/task 分别保存在对应配置文件中；Memory 使用独立 `[memory]`，embedding 使用独立 `[embedding]`，Home parser 不接受旧 `[home.memory]`。include pattern 必须是项目根内的相对路径：绝对路径与含 `..` 的路径在展开前拒绝，每个 glob 命中项在解析真实路径后还必须位于项目根内，以防符号链接绕过边界。glob 展开顺序稳定；主文件和每个 include 作为独立有序 source 保留，后加载文件覆盖前文件时仍可定位最终值来自哪个实际路径。Infra 只负责读取和合并这些文件，不解释其中的领域语义；模块 parser 在实际模块边界把 section tree 转成 Settings。

`tinysoul init --config-profile` 与 `tinysoul reset --config-profile` 属于 App-owned 的项目模板物化期文件选择，不是新的配置来源。standard/development profile 各自提供一套完整配置，initializer/resetter 只物化其中一套为普通 `configs/` 与 `.env.example`；resetter 只把旧项目的普通 `.env` 作为不解释内容的保留文件复制进新项目。生成项目不保存 profile identity，Infra 也不读取 package profile、执行 profile overlay 或自动同步模板更新。运行时配置优先级仍只有代码默认值、项目文件、本地环境文件、系统环境变量和显式覆盖。

profile 文件由 package project template 拥有，但其中各 section 的语义仍归对应业务模块。模块新增、删除、重命名配置键或拆分 TOML 文件时，开发者必须同步审查 `config_profiles/standard/configs` 与 `config_profiles/development/configs`：两者保持相同相对文件集合、相同 section/schema 形状并各自通过模块 parser，值差异只能表达已确认的初始化策略。代码默认值不通过复制 profile 推导，profile 也不能替代模块默认值或校验。profile 引用的 credential/专用环境变量名必须出现在同 profile 的 `.env.example` 中，但真实值永不进入模板。该同步责任属于源码维护与发布验收，不属于 ConfigEnvironment 运行时。

## 可写配置

项目需要适合人阅读和编辑的配置文件，承担长期、非敏感配置的存储角色。

配置文件应支持分组，使不同模块的配置自然归属到自己的命名空间。配置可以按主题或目录拆分到多个文件，但加载顺序必须显式、稳定、可解释。写入配置时应保持内容稳定、可预测，并避免把密钥或临时环境值写入项目配置。

可写配置不是运行时状态存储。它只保存用户或项目希望长期保留的配置选择。

## 环境文件

本地环境文件应被解析为配置来源，而不是在读取时直接写入进程环境。

这样可以避免加载配置时污染全局进程状态，也让测试、嵌入式运行和多实例运行更加清晰。系统环境变量仍然可以作为更高优先级来源参与覆盖。

环境文件主要承载敏感信息、本地路径、开发机差异和不适合提交的临时配置。

`env_file` 与 include 使用相同的项目边界：只接受项目根内相对路径，拒绝绝对路径、`..` 以及解析真实路径后越出项目根的目标。配置入口不能借由环境文件读取项目外任意文件。

环境变量应使用清晰的命名规则映射到配置路径。常规配置项可以使用项目统一前缀加模块路径，例如将模块、分组和字段组合成大写名称。字段名本身可以保留下划线，以避免长字段被错误拆分。需要显式表达更深层路径时，可以使用双下划线作为分段标记。

## 类型与校验

配置项应尽量使用明确类型。基础设施应支持常见标量、路径、枚举和简单列表的类型化加载。嵌套分组通过配置树视角提供给对应模块，由模块自己的解析器解释和校验。

复杂领域配置不应退化为任意字典在模块内部流动。需要复杂结构时，应由对应模块定义清楚的配置形态，从配置树入口读取动态数据，并在模块边界完成解析和校验。

配置错误应尽早暴露，错误信息应包含配置键、来源、原始值、期望类型和失败原因。AppBuilder 先拒绝未知顶层 section，各模块 parser 再拒绝自身 table 中的未知键；嵌套未知键也不允许静默穿过。`ConfigEnvironment.parse_section` 根据最终获胜的 main/include/dotenv/environment/override source 为模块 parser 产生的 `ConfigError` 补充来源，因此拼写错误和语义错误使用同一套 key/source 诊断。

Infra 自身只抛出配置和基础设施语义的错误，不直接表达 Runtime 控制流。当前 Infra bridge 的真实跨模块路径只有配置加载失败，并将其映射为启动失败；JSON 和受控文件系统错误由拥有具体调用流程的业务模块局部处理或通过该模块 bridge 映射。Infra 不为没有消费路径的假想失败维护枚举项。这样 Infra 保持纯基础设施边界，Runtime 也不会反向侵入配置加载实现。

Infra bridge 只翻译确实需要 Runtime 协调的模块失败，不替业务模块兜底分类。bridge 显式构造稳定、精简、JSON 安全的 payload；原始异常链用于调试，payload 不承载 traceback、文件内容或调用方内部对象。

JSON 值类型、JSON 对象校验和稳定序列化属于 Infra 的公共基础能力。来自模型输出、配置文件或外部接口的动态 JSON 数据应在进入模块内部边界时转换为明确的 JSON 值结构。具体 JSON 内容表达什么业务含义，仍由使用它的模块解释。

## 依赖检查

`DependencyChecker` 只检查当前 Python 解释器中 distribution metadata 和 import module 是否存在，不导入目标模块、不执行安装，也不了解 action enabled 或 adapter 选择。业务模块根据自身 effective settings 构造 `DependencyRequirement`，并解释 `DependencyCheck`；因此 Resource 等 capability 可以在 App 装配期拒绝“已启用但依赖缺失”，而禁用能力无需检查。依赖需求、可选 feature 和失败归属仍由 capability 自己拥有。

## Text Embedding

`EmbeddingSettings`、`EmbeddingClient`、`EmbeddingBatch` 和 OpenAI-compatible adapter 属于 Infra，因为它们只表达文本到有限浮点向量的外部基础能力，不表达 Memory Link、候选排序或缓存语义。`[embedding]` 配置包含 enabled、base URL、model、环境变量名、dimensions、batch size、timeout 和派生缓存大小；API key 只能由 `ConfigEnvironment.runtime_env` 按显式变量名解析，TOML 不接受 `api_key`。

adapter 校验非空批次、批量上限、响应 index、向量数量、维度和有限浮点值，并把 provider 异常压缩成不含响应正文或密钥的 `EmbeddingError`。当前 `embedding-3` 配置只接受官方支持的 256/512/1024/2048 维。Infra 不持久化向量、不执行 cosine、不决定降级；Memory owner 使用该协议维护可删除缓存，并在请求失败时回退自己的 lexical/reference 检索。

## 使用方式

配置应显式加载、显式传递。

应用入口或组合层负责构建统一配置环境，再把相关配置交给需要的模块。模块不应在导入时自动读取文件、解析环境或创建全局单例。

这种方式能让配置来源、测试覆盖和运行边界保持清楚，也避免不同模块在不同时间读取到不一致的配置。

统一配置环境应同时提供配置树视角和类型化分段加载视角。结构化模块配置读取自己的配置树并自行解析；简单配置可以直接加载为类型化设置。两种读取方式应来自同一套来源和优先级规则，而不是两套独立配置机制。

`tinysoul.infra` 提供稳定公共门面，导出配置环境、配置错误、TOML/dotenv source、JSON 边界和受控文件系统读写能力。业务模块应优先依赖这个门面或明确子包门面，不应跨入 infra 内部实现细节。

来自 dotenv、TOML、环境变量和项目配置树的动态边界错误统一表达为 `ConfigError`。Infra 公共入口不使用裸 `ValueError` 或 `TypeError` 表达配置语义失败；内部 Python 转换异常只在局部捕获后映射为包含 key、source、value 和 expected 的配置错误。

## 设计范围

配置环境机制属于 Infra 的基础能力。其他基础设施应在存在清楚使用场景时建立，不应为了未来可能需要而提前创建没有实际使用场景的抽象。

设计重点是保持配置清晰可读、来源可解释、错误可定位，并为模块重构提供稳定基础。
