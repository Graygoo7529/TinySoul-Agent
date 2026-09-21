# Infra 设计

## 定位

Infra 提供项目底层运行设施。它不表达具体业务语义，也不拥有上层模块的领域配置。

Infra 当前负责配置环境、JSON 动态边界、受控文件系统读写、Python 依赖可用性检查、owner-neutral 的 `CalendarDay` 值对象，以及 provider-neutral 的文本 embedding 配置和窄客户端协议。`infra/json/schema.py` 提供限定 dialect、无网络引用解析的标准 JSON Schema 校验；`infra/process/stdio.py` 在同一平台进程所有权内提供有界异步双向管道，供协议能力使用。每项基础能力都保持小而明确的边界，避免反向了解 Loop、Action、LLM、Memory、Workspace 或具体 capability 的业务细节；业务时区、日切策略、检索融合与业务日志不属于 Infra。通用受控进程位于 infra/process，由 Action worker 适配器和 execution Job 后端共同消费，不携带 Job/Turn 身份。

配置内部按 sources、editing、descriptors 分开来源读取、候选文件事务与展示描述；ConfigEnvironment/ConfigController 保持公开门面。描述符模型和加载器不创建业务对象，业务 owner 显式解释自己的 section。

## 配置边界

配置加载机制属于 Infra；具体配置项属于使用它的模块。

Infra 同时拥有 package 内的配置展示目录，但不拥有业务配置语义。目录位于
`tinysoul/infra/config/catalog/*.toml`，集中维护稳定 surface、collection identity、field group、
字段标题、说明、输入类型、primary/advanced 层级、静态 choices、正向引用、credential reference
标记和 collection 的设置页删除策略；
`ConfigCatalog` 在加载时校验 ID、pattern、引用与 source policy，并通过
`ConfigController.catalog()` 提供 JSON-safe 投影。业务模块不得复制这些展示说明，前端也不按
dotted path 猜测标签和归属。

普通 merged field 使用 `ConfigFieldDescriptor`；owner 管理的独立 TOML 文档使用
`ConfigDocumentFieldDescriptor(document_set, document_kind, path)`。后者只描述文件内局部字段的
展示方式，不携带当前值，也不让 Infra import Action 等 owner 类型。当前 Action Catalog 的全部
设置页说明集中在 `catalog/actions.toml`，Action 模块仍独占其解析和运行语义。

Catalog 不包含当前值、Runtime activity、业务默认值、parser callable、前端 route、React
component 或 secret value。Provider、Model、Task Chain 等对象仍只是 `ConfigStatus` 中同一
source/effective 配置事实的 collection view；Infra 不缓存对象投影，也不 import LLM、Action、
Capabilities 等业务模块。Catalog 资源错误是 Infra package contract failure，项目 TOML 的结构
与引用错误仍由各业务 parser 形成 `ConfigError`。

TOML 展开在 catalog 声明的 object 字段处停止，以整个映射作为配置值；对象内的点号、数字等 key 不解释为新的 dotted path。候选编辑和 source/effective 投影复用同一边界，工具选择、环境引用等映射按整体值覆盖。credential reference 可声明单个名称、名称数组或映射值；ConfigController 从有效引用派生需脱敏的环境变量集合，不把解析出的凭据带回配置投影。

Collection 的 `delete_policy` 只表达设置页是否提供删除命令：`all` 允许删除任意对象，
`create_source_only` 只允许删除全部 project TOML 定义都来自 collection `create_source` 的对象，
`none` 不提供删除命令。该策略不进入 `ConfigController` 的写入权限判断；Endpoint 仍可对任意可写
project TOML 执行 source-aware mutation。Custom Model 因此不增加重复配置字段，而由其是否完全归属
`configs/llm/models/custom.toml` 派生；带其它 source 定义或覆盖的 Model 不由设置页删除。

例如，Infra 可以提供读取配置、合并来源、类型转换、配置树访问和错误报告的机制，但不应把 LLM provider catalog、Action 策略、Loop 语义或 Workspace 规则集中放进 Infra。

各模块应定义自己的配置结构和默认值。应用入口或组合层负责构建统一配置环境，再把相关配置交给模块。模块内部不应依赖导入时生成的全局配置对象。

## 配置来源

运行时配置控制仍由 Infra 提供 source-aware 的无业务控制面：`ConfigSource` 带有
`PROJECT_TOML`、`DOTENV`、`ENVIRONMENT` 和 `OVERRIDE` 类型、稳定 `source_id` 与项目相对路径。
`ConfigFileToml` 和 `DotenvDocument` 在临时文档上执行结构化 set/delete；`ConfigFileTransaction`
以同根原子替换多个文档，保存失败时恢复已替换文件。`ConfigController` 只编排 source
图、候选环境、校验回调和两阶段 activation callback，不解析业务 section。dotenv 原始键值
单独保留在 `runtime_env`，系统环境仍覆盖 dotenv，进程 `os.environ` 不被写回。
配置 dotted path 的纯数字段保留为列表索引，因此项目 TOML 的映射键不得为纯数字。

`config.document_sets` 声明不参与 effective tree 合并的受管 TOML 集合。`ProjectConfig` 将 glob
稳定展开为 `ConfigDocumentSet/ConfigDocument`，为每个文件分配项目相对的稳定 source ID，并拒绝
同一文件同时属于 merged include 或多个 document set。`ConfigEnvironment` 在当前与候选快照中
携带这些文档；document mutation 的 path 是文件内局部 path。`ConfigController` 先在内存中构造
完整候选环境并调用 owner validator，成功后与普通 TOML、dotenv 一起提交为待激活候选。
显式 reload 在空闲时调用 Generation activator；失败保留当前世代和已保存候选。旧资源退休在激活成功后独立执行，退休失败不回滚文件或已生效世代。document 内容不进入 `effective_values()` 或普通 section parser。

配置写入由 `ConfigController` 的异步锁串行化；事务在替换前保存原文，并在文件提交失败时
恢复已替换文件。候选保存与显式激活分开，reload 失败保留已保存候选和旧活动世代。当前不计算或暴露 source fingerprint/revision，也不提供基于 revision 的并发
提交协议；单次写入的一致性由候选校验、串行化、原子替换和回滚保证。

通用并发设施提供 JoinedOperations、AsyncResourceScope 与 AsyncMailbox。JoinedOperations 只承载有界本地工作：调用开始后，即使调用方取消也等待真实结果，由业务 owner 记录后再传播取消。AsyncResourceScope 按注册逆序回收资源，嵌套作用域保留有限清理诊断，并发或重复关闭共用同一任务。AsyncMailbox 接受线程来源的投递，在一个事件循环上异步取出；它只提供唤醒与队列基础，不解释业务输入、事件路由、预算或 Turn 受理。

ServiceScope 的短操作可显式附带异步提交后回调，并在同一 lease 与 joined 边界内完成；Workspace 用它在正式写入返回前发布 owner 变化。Infra 不解释该回调的事件、领域状态或 Context 内容。

配置应支持多种来源，并保持明确优先级：

1. 代码默认值
2. 项目配置文件
3. 本地环境文件
4. 系统环境变量
5. 显式传入覆盖

后面的来源覆盖前面的来源。覆盖关系必须可解释，错误报告应能指出配置值来自哪里。

项目配置文件用于可读、可写、可提交的非敏感配置。本地环境文件用于密钥、本机差异和开发环境临时值。系统环境变量用于部署、持续集成和命令行覆盖。显式传入覆盖用于测试或上层调用。

项目配置由 `tinysoul.toml` 作为入口，显式 include `configs/*.toml`、`configs/action/*.toml`、`configs/capabilities/*.toml`、`configs/infra/*.toml`、`configs/llm/*.toml` 与 `configs/llm/models/*.toml`。Action routing 位于 `configs/action/routing.toml`；独立 Action 定义位于 `configs/action/catalog`，由 `action.catalog` document set 管理而不参与 merged include。单一业务 owner 的 agent/reflection/context/home/memory/loop/workspace/execution/jobs 等配置保留在 `configs/` 根部；独立 capability 配置位于 `configs/capabilities/`；Infra-owned 外部基础能力位于 `configs/infra/`；LLM provider/task 与按模型族拆分的 model 配置位于 `configs/llm/`。文件层次只表达维护归属，不改变 TOML section identity。Memory 使用独立 `[memory]`，Embedding 使用 `[infra.embedding]`，Home parser 不接受旧 `[home.memory]`。include/document-set pattern 必须是项目根内的相对路径：绝对路径与含 `..` 的路径在展开前拒绝，每个 glob 命中项在解析真实路径后还必须位于项目根内。glob 展开顺序稳定；主文件和每个 include 作为独立有序 source 保留，后加载文件覆盖前文件时仍可定位最终值来自哪个实际路径。ConfigEnvironment 只负责读取、合并或携带文档快照；各业务模块在自己的 parser/loader 边界解释内容。

`tinysoul init --config-profile` 与 `tinysoul reset --config-profile` 属于 Gateway-owned 的项目模板物化期文件选择，不是新的配置来源。standard/development profile 各自提供一套完整配置，initializer/resetter 只物化其中一套为普通 `configs/` 与 `.env.example`；resetter 只把旧项目的普通 `.env` 作为不解释内容的保留文件复制进新项目。生成项目不保存 profile identity，Infra 也不读取 package profile、执行 profile overlay 或自动同步模板更新。运行时配置优先级仍只有代码默认值、项目文件、本地环境文件、系统环境变量和显式覆盖。

公共文件位于 assets/common，预设文件位于 assets/standard 或 assets/development；生成时复制 common 与选中预设并拒绝重复目标。profile 文件由 package assets 拥有，但其中各 section 的语义仍归对应业务模块。模块新增、删除、重命名配置键或拆分 TOML 文件时，开发者必须同步审查 `assets/standard/configs` 与 `assets/development/configs`：两者保持相同相对文件集合、相同 section/schema 形状并各自通过模块 parser，值差异只能表达已确认的初始化策略。代码默认值不通过复制 profile 推导，profile 也不能替代模块默认值或校验。profile 引用的 credential/专用环境变量名必须出现在同 profile 的 `.env.example` 中，但真实值永不进入模板。该同步责任属于源码维护与发布验收，不属于 ConfigEnvironment 运行时。

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

配置错误应尽早暴露，错误信息应包含配置键、来源、原始值、期望类型和失败原因。AgentBuilder 先拒绝未知顶层 section，各模块 parser 再拒绝自身 table 中的未知键；嵌套未知键也不允许静默穿过。`ConfigEnvironment.parse_section` 根据最终获胜的 main/include/dotenv/environment/override source 为模块 parser 产生的 `ConfigError` 补充来源，因此拼写错误和语义错误使用同一套 key/source 诊断。

Infra 自身只抛出配置和基础设施语义的错误，不导入 Runtime，不维护 Runtime bridge 或 failure 枚举。配置源加载由 App 组合根解释；模块配置解释由对应 owner bridge 处理；UserTurnBuilder 的 staging 失败由 Loop 以资源准备失败报告启动失败。JSON 和受控文件系统错误同样由实际调用 owner 处理。

ConfigError 本地保留完整诊断供调试；`config_error_payload` 只提供有界 key 和 expected，不复制 source、value 或原始异常文本。业务 bridge 使用这份纯 JSON 投影并自行确定 module、kind 和运行原因，避免把本地调试数据直接变成 Runtime/Observation 协议。

JSON 值类型、JSON 对象校验和稳定序列化属于 Infra 的公共基础能力。来自模型输出、配置文件或外部接口的动态 JSON 数据应在进入模块内部边界时转换为明确的 JSON 值结构。具体 JSON 内容表达什么业务含义，仍由使用它的模块解释。

## 依赖检查

`DependencyChecker` 只检查当前 Python 解释器中 distribution metadata 和 import module 是否存在，不导入目标模块、不执行安装，也不了解 action enabled 或 adapter 选择。业务模块根据自身 effective settings 构造 `DependencyRequirement`，并解释 `DependencyCheck`；因此 Resource 等 capability 可以在 App 装配期拒绝“已启用但依赖缺失”，而禁用能力无需检查。依赖需求、可选 feature 和失败归属仍由 capability 自己拥有。

## Text Embedding

`InfraSettings` 严格解释完整 `[infra]` 子树，当前只接受 `[infra.embedding]`。`EmbeddingSettings`、`EmbeddingClient`、`EmbeddingBatch` 和 OpenAI-compatible adapter 属于 Infra，因为它们只表达文本到有限浮点向量的外部基础能力，不表达 Memory Link、候选排序或缓存语义。Embedding 配置包含 enabled、base URL、model、环境变量名、dimensions、batch size 和 timeout；API key 只能由 `ConfigEnvironment.runtime_env` 按显式变量名解析，TOML 不接受 `api_key`。派生缓存大小属于 Memory 的 `[memory.semantic_search]`。

EmbeddingClient 使用原生 async 请求，adapter 的自建 AsyncOpenAI client 由 generation 关闭；注入 transport 为借用对象。取消直接传播到网络任务，不转换为 EmbeddingError。

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

## 异步 owner 适配

ServiceScope 封装完整的 async 准入作用域；ScopedService 只将 owner 显式选择的方法暴露为 async 操作，不提供通用 getattr 或 owner 访问口。准入策略由 Agent 注入，Infra 不解释世代、业务日或 Runtime。短本地调用复用 JoinedOperations，取消先 join 并交付结果；operation 在复合调用中保持同一次准入，退出后临时视图失效。AsyncReadWriteLock 用协程等待处理跨 await 的日协调；同步锁只留在同一次短 owner 调用内部。Staging 的 async allocation 在取消后仍完成 cleanup。

## 日历时间

`CalendarClock` 与 `IanaCalendarClock` 提供显式时区的当前时间和 CalendarDay，不负责日切或根请求编排。Agent 的 day coordinator 持有活动日期；Turn 使用 `active_day`，Reflection 另外保留来源日和目标日。时钟可由测试或宿主显式注入，没有旧 BusinessClock 别名。

## 受控进程

ManagedProcessRunner 显式接收请求，拥有进程组、标准流捕获和有界硬停止。执行关闭与附属资源清理分开：已停止后日志/临时文件失败形成有限 CleanupDiagnostic；有界复查后仍无法停止则保留可再次关闭的句柄并抛出 Process 层错误。Action 与 Jobs 的适配器分别解释其失败，Infra 不产生 Runtime 转移，也不复制业务终态。输出读取有界，完整输出由调用方选择的捕获目录承载。

受控执行包含主进程及其后代，不能用主进程退出替代整个执行单元的关闭。Windows 挂起创建主进程，在加入系统 Job Object 后恢复初始线程，后代自动留在同一集合；停止集合并确认无活进程后才关闭执行。POSIX 使用启动时建立的独立进程组，主进程已退出仍对该组发出硬停止。平台细节封装在 infra/process，业务侧共用同一 ManagedProcess，不维护父 PID 列表或另一套监督器。系统容器不是安全沙箱；POSIX 主动另建 session/group 的脱离行为不在进程组所有权保证内。

启动失败先回收已获取的进程和句柄；挂起进程未能加入集合时不会执行用户代码。模块失败保留原始异常链用于调试，只以 Process 层异常跨出边界。Windows API 所有权依据见 [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) 与 [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)。
