# 需求：Endpoint 稳定 token 与显式远程绑定（本机与 A/B 部署统一连接模型）

日期：2026-10-30 · 提出方：前端（visualization） · 状态：implemented · owner：gateway/endpoint

实现与验证见 `docs/analysis/20261101-endpoint-stable-auth-unified-connection-execution-plan.md`。

## 理想设计

部署模型：主机 A 运行 TinySoul 后端与数据目录，电脑 B（Tauri 壳或浏览器）运行前端；开发机上前后端同机是同一模型的特例。

连接契约只有一个：**address + token**。

- 用户在任意前端输入一次 `ip:port + token` 并连接；
- 前端持久化该目标（现有 `tinysoul-web-connection` 机制），此后启动自动登录；
- 后端重启不改变 token 与端口，已存目标永久有效；
- 同机场景走同一条路径（`127.0.0.1:port + token`），不再需要前端读取本机租约文件。

实现后前端已整体删除实例发现链路（`projectRoot`、`discover_backend` 命令、「本机实例」按钮），ConnectScreen 收敛为纯表单 + 自动登录。

## 实施前现状（历史记录）

- **token 每次启动随机生成**：已改为 `init` 生成项目 `.auth`，普通启动只读取该文件；后端重启不会改变 token。
- **强制 loopback 绑定**：已改为 `.env` 的 `TINYSOUL_ENDPOINT__BIND_HOST` 显式接受 IP 地址，包括受信主机的非 loopback bind。
- **端口默认自动分配**：已改为部署默认固定端口 1430；底层测试可显式使用 `port=0`。
- **实例租约**（`tinysoul/gateway/project/instance.py`）只服务同机 Tauri 壳的发现，文件名是项目根目录的哈希；它对 A/B 模型无意义（租约在 A 的文件系统上，B 读不到）。
- 前端现状：`appStore.projectRoot` 硬编码开发者机器路径且无任何设置入口（这是本次讨论的起因）。

## 需求

1. **endpoint 配置节**：按既有 `parse_section` 模式读取 `.env` 中的 `TINYSOUL_ENDPOINT__BIND_HOST` 和 `TINYSOUL_ENDPOINT__PORT`；默认值为 `127.0.0.1:1430`。
2. **稳定凭据**：`init` 生成项目 `.auth`，普通 `start` 必须读取其中唯一的 `token=` 项并校验长度；不提供环境变量覆盖，缺失或无效时启动失败。
3. **校验语义**：bind host 必须是 IP 地址，显式允许非 loopback；生产端口为 1..65535，底层测试可以显式传 `port=0`。
4. **启动可见性**：启动输出中给出实际绑定地址与 `.auth` token 来源，不输出 token 内容，让部署者能直接把 `ip:port + token` 交给前端。
4. 进程锁和运行身份仍保留，但不再发布 token-bearing 租约；前端不再使用本机发现。

## 前端侧配合

- 已完成分析：`projectRoot` 的唯一作用是推算同机租约文件名，不是连接契约的一部分；
- 本需求已删除整个发现链路（`projectRoot` 状态与持久化、`discover_backend` Rust 命令、ConnectScreen「本机实例」按钮），ConnectScreen 只剩手动表单，启动时从已存目标自动登录；
- 前端已移除同机发现过渡链路，浏览器和 Tauri 统一使用手动 address + token 登录。

## 为什么前端侧无法自行解决

token 生成、绑定地址与端口都在后端启动路径上；前端只能消费租约或手动目标，无法让 token 跨重启稳定，也无法让服务监听真实网卡。
