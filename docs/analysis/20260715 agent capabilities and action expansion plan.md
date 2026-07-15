# 20260715 Agent Capabilities And Action Expansion Plan

## 状态

status: pending

依赖：Stage 8 发布与初始化闭环、默认 Agent Home 内容实施完成。

## 目标

基于现有 Action backend mechanism 扩充真实、可维护的 Agent 能力。该计划不以保留 domain 或展示 backend 为目标；只有具备明确用户价值、输入输出协议和安全边界的 action 才进入内置 Catalog。

## 组织边界

1. 具有独立链接、持久化或 runtime/trap 生命周期的能力才建立顶层业务模块；
2. 无独立持久状态的轻量能力放在 `tinysoul/capabilities/<capability>/`，由能力包的 service/client/evaluator 承担业务逻辑，由 `actions.py` 提供 ActionEngine registrar/executor 适配；
3. 通用执行机制继续位于 `tinysoul.action.backends`；capability 不重复实现 subprocess、temporary script、LLM task 或 ActionResult 管线；
4. Catalog 只描述真实 domain/action，空 domain、预留 action、未注册 handler 和通用“执行任意模型脚本”均禁止；
5. 需要硬停止的外部工作使用受控 subprocess/script backend；native 仅承载可协作取消且受信任的进程内逻辑。

## 候选能力

实施前逐项确认真实工作流、依赖和安全策略，候选顺序为：

1. document conversion：在 Workspace Link 边界内把受支持文档转换为可检查的 Markdown/文本资源，明确格式、大小、超时、临时文件与失败结果；
2. web/search：通过明确 client 接口返回有界来源摘要和链接，不把 HTTP/JSON 细节泄漏到 action executor；
3. deterministic utility：数学、时间或格式转换等能以明确 schema 和纯结果表达的能力；
4. 受控项目命令：仅在白名单工作流确有需要时建立，不提供任意 shell 字符串接口。

## 每项能力的实施门槛

- 真实用户场景、domain 归属、`use_when`/`avoid_when` 与 effects 已确认；
- 参数 schema 不以自由字符串绕过路径、命令或网络边界；
- 正常失败映射为局部 ActionResult，配置/环境/不变量失败保持模块边界异常；
- 文本、文件、网络响应、运行时长和并发均有明确上限；
- registrar、Catalog handler、executor 和业务 service 的所有权一致；
- 有模块测试、Phase2/Phase3 集成测试和至少一个 App 工作流验收。

## 待确认

开始实施前需与维护者确认：

1. 首个 document conversion 的输入格式、输出格式、第三方依赖和是否允许 OCR；
2. 外部网络能力的供应商、凭据配置、来源引用与缓存策略；
3. 项目命令能力是否需要，以及允许的命令集合和工作目录边界；
4. 新能力是否需要对应通用 HOW、domain HOW 或 action HOW。
