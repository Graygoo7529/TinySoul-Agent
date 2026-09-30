# Session Explorer Removal

状态：done

日期：2026-07-25

## 意图

前端应用回到两个真实用户表面：Chat 负责统一输入和 Agent 运行观测，Workspace 负责业务资源管理。已完成 prior Turn 的探索属于 Agent 的 Session 语义，不为前端审计需求建立第二套 REST、类型和页面状态。

## 完成内容

- 删除 Sidebar 的 History 入口和全局 `session` tab；
- 删除 `SessionView`、`useSessionExplorer`、reducer/test 与 Session 专用样式；
- 删除 `/v1/session/history|actions|trace` client 方法和 TypeScript 类型；
- status 类型移除无前端消费者的 `session_revision`；
- Chat 继续从 model Observation 展示真实 `llm.model.request` MessageStack，其中自然包含实际进入模型的 Session Background；
- Workspace、Maintenance、连接发现与事件 replay 保持原边界；
- 更新设计文档，并把 2026-07-24 Session Explorer 计划标记为历史方案。

## 验证

- `pnpm build` 通过；
- 前端源码不再引用 Session Explorer、Session REST 或 session tab；
- 后端 OpenAPI 不再包含 `/v1/session/*`。
