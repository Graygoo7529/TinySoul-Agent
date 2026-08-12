# Settings 配置页面实施记录

状态：`done`

## 目标

把旧的客户端设置弹窗改造成独立 Settings 页面，通过 Endpoint 查询和更新运行根目录内的 TOML 与 `.env`，并在空闲时完成持久化和当前 Runtime Generation 激活。

## 已完成

- `done`：补齐 `GET /v1/config`、`PATCH /v1/config` 的前端协议类型和客户端入口；
- `done`：建立非持久化 `configStore`，处理快照刷新、单字段写入、激活完成后的权威重读和实例隔离；
- `done`：建立 Overview、Models、Embedding、Capabilities、Memory、Workspace、Maintenance、Behavior、System、Credentials、Application 子页；
- `done`：以项目 TOML source value 驱动通用类型化控件，以 effective field 投影覆盖和只读语义；
- `done`：建立 `.env` 凭据列表、遮罩查看、新增、更新和删除交互；
- `done`：任意非 idle Runtime 活动期间完整展示配置并统一禁用修改；
- `done`：通过 Runtime activity 轮询状态和业务活动事件及时刷新统一只读状态；
- `done`：将 Settings 接入主导航，删除 `SettingsDialog` 和对应重复 UI 状态；
- `done`：收到配置激活 Observation 时只刷新 Endpoint 快照，不从事件建立配置状态；
- `done`：增加配置路径投影、凭据聚合和 PATCH 激活时序测试；
- `done`：同步 Settings 设计文档与前端架构总览。

## 验证

- 聚焦 Vitest：`src/features/settings/model.test.ts`、`src/store/configStore.test.ts`；
- TypeScript 与生产构建：`pnpm.cmd build`；
- 完整前端测试：`pnpm.cmd test`。
