# Application Integration Next Stage Plan

Status: planned

## 意图

下一阶段不重建 TinySoul 的 Agent、Loop、Action、Context 或持久化模型，而是在已经完成的 CLI、Endpoint、Observation 和 Workspace 基础上，把桌面应用接入补完整。

应用集成设计语义：

1. `AppCommandGateway` 是 Terminal、Endpoint 和后续可信用户输入适配器的统一控制入口；
2. 前端和 cli 同时存在，都支持命令输入和信息呈现；前端后续可考虑嵌入 terminal 与 cli 同步运行；
3. 前端可允许执行 maintance 命令，以及在启动时收到 maintance 提醒


## Stage 1：统一 Maintenance 请求与工作状态

这是下一阶段最明确、优先级最高的工作。


## Stage 2：能力扩展

以下方向从已关闭的 capability expansion 计划提取，但尚未获得足够真实场景，不能直接进入实现；后续进一步设计与确认

### Deterministic Utilities
数学等实用工具

### Home Backlink
查询 home、memory 中文档的前向、反向链接

### Memory 语义检索
memory 语义检索优化

### Knowledge
卢卡曼式笔记盒，运行将 workspace 中重要知识写入知识库，维护知识网络

### home 文档优化
强化对于 skill、knowledge 维护倾向，主动利用和维护记忆、知识；迁移 openclaw home 文档；同步 wheel 初始化文档与项目内文档


## Stage 3：codex 研习
参考 codex 源代码进一步优化现有系统
