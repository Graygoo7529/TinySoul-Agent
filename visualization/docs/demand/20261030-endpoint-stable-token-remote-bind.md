# 需求：Endpoint 稳定 token 与显式远程绑定（本机与 A/B 部署统一连接模型）

日期：2026-10-30 · 提出方：前端（visualization） · 状态：pending · owner：gateway/endpoint

## 理想设计

部署模型：主机 A 运行 TinySoul 后端与数据目录，电脑 B（Tauri 壳或浏览器）运行前端；开发机上前后端同机是同一模型的特例。

连接契约只有一个：**address + token**。

- 用户在任意前端输入一次 `ip:port + token` 并连接；
- 前端持久化该目标（现有 `tinysoul-web-connection` 机制），此后启动自动登录；
- 后端重启不改变 token 与端口，已存目标永久有效；
- 同机场景走同一条路径（`127.0.0.1:port + token`），不再需要前端读取本机租约文件。

统一之后，前端可以整体删除实例发现链路（`projectRoot`、`discover_backend` 命令、「本机实例」按钮），ConnectScreen 收敛为纯表单 + 自动登录。

## 现状（逐条事实）

- **token 每次启动随机生成**：`tinysoul/gateway/cli.py` 的 EndpointSettings 构造处硬编码 `token=token_urlsafe(32)`，没有配置入口；后端一重启，所有前端已存目标即失效，必须重新复制粘贴。
- **强制 loopback 绑定**：`tinysoul/gateway/endpoint/config.py` 的 `EndpointSettings.__post_init__` 校验 `Endpoint may only bind to loopback`，非 loopback 直接拒绝——B 机连 A 的真实 IP 在后端层面尚无通路。
- **端口默认自动分配**：`port: int = 0`，实际端口由系统分配并写进租约；没有固定端口的配置入口时，A/B 下用户无从得知地址。
- **实例租约**（`tinysoul/gateway/project/instance.py`）只服务同机 Tauri 壳的发现，文件名是项目根目录的哈希；它对 A/B 模型无意义（租约在 A 的文件系统上，B 读不到）。
- 前端现状：`appStore.projectRoot` 硬编码开发者机器路径且无任何设置入口（这是本次讨论的起因）。

## 需求

1. **endpoint 配置节**：按既有 `parse_section` 模式新增 `endpoint` 节（参考 agent 节），字段：
   - `token`：可选；配置则作为稳定 bearer token，缺省保持现状（每次启动随机生成）；
   - `host`：默认 `127.0.0.1`；**仅当配置显式出现时**才允许非 loopback 值，未配置时的校验行为与今天完全一致；
   - `port`：可选；缺省保持 0（自动分配）。
2. **校验语义不放宽默认面**：token 仍要求 ≥ 32 字符；非 loopback host 只在用户显式配置时成立，不静默放开。
3. **启动可见性**：启动输出中给出实际绑定地址与 token 来源（「配置」或「本次随机生成」），让部署者能直接把 `ip:port + token` 交给前端。
4. 租约发布与实例锁机制不变（同机发现仍可工作，直到前端删除它）。

## 前端侧配合

- 已完成分析：`projectRoot` 的唯一作用是推算同机租约文件名，不是连接契约的一部分；
- 本需求落地后，前端删除整个发现链路（`projectRoot` 状态与持久化、`discover_backend` Rust 命令、ConnectScreen「本机实例」按钮），ConnectScreen 只剩手动表单，启动时从已存目标自动登录；
- 落地前前端保留现有同机发现作为过渡（该过渡版的独立改进在排队中）。

## 为什么前端侧无法自行解决

token 生成、绑定地址与端口都在后端启动路径上；前端只能消费租约或手动目标，无法让 token 跨重启稳定，也无法让服务监听真实网卡。
