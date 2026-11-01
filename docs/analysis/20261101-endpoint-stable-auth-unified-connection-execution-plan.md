# Endpoint 稳定认证与前后端统一连接执行计划

日期：2026-11-01

状态：ready-for-implementation

## 目标

把 TinySoul 的 Endpoint 连接收敛为一个清晰的长期协议：

```text
前端连接目标 = client-reachable address + stable bearer token
```

本机开发、远程主机部署、浏览器前端和 Tauri 前端都使用同一条连接路径。后端重启、源码更新或普通配置调整不会改变已保存的连接目标；前端通过 logout 清除本地凭据并切换目标。

本计划按 `AGENTS.md` 的 owner 和生命周期边界设计：Endpoint 负责认证与协议，CLI 负责进程启动配置，Infra/ConfigEnvironment 负责环境来源，前端只保存自己的连接目标，不读取后端文件，也不拥有 Agent、Turn 或运行数据。

## 已确认的设计决定

1. 不增加可写的 `[endpoint]` TOML。Endpoint 监听器属于进程启动边界；项目 TOML 继续只描述 Agent、模型、插件和业务行为。
2. 稳定 token 属于后端部署目录的 `.env`，不会放入 Git，也不会由前端读取。`tinysoul init` 为新项目生成 token；缺少 token 时后端启动失败，不回退为每次启动随机 token。
3. Endpoint 使用固定端口，默认 `1430`。`0` 只保留给直接构造的测试或明确的临时嵌入场景，不作为部署配置默认值。
4. 默认只绑定 loopback；只有后端启动配置明确设置非 loopback 绑定地址时才允许远程连接。
5. 前端保存 `{address, token}`，logout 清除保存的目标、当前连接和本地连接状态。logout 不修改远程主机 `.env`，也不伪造服务端 token 撤销。
6. `instance_id` 仍是一次后端进程的运行身份，用于检测 Endpoint 替换和事件续传；它不是登录凭据，也不进入前端持久化目标。
7. 不引入用户名、密码数据库、服务端 session、TLS、账户管理或主机更新脚本。项目按 `AGENTS.md` 的个人受信主机假设运行。

## 数据所有权与实际部署模型

| 位置 | 保存内容 | 是否随 Git 更新 | 作用 |
| --- | --- | --- | --- |
| 后端项目 `.env` | `endpoint` token、bind host、port、模型凭据 | 否；`.gitignore` 忽略 | 某个主机/数据目录的启动配置 |
| 后端 `tinysoul.toml` 与 `configs/` | Agent、模型、Action、插件和业务配置 | 是 | 可复现的项目行为配置 |
| 前端浏览器/Tauri 存储 | `address + token` | 否；每台前端独立 | 自动连接和 logout 切换目标 |
| 后端 `runtime/`、`memory/`、`archive/` | Session、Workspace、Memory 等事实 | 否 | 主机上的 Agent 数据 |

后端环境变量使用现有配置来源的命名约定。为明确它是监听接口而不是前端登录地址，采用：

```dotenv
TINYSOUL_ENDPOINT__TOKEN=stable-token-at-least-32-characters
TINYSOUL_ENDPOINT__BIND_HOST=127.0.0.1
TINYSOUL_ENDPOINT__PORT=1430
```

`__` 只表示 `ConfigEnvironment` 将环境变量映射为内部 dotted key；它不代表存在 `[endpoint]` TOML。`BIND_HOST` 是后端 socket 的监听地址，前端输入的是实际可达的 `address`：当后端绑定 `0.0.0.0` 时，前端应填写主机的局域网或可达 IP。

环境来源保持现有优先级：进程环境可以有意覆盖 `.env`，但启动输出只报告 token 来源，不输出 token 本身。除非明确修改 `TINYSOUL_ENDPOINT__TOKEN`，普通配置修改和后端重启不会改变 token。

## 现状与需要解决的缺口

- `tinysoul/gateway/cli.py` 在每次 `start` 中调用 `token_urlsafe(32)`，已保存的前端凭据在后端重启后失效。
- `EndpointSettings` 默认 `host=127.0.0.1` 且拒绝非 loopback，远程前端无法连接真实网卡。
- `EndpointSettings.port=0` 让系统每次自动分配端口，无法形成可长期保存的 `ip:port`。
- `ProjectInstanceLease` 将 token、host、port 写入本机租约 JSON；该文件只适合同机 Tauri 发现，不是 A/B 部署的连接协议，也重复保存了后端授权凭据。
- 前端 `autoConnect(projectRoot)` 在 Tauri 中优先读取本机租约，`ConnectScreen` 有独立的“本机实例”按钮；`appStore.projectRoot` 还包含开发者机器路径。
- 当前 HTTP Bearer 和 WebSocket 首帧认证已经满足统一认证协议，主要缺口在 token 生命周期、监听配置和发现链路。

## 预期用户流程

### 本地开发

`tinysoul init` 在项目数据目录生成 `.env` 和稳定 token。默认后端监听 `127.0.0.1:1430`。前端第一次填写：

```text
127.0.0.1:1430 + .env 中的 token
```

连接成功后前端保存目标。修改源码后重启后端，前端仍使用同一个目标自动重连。

### 远程主机部署

远程主机的数据目录有自己的 `.env`：

```dotenv
TINYSOUL_ENDPOINT__BIND_HOST=0.0.0.0
TINYSOUL_ENDPOINT__PORT=1430
TINYSOUL_ENDPOINT__TOKEN=该主机自己的稳定 token
```

笔记本前端填写：

```text
192.168.1.20:1430 + token
```

主机执行 `git pull` 后，`.env` 和 `runtime/` 保留；重启后端仍使用相同地址和 token。笔记本无需项目根目录、Tauri 租约文件或主机本地路径。

### 切换连接

前端 logout 顺序为：关闭事件流、取消前端重连定时器、清除连接 store、清除持久化 `{address, token}`、返回统一登录表单。登录另一台主机后保存新目标。后端不会因为前端 logout 停止 Agent 或取消 Turn。

## 实施范围与修改预览

### A. Endpoint 启动配置和校验

涉及：

- `tinysoul/gateway/endpoint/config.py`
- `tinysoul/gateway/cli.py`
- `tinysoul/agent/composition/builder.py`
- `tinysoul/assets/common/.env.example`
- `tinysoul/gateway/project/initializer.py`
- `tests/gateway/endpoint/`、`tests/gateway/test_cli.py`、项目初始化测试

改动内容：

- 在 Endpoint owner 内增加轻量的启动配置解析，明确只接受 `token`、`bind_host`、`port` 三个启动字段；`EndpointSettings` 继续承载 Host/Engine 的运行设置，避免把事件容量、journal 等内部参数暴露成部署协议。
- `bind_host` 默认 `127.0.0.1`，显式配置的 IPv4/IPv6 地址和 `0.0.0.0` 可用；保留 IP 校验，不接受无法确定监听语义的任意字符串。
- 部署配置端口默认 `1430`，范围为 `1..65535`；直接测试构造仍可使用 `0` 获取临时端口。
- token 必须是至少 32 字符的非空字符串；缺少或过短时抛出带配置来源的稳定配置错误。
- 将 `endpoint` 加入 Agent builder 的保留启动配置 section，使 `.env` 中的 `TINYSOUL_ENDPOINT__*` 不被 Agent 误认为未知业务 section；Endpoint parser 只由 CLI 在需要启动 HTTP 时调用。
- `tinysoul start --once` 不启动 Endpoint，不因缺少 Endpoint token 阻塞纯 CLI 单轮；交互式 `start` 必须完成 Endpoint 启动配置。
- 删除 CLI 的随机 token 生成，使用解析出的稳定配置构造 EndpointSettings，并在启动成功时输出实际绑定 host/port、协议版本和 token 来源（dotenv 或 process environment），不输出 token 内容。
- 新项目初始化时创建被 `.gitignore` 忽略的 `.env`，从 `.env.example` 保留注释和 provider 字段，并生成一次 `secrets.token_urlsafe(32)` 作为 Endpoint token。`reset` 保留已有 `.env`；没有 `.env` 时生成一份可运行的初始 `.env`。

预期效果：

```text
普通配置修改 / 后端重启 ──> address 和 token 不变
明确修改 endpoint token ──> 下次启动使用新 token，前端重新登录
缺少 token ──> 明确启动失败，而不是悄悄变成临时凭据
```

### B. 进程锁与旧租约发现清理

涉及：

- `tinysoul/gateway/project/instance.py`
- `tinysoul/gateway/endpoint/host.py`
- `tinysoul/gateway/endpoint/__init__.py`
- `tests/gateway/project/test_instance.py`
- `tests/gateway/test_cli.py`、`tests/gateway/test_cli_fake_provider.py`

改动内容：

- 保留 `ProjectInstanceLease` 的单项目进程锁、项目 identity 和 instance identity；这些仍然是后端生命周期职责。
- 删除 token-bearing 的租约 JSON 发布和读取职责，避免把稳定 bearer token 复制到本机发现文件；同步删除只服务该记录的 `record_path`、`publish` 和 `EndpointReady` 回调 API，清理无消费者的类型和测试。
- 保留实例 identity 在 `/v2/status`、事件认证和运行投影中的语义；它只表示当前 Endpoint 进程，不承担发现或授权。
- Tauri `discover_backend` 只读租约记录的 Rust 命令与相关结构在前端清理阶段删除；项目锁目录仍可继续存在，不再作为前端连接数据源。

预期效果：租约只防止同一项目重复启动，不再成为第二套连接协议或第二个凭据存储。

### C. 前端统一连接和登录状态

涉及：

- `visualization/src/app/connection.ts`
- `visualization/src/app/discovery.ts`
- `visualization/src/components/shell/ConnectScreen.tsx`
- `visualization/src/components/shell/AppShell.tsx`
- `visualization/src/components/shell/TopBar.tsx`
- `visualization/src/store/appStore.ts`
- `visualization/src/App.tsx`
- `visualization/src-tauri/src/lib.rs`
- 连接、shell、discovery 相关 Vitest 测试

改动内容：

- `ConnectTarget` 收敛为 `{ address, token }`；instance/project identity 只保留在连接握手返回的 `ConnectionInfo` 中，不进入持久化目标。
- `autoConnect()` 不再接收 `projectRoot`，浏览器和 Tauri 都只读取同一个 `tinysoul-web-connection` 本地存储。
- 删除 Tauri 本机租约发现、`isTauriShell()` 连接分支、`discoverLocalLease()`、Rust `discover_backend` 命令、`projectRoot` 状态以及硬编码开发者路径。
- `ConnectScreen` 只保留 address/token 表单，删除“Use the local instance”按钮；本机和远程输入完全相同。
- 保留成功连接后保存 `{address, token}` 的行为；新增明确的 `logout()`，清除持久化目标和当前连接。无需引入服务端 session 或多账户列表。
- `reconnectFromDiscovery()` 改名并收敛为复用最后成功目标；后端 instance_id 变化时仍重新读取 status 和 owner projection，但不访问本机文件。
- 顶栏增加 logout/切换连接入口，显示当前 Endpoint address；logout 不调用后端 shutdown/restart，也不取消后端 Turn。
- 保留 `parseEndpointAddress` 对 `IP:Port`、hostname、HTTP/HTTPS 和 WS/WSS 的统一处理；token 只放在 Authorization header 或 WebSocket 首帧，不进入 URL。

预期效果：

```text
同机 Tauri      ┐
同机浏览器      ├─> 填写 address + token ─> 保存 ─> 自动连接
远程笔记本      ┘
```

三种场景不再有“快速连接”“本机发现”“远程登录”三套不同语义。

### D. Endpoint 与项目使用文档

涉及：

- `docs/design/endpoint.md`
- `docs/endpoint/index.md`
- `docs/endpoint/frontend-integration.md`
- `visualization/docs/design/connection.md`
- `visualization/README.md`
- `tinysoul/assets/common/README.md`
- 根 `README.md`
- `visualization/docs/demand/README.md`
- `visualization/docs/demand/20261030-endpoint-stable-token-remote-bind.md`

改动内容：

- 将“Endpoint 是 loopback 本地协议”和“连接描述由 App 发布”改为当前事实：Endpoint 默认 loopback，但支持显式远程 bind；连接目标由用户输入/前端保存，租约不再是前端协议。
- 记录 HTTP Bearer、WebSocket 首帧 token、health/status 的认证边界，以及 instance_id 只是运行身份。
- 写出本地开发、远程主机、源码更新后的完整命令和 `.env` 示例。
- 说明 `.env` 是后端部署目录的本地配置，前端不读取；TOML/configs 由 Git 管理，runtime 数据不随源码更新覆盖。
- 说明固定端口、`0.0.0.0` 与实际前端连接 IP 的区别，以及 token 轮换和 logout 的实际语义。
- 需求文档在实现完成后更新为当前设计或移动到 `docs/analysis/done/`，避免继续描述随机 token、租约发现和可选随机端口。
- 同步 demand index 的 pending/owner 描述，避免索引继续暗示存在 `[endpoint]` TOML 或保留本机发现链路。

### E. 测试与验收

后端测试：

- Endpoint launch parser：默认值、固定端口、bind host、非 loopback、token 长度和缺失 token。
- ConfigEnvironment dotenv/process source precedence，确认 token 来源不泄露值。
- `init` 生成 `.env` 和稳定 token；重复 start/普通配置变更不会生成新 token；`reset` 保留 `.env`。
- CLI 将配置传给 Endpoint，启动输出只包含地址和 token 来源。
- HTTP/WS 认证和现有 Endpoint API 回归；状态与错误响应不回显 token。
- ProjectInstanceLease 只验证锁和 identity，不再验证租约 JSON 或 token 副本。

前端测试：

- storage round-trip 只保存 address/token；旧发现字段不再成为连接路径。
- browser/Tauri 使用相同 `autoConnect()`，不调用 `discover_backend`。
- `connect()` 成功后自动保存目标，`logout()` 清除目标并关闭 stream。
- logout 后可连接另一地址；自动重连复用最后成功目标。
- ConnectScreen 只渲染统一表单，App store 不再持有硬编码 project root。
- `pnpm build` 验证 Tauri/React/TypeScript 边界没有悬空引用。

运行验收：

1. `uv run --locked --extra dev python scripts/test.py tests/gateway tests/infra/config`。
2. `uv run --locked --extra dev python scripts/test.py --suite full`。
3. `uv run --locked --extra dev ty check`。
4. `cd visualization; pnpm test`。
5. `cd visualization; pnpm build`。
6. 使用临时项目验证 init → `.env` token → 本机 `127.0.0.1:1430` 登录 → 后端重启 → 前端自动重连。
7. 使用显式非 loopback bind 配置验证 Endpoint 可绑定并可用实际主机 IP 连接；不把当前机器网卡地址写入测试断言。
8. `git diff --check`，检查所有生成文件、文档、测试和计划范围。

## 不在本次范围

- 不实现主机自动 pull/restart 脚本。
- 不修改 `init`/`reset` 的运行数据归档语义；只增加稳定 Endpoint 配置的初始化与保留规则。
- 不增加服务端账户、密码哈希、session、token revoke、TLS、反向代理或企业安全治理。
- 不让 Endpoint 直接读写任意 `.env` 或提供修改监听器的 HTTP API。
- 不改变 Agent、Turn、Cycle、Context、Session、Memory、Workspace 和 Action 语义。
- 不为可编辑模型配置、Action catalog 或提示词增加逐项前端测试。

## 可行性核对

方案与现有代码边界相容：HTTP/WebSocket Bearer 已存在，`ConfigEnvironment` 已能读取项目 `.env` 和 process environment，Endpoint host 已经通过显式 `EndpointSettings` 绑定 socket，前端已经有 address/token transport、持久化和连接 epoch。主要工作是把随机生成、loopback 校验、自动端口和本机发现四个旧假设一次性收口。

实现风险集中在两处：一是初始化器当前只复制 `.env.example`，需要在 staging 结束前安全生成 `.env`；二是删除租约发布会同时影响 Python 测试、Tauri Rust 命令和前端 discovery，需要按后端协议先行、前端清理随后执行。两处都有明确 owner 和独立测试，不需要引入新的状态机或兼容层。

固定端口可能使同一台机器同时运行多个不同项目时发生端口冲突；启动应保留明确的 `EndpointServerError`，文档说明可以为不同项目配置不同固定端口。远程 bind 的实际可达地址取决于主机网络和防火墙，这不由 Endpoint 猜测或写入前端；测试只验证监听配置和协议，不硬编码本机网卡。

## 实施顺序

1. 先落地启动配置类型、`.env` 初始化和后端 Endpoint 校验；同步 `docs/endpoint` 协议说明。
2. 调整 CLI、固定端口、启动输出并验证本机 HTTP/WS 认证。
3. 移除 token-bearing 租约发布和 Tauri discovery 后端接口，保持项目锁。
4. 修改前端连接 owner、ConnectScreen、logout 和本地存储，删除硬编码 `projectRoot`。
5. 更新前端/根 README、设计文档和需求状态。
6. 运行聚焦测试、Fast/Full/typecheck、前端 test/build 和本机手工闭环。
7. 基于 `AGENTS.md` 逐项检查 owner、配置来源、凭据生命周期、测试范围、文档事实和未实现项；所有实现和验证完成后将本计划标为 done 并移入 `docs/analysis/done/`。

本计划不要求维护者再决定架构方向；`BIND_HOST`、稳定 token、固定端口、后端 `.env` 与前端独立保存目标均按已确认语义记录。若实施前希望保留租约 JSON 作为仅诊断用途，需要另行确认，因为它会重新形成第二个 token 存储位置。
