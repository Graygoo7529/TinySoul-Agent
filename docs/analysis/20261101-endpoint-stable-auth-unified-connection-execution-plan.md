# Endpoint 稳定认证与前后端统一连接执行计划

日期：2026-11-01

状态：implemented-and-verified

## 目标

把 TinySoul 的后端 Endpoint 连接收敛为一条长期稳定、前后端一致的协议：

    前端连接目标 = client-reachable address + stable bearer token

浏览器、Tauri 桌面端、本地开发和远程主机都填写同一种 ip:port + token。后端重启、源码更新和普通项目配置变更不改变连接目标；前端通过 logout 清除自己的连接凭据并切换到另一台主机。

本计划基于当前 AGENTS.md 的所有权和生命周期约定修订：

- Gateway/Endpoint 负责鉴权、协议映射和运行投影，不拥有 Agent/Turn 业务状态。
- CLI 负责进程启动配置；Infra 的 ConfigEnvironment 继续负责 .env 与进程环境来源。
- 前端只持有自己的连接目标，不读取后端项目文件，不依赖后端本机路径。
- 项目没有向后兼容压力，旧的租约发现链路、开发专用快捷连接和不再需要的字段可以直接删除。

## 已确认的设计决定

### 1. 后端配置文件的职责

后端部署目录使用两个本地文件：

| 文件 | 内容 | 生成/保留 | Git |
| --- | --- | --- | --- |
| .auth | 仅保存 Endpoint bearer token | init 生成；reset 原样保留 | 忽略 |
| .env | 可选的 Endpoint 监听配置和外部凭据 | init 不生成；reset 原样保留 | 忽略 |

.auth 使用明确的单键格式：

    token=<url-safe token>

读取时只接受一个 token 值，并继续执行长度和非空校验。普通环境变量不覆盖 .auth，避免进程环境意外改变长期授权凭据。修改 .auth 是明确的 token 更换操作，前端下次连接需要重新登录。

.env 保留现有 Infra dotenv 语义，用于部署目录的本地配置。Endpoint 只增加两个可选字段：

    TINYSOUL_ENDPOINT__BIND_HOST=127.0.0.1
    TINYSOUL_ENDPOINT__PORT=1430

它们不是前端登录数据，也不进入 .auth。.env.example 会说明默认值和远程绑定示例，但 init 不把示例复制成 .env。因此现有“.env 由使用者填写、reset 原样保留”的生命周期保持不变。

不引入 .connection 或 .endpoint 文件：前者容易与前端保存的连接目标混淆，后者会为两个简单的监听字段增加另一套解析、优先级、保留和文档规则。也不把监听配置放入项目 TOML；Endpoint 监听器属于 Gateway 进程启动边界，不是 Agent 业务配置。

### 2. 监听地址和端口

- 后端默认监听 127.0.0.1:1430。
- 1430 是部署默认固定端口，形成可长期保存的连接地址。
- TINYSOUL_ENDPOINT__BIND_HOST 可以显式设置 0.0.0.0 或具体 IPv4/IPv6 地址，以支持远程电脑连接。
- BIND_HOST 是 socket 监听地址；前端填写的是实际可访问的主机地址，例如 192.168.1.20:1430。
- 配置端口必须为 1..65535。底层 Endpoint 测试仍可显式使用 port=0 取得临时端口，生产 CLI 不使用随机端口。
- 进程环境继续按 Infra 现有优先级覆盖 dotenv；这属于明确的启动覆盖，而不是前端凭据。所有普通启动文档使用 .env 的固定值，避免把进程环境覆盖误当作持久连接配置。
- EndpointSettings 允许绑定任意可解析 IP，不再只允许 loopback；不接受无法确定 socket 语义的任意主机字符串。

### 3. token 生命周期

- tinysoul init 在新项目 staging 目录中生成一次 .auth。
- 普通 tinysoul start 只读取已有 .auth；缺失、格式错误或 token 过短时启动失败，并给出不包含 token 内容的配置错误。
- 普通重启、源码更新、git pull 和 .env 中的普通配置变化不会改变 .auth。
- tinysoul reset 保留已有 .auth 字节，不生成新 token，不静默修复缺失 token。.auth 缺失时 reset 后仍缺失，下一次普通 Endpoint 启动失败；这是“缺少 token 直接失败”的明确语义。
- tinysoul start --once 不启动 Endpoint，继续允许无 .auth 执行单次 CLI Turn。
- 启动日志只报告实际绑定地址和 token 来源（.auth），绝不打印 token 内容。

### 4. 前端连接和 logout

前端唯一持久化的后端连接目标是：

    { address, token }

instanceId、projectIdentity 等运行身份只属于一次连接握手返回值，不进入持久化目标。浏览器 localStorage 和 Tauri 使用同一存储协议；Tauri 不再读取后端本机租约文件。

logout 的语义是：

1. 关闭当前 WebSocket/事件流并取消重连定时器；
2. 清除当前连接状态和本地保存的 {address, token}；
3. 返回统一登录表单，允许输入另一台主机；
4. 不停止后端 Agent、不取消后端 Turn、不修改后端 .env 或 .auth。

自动连接只尝试本地存储的最后一个成功目标。存储为空或凭据失效时显示同一个 address/token 登录表单。

## 当前实现与目标的差距

当前 tinysoul/gateway/cli.py 每次交互式启动用 token_urlsafe(32) 生成 token，EndpointSettings 默认使用 loopback 和随机端口 0。ProjectInstanceLease 还把 token、host、port 写入用户目录的 JSON 租约，Tauri Rust 命令和前端 discoverLocalLease 读取该租约，形成第二套本机发现和凭据复制链路。

当前 init 只复制 .env.example，不创建 .env；reset 原样保留 .env 并替换其它项目内容。这个生命周期适合继续承载可选的 bind host/port。目标方案新增的只有 .auth 的生成和保留，不改变 .env 的创建/保留规则。

当前 HTTP Bearer、WebSocket 首帧 token、health/status 握手和前端 {address, token} transport 已经存在，因此协议主体不需要重建，主要工作是收敛 token 来源、启动配置和连接发现。

## 实施范围

### A. Endpoint 启动配置和认证读取

涉及：

- tinysoul/gateway/endpoint/config.py
- 新增或整理 Endpoint owner 内部的 .auth 读取/生成实现
- tinysoul/gateway/cli.py
- tinysoul/agent/composition/builder.py
- .gitignore（源码仓库本地凭据忽略）
- tinysoul/assets/common/.env.example
- tinysoul/assets/common/.gitignore

实施内容：

1. 为 Endpoint 启动配置增加明确的 typed parser，读取 endpoint.bind_host 和 endpoint.port，默认 127.0.0.1、1430，并映射为内部 EndpointSettings.host/port。
2. 在 Endpoint owner 内实现 .auth 文件的生成、读取和格式校验。生成使用 secrets.token_urlsafe，写入 staging 或原子文件；读取失败转换为 Endpoint 配置边界错误，不泄露原始内容。
3. CLI 先构造 ConfigEnvironment，在交互式启动时读取 endpoint 启动配置和 .auth，再构造 EndpointSettings。--once 跳过 Endpoint 配置和 .auth。
4. EndpointSettings 取消 loopback-only 校验，保留 IP、端口、token、内部资源容量等不变量。部署默认端口固定为 1430；直接构造测试可明确传 0。
5. 将 endpoint 作为 Gateway 保留的启动配置 section，避免 .env 中的 TINYSOUL_ENDPOINT__* 被 AgentBuilder 当作未知业务 section；Agent 本身不解析或拥有这些字段。
6. 删除 CLI 每次启动的随机 token 生成。Endpoint 启动成功输出 host/port 和 token 来源，不输出 token。
7. 保持现有 HTTP/WS Bearer 认证和协议版本，不增加 session、账户、token revoke、TLS 或 Endpoint 写文件 API。

预期效果：

    init -> .auth 生成
    start -> 读取 .env 可选监听配置 + .auth 固定 token -> 127.0.0.1:1430
    remote -> .env 设置 BIND_HOST=0.0.0.0 -> 前端输入实际主机 IP:1430 + token

### B. 项目初始化和 reset 生命周期

涉及：

- tinysoul/gateway/project/initializer.py
- tinysoul/gateway/cli.py
- tests/gateway/project/test_initializer.py
- tests/release/test_wheel.py 及受影响的打包断言

实施内容：

1. ProjectInitializer 在模板 staging 完成后生成 .auth，再整体替换空目标。.auth 不作为包内静态资源，不把 token 写入源码模板。
2. 更新初始化结果和测试辅助逻辑，使测试区分“包内资源快照”和“初始化生成的本地凭据”，不再用完整目录等于包资源的断言否决动态 .auth。
3. ProjectResetter 在替换前读取并校验 .env、.auth 是普通文件；存在时分别原样写入 staging。保留状态分别以 env_preserved、auth_preserved 表达，CLI 输出分别报告。
4. .auth 缺失时 reset 不生成；.env 缺失时也继续缺失。.env.example 始终随新模板更新。
5. 将 .auth 加入项目模板 .gitignore，同时保留现有 .env、runtime、archive 忽略规则。
6. 更新项目内 README.md 和 tinysoul/assets/common/README.md，明确 .auth、.env、init/reset 的实际关系。

### C. 删除租约凭据发现链路

涉及：

- tinysoul/gateway/project/instance.py
- tinysoul/gateway/endpoint/host.py
- tinysoul/gateway/endpoint/__init__.py
- tests/gateway/project/test_instance.py
- tests/gateway/test_cli.py
- tests/gateway/test_cli_fake_provider.py
- Endpoint host/contract tests

实施内容：

1. 保留 ProjectInstanceLease 的单项目进程锁、项目 identity 和 process-local instance_id，因为它们仍然负责防止同一项目重复运行和识别当前 Endpoint 进程。
2. 删除 record path、publish()、租约 JSON 的 token/host/port 写入和清理逻辑。锁文件不再承担连接发现或授权职责。
3. 删除 EndpointReady 中用于发布租约的 token 和发布字段、ready 回调；若无其它真实消费者，直接移除该类型和相关测试，不保留兼容别名。
4. 保留 status 中用于运行身份和 generation 变化的 instance_id/project_identity 投影，但不把它们当作登录凭据。
5. 删除 Tauri discover_backend command、Rust 的租约 JSON 结构和本机路径推导；保留与 trace 导出无关的现有 Tauri 能力。

预期效果：

    ProjectInstanceLease = 进程锁和运行身份
    .auth              = 稳定授权凭据
    前端 localStorage  = address + token

三者不再互相复制职责。

### D. 前端统一连接

涉及：

- visualization/src/app/discovery.ts
- visualization/src/app/connection.ts
- visualization/src/components/shell/ConnectScreen.tsx
- visualization/src/components/shell/AppShell.tsx
- visualization/src/components/shell/TopBar.tsx
- visualization/src/store/appStore.ts
- visualization/src/App.tsx
- visualization/src-tauri/src/lib.rs
- visualization/src/app/*、shell 相关测试

实施内容：

1. 收敛 ConnectTarget 为 {address, token}；删除 lease-only 的 identity 字段和旧 host/port 存储迁移分支。
2. 将 discovery 模块收敛为连接目标存储，或按现有依赖关系重命名为 storage 模块；不再导入 Tauri invoke 进行后端发现。
3. autoConnect() 不再接受 projectRoot，浏览器和 Tauri 走同一条“读取最后目标并连接”路径。
4. connect() 成功后保存目标；后端 instance_id 变化时重新使用最后保存的 address/token 做握手，不重新读取本机文件。
5. 新增并接入 logout()，清除连接目标、当前连接和重连状态；连接界面只保留 address/token 表单和错误反馈。
6. 顶栏提供 logout/切换连接入口，显示当前 address；不提供后端停止、重启或修改 .auth 的伪装操作。
7. 删除 appStore.projectRoot 及硬编码开发者路径；App.tsx 调用无参数的 autoConnect()。
8. 删除 Rust discover_backend、BackendConnection、InstanceRecord 及其 handler 注册，确保桌面端编译不再依赖后端项目路径。

### E. 文档同步

涉及：

- README.md
- tinysoul/assets/common/README.md
- tinysoul/assets/common/presentation/README.md
- docs/design/endpoint.md
- docs/endpoint/index.md
- docs/endpoint/frontend-integration.md
- visualization/docs/design/connection.md
- visualization/README.md
- visualization/docs/demand/20261030-endpoint-stable-token-remote-bind.md
- visualization/docs/demand/README.md

文档统一说明：

1. 本地开发命令：tinysoul init、tinysoul start、前端输入 127.0.0.1:1430 + .auth token。
2. 远程主机：在主机项目目录 .env 设置 TINYSOUL_ENDPOINT__BIND_HOST=0.0.0.0 和可选端口，前端输入主机可达 IP 与 .auth token。
3. .auth 属于后端部署目录，前端只保存用户输入的 {address, token}，不会访问主机文件。
4. reset 保留 .env 和 .auth，清除 runtime、archive、memory 等项目数据；缺少 .auth 时普通 Endpoint 启动失败。
5. logout 只清除前端连接凭据和当前连接，不影响后端 Agent。
6. instance_id 是运行身份，不是登录 token；租约发现不再是连接协议。
7. 删除“App 发布本机 Endpoint 租约”“本机快速连接”“loopback-only Endpoint”等过时描述。

需求文档在实现完成后更新为 `implemented` 并由 demand 索引归入已实现条目，避免 pending 索引继续描述已经完成的旧方案。

### F. 测试重组和语义覆盖

后端测试重点：

- Endpoint 启动配置：默认 bind host、固定部署端口、显式远程 bind、IP/端口/token 校验。
- .auth：init 生成、读取稳定 token、缺失/格式错误启动失败、reset 保留字节、reset 不生成缺失 token。
- .env：可选 bind host/port 读取、进程环境覆盖、普通 .env 保留；不测试具体 provider/model 清单。
- CLI：普通 start 使用稳定 token，--once 不要求 Endpoint token，启动输出不包含 token。
- HTTP/WS：继续验证 Bearer 和首帧 token 的既有协议，以及未授权响应不泄露 token。
- ProjectInstanceLease：只测试互斥锁和 identity；删除租约 JSON 发现/授权断言。
- Endpoint API：保留真实协作边界和代表性成功/失败路径，删除 ready callback、token-bearing lease 的冗余矩阵。

前端测试重点：

- {address, token} localStorage round-trip 和无效存储回退。
- connect 成功自动保存目标，失败不污染旧状态。
- autoConnect 只使用保存目标，浏览器/Tauri 不分支读取项目路径。
- logout 关闭流、清除保存目标和当前状态，并可立即连接另一台主机。
- 重连沿用最后目标；instance/generation 变化只触发重新握手和投影刷新。
- ConnectScreen/TopBar 只验证统一表单和 logout 行为，不固化具体地址、token、模型或 provider 文本。

删除或修改以下旧测试假设：

- Tauri 读取本机 lease JSON。
- projectRoot 默认是维护者机器上的硬编码路径。
- 每次启动生成新 token、随机生产端口。
- 初始化目录只能精确等于包资源而不能有生成的 .auth。
- 具体 .env.example provider key、模型名、action catalog 内容的逐项快照。

### G. 标准验证入口

实现过程中始终使用项目统一入口：

    uv run --locked --extra dev python scripts/test.py --suite fast
    uv run --locked --extra dev python scripts/test.py --suite full
    uv run --locked --extra dev ty check
    cd visualization; pnpm test
    cd visualization; pnpm build

必要时先运行受影响的窄集：

    uv run --locked --extra dev python scripts/test.py tests/gateway tests/infra/config

最终还需执行：

- git diff --check
- Python fast/full 和 TypeScript/Tauri 构建
- 在临时项目目录中验证 init -> 读取 .auth -> 本地登录 -> 重启后端 -> 自动重连
- 在临时项目目录中设置非 loopback bind，使用实际局域网地址完成一次 HTTP/WebSocket 登录
- 删除 .auth 后确认普通 start 明确失败，start --once 仍可运行
- 执行 reset，确认 .env、.auth 原样保留且 runtime/archive/memory 数据按既有语义清理

## 实施顺序

1. 先实现 Endpoint 配置和 .auth owner，更新 EndpointSettings、CLI 和启动错误。
2. 修改 init/reset 和资源模板，补齐 .auth 生成、保留、忽略规则。
3. 移除租约发布及对应 Python/Rust 发现代码，保留进程锁和运行身份。
4. 重构前端连接存储、autoConnect、logout、ConnectScreen 和顶栏。
5. 按当前实现同步设计文档、项目 README、前端 README 和 demand 归档。
6. 先跑受影响的 Python/前端窄集，再跑 fast/full、类型检查和构建。
7. 对照本计划、AGENTS.md 和 git diff --check 做最终审阅，确认没有残留随机 token、随机生产端口、硬编码项目路径或 token-bearing lease。

## 可行性核对

本计划可直接落地，原因如下：

1. HTTP Bearer 和 WebSocket token 已经存在，只需替换 token 来源，不需要重做协议。
2. ConfigEnvironment 已支持 .env、进程环境和 typed section parser；新增 endpoint 保留 section 可以复用现有配置链路。
3. Endpoint host/server 已经接受 EndpointSettings，固定端口和非 loopback 校验集中在一个 owner 内。
4. 初始化/reset 已有 staging、原子替换、.env 保留和失败回滚流程；.auth 可作为同类的本地部署文件加入，不需要新建数据迁移系统。
5. 前端 transport 已经接受 address/token，改动集中在发现来源、持久化和 UI 生命周期。
6. 项目锁和运行身份与租约 JSON 可以独立，删除发现文件不会影响 Agent/Turn、generation 或 Endpoint status 语义。

主要风险是边界清理而不是新架构：

- 初始化目录快照、reset 结果对象和 CLI 测试需要从单一 .env 保留扩展为 .env/.auth 两项。
- 删除 Rust discovery 后必须同步删除所有 TypeScript 调用和 Tauri handler 注册。
- 固定端口要求直接启动 Endpoint 的测试显式使用临时端口，避免测试之间争用 1430。
- .env 的 endpoint 字段必须加入 Gateway 保留 section，否则 AgentBuilder 会把它误判为未知业务配置。

这些风险都有明确 owner、局部测试和验证命令，没有未决的架构决策。.auth 格式、.env 的 host/port 生命周期、固定端口、reset 行为和前端 logout 语义均已确定，本计划已完成实施并进入最终核对。

## 完成标准

- 普通 start 在稳定 .auth 和默认/显式监听配置下启动，重启后地址和 token 不变。
- init 生成 .auth，reset 原样保留 .auth 和 .env，缺失 .auth 的普通 Endpoint 启动明确失败。
- 本地和远程前端都只需输入 address + token；浏览器和 Tauri 不依赖后端本机路径或租约文件。
- logout 能清除本地目标并切换主机，不改变后端运行。
- 项目不再生成或读取 token-bearing instance lease，不再保留硬编码开发者路径。
- 文档、测试、源码和 AGENTS.md 的 owner、配置、生命周期描述一致。
- fast/full、Python 类型检查、前端测试和 TypeScript/Vite 构建全部通过；Rust
  `cargo check` 因当前机器未安装 cargo 尚未执行。

## 实施核对（2026-11-01）

计划中的代码和文档范围已完成：

- Gateway 使用 `EndpointLaunchSettings` 读取 `.env` 的 bind host/port，默认固定
  `127.0.0.1:1430`；`.auth` owner 负责生成和校验稳定 token，普通 `start` 缺少
  凭据时失败，`start --once` 不打开 Endpoint。
- `init/reset` 的 staging、保留和 `.gitignore` 已覆盖 `.auth`；reset 同时报告
  `.env` 与 `.auth` 是否保留。
- `ProjectInstanceLease` 只保留进程锁和运行身份；EndpointReady、token-bearing
  JSON 租约、Tauri `discover_backend` 和前端 `projectRoot` 已移除。
- 浏览器和 Tauri 共用 `{address, token}` 本地存储；自动连接、重连和 logout 已
  统一，logout 不影响后端 Agent。
- README、Endpoint 设计/协议、前端连接设计和 demand 索引已改为当前语义。

验证结果：

- Python fast：`1370 passed, 145 deselected`。
- Python full：`1512 passed, 3 deselected`。
- Endpoint server random-port and explicit non-loopback bind checks: `2 passed`.
- `ty check --python .venv`：通过。
- 前端 Vitest：`100 files, 879 tests` 通过。
- 前端 `tsc + vite build`：通过。
- `git diff --check`：通过。

当前机器没有 `uv` 和 `cargo` 命令，因此用已有 `.venv` 执行等价 Python 检查；
Tauri Rust 的 `cargo check` 未能执行，代码已同步移除发现命令及 `sha2` 的直接依赖，
应在安装 Rust 的开发环境中补跑仓库 README 中的构建命令。

### AGENTS.md 对照

- 认证和监听属于 Gateway/Endpoint 进程边界；`.env` 仍由 Infra 配置设施读取，
  Agent 仅登记 `endpoint` 为保留 section，不拥有其业务语义。
- `.auth` 是后端部署目录凭据，前端只拥有 `{address, token}` 的客户端目标；没有
  新增第二套调度器、业务状态副本、通用文件 API 或兼容别名。
- ProjectInstanceLease 继续只承担进程锁和运行身份，Session/Turn/Generation 的
  owner 与生命周期没有被 Endpoint 或前端复制。
- 测试保护稳定行为（token 生命周期、bind/port 校验、reset、统一登录/logout），
  没有逐项固化 provider、model、prompt 或 action catalog 的可编辑内容；测试中间
  产物由既有 `.local-test/` 管理。
- 旧发现链路属于已放弃设计，已直接删除而未建立过渡兼容层，符合当前开发阶段无
  向后兼容压力的规约。
