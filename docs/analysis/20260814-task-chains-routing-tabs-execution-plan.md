# Task Chains Routing Tabs Execution Plan

状态：`done`

## 背景与目标

Cycle Routing 和 Action Routing 都是 task chain 的使用关系，不应与 Providers、Models、Task Chains 一起作为三个平级的 Models & Routing 页面。当前实现将它们放在侧边栏，导致同一条配置链路被拆散；同时未被引用的 task chain 被标记为 `Unbound`，把合法的闲置定义误显示为异常状态。

本轮只调整 Visualization 的信息架构和投影，不改变后端配置、endpoint、Infra catalog 或路由语义。

## 确定的设计语义

- 侧边栏只保留 `Task Chains`；`Cycle Routing` 与 `Action Routing` 成为 Task Chains 页面内部的标签页。
- catalog 继续保留 `task_chains`、`cycle_routing`、`action_routing` 三个 surface。它们是字段所有权和描述来源，不再等同于侧边栏页面。
- Task Chains 标签页编辑 task profile 定义；Cycle Routing 标签页编辑共享 Phase1/Phase2 task profile 引用；Action Routing 标签页编辑默认链、Action overrides 和高级超时。
- Task Chain 列表的使用摘要分别投影 Cycle Phase、Action 默认链和 Action override 数量。没有任何引用时只显示模型数量，不显示 `Unbound`。
- 同一条 chain 可以同时显示多个使用关系，例如 `Phase1 · Action default · 2 Action overrides`。
- 保存、运行时只读状态、generation 刷新和所有配置说明继续复用现有组件、endpoint 和 Infra catalog。

## 实施步骤

1. 从侧边设置导航和页面分派中移除独立 routing 页面。
2. 在 Task Chains 页面增加 Chains、Cycle Routing、Action Routing 三个内部标签。
3. 将 Action Routing 页面作为嵌入面板复用，并用通用配置面板渲染 Cycle Routing。
4. 在 settings model 中增加统一 task-chain usage 投影，修正组合绑定和无绑定摘要。
5. 增加投影与页面回归测试，运行 TypeScript、settings 测试和前端完整门禁。

## 实施核对

- [x] 侧边栏不再显示独立 Cycle/Action Routing。
- [x] Task Chains 内部三个标签可切换并复用现有配置编辑流程。
- [x] usage 投影正确区分 Phase、Action 默认和具体 override。
- [x] 未绑定 chain 不显示 `Unbound`。
- [x] Visualization 设置设计文档与测试已同步，TypeScript 类型检查与完整 95 项前端测试通过。

默认 fork 模式的 `npm run test` 中 78 项测试通过，但部分 worker 因本机 `node_modules/.pnpm` 下 `punycode.js` 的 `EPERM` 未启动；使用单线程 threads pool 重跑后，17 个文件、95 项测试全部通过。`npm run build` 的 TypeScript 阶段通过，Vite 仍因 KaTeX 字体文件的同类 `EPERM` 中止，属于现有依赖目录访问权限问题。
