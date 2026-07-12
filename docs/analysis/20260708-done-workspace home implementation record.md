# 20260708-done Workspace / Agent Home implementation record

## 状态

status: done

本文由原 `20260708 workspace home implementation plan.md` 拆分而来，记录截至 2026-07-12 已经落地的设计与实现事实。原计划中尚未完成的 Agent Home 检索与写入、Memory/HOW feedback、Workspace 日终归档和每日沉淀，已迁移到 `20260712 agent home daily lifecycle followup plan.md`，不在本文中以完成状态保留。

本文的 `done` 表示下列记录项均可在当前代码、设计文档和测试中找到对应实现，不表示 Workspace 与 Agent Home 的全部目标已经完成。

## 稳定设计边界

- Workspace 是 `workspace:` 链接、当日工作资源、Manifest、Trash 和资源正文访问的唯一语义归属方。
- Agent Home 是 `home:` 链接、顶层背景、渐进资源、HOW prompt mount 和 runtime home 副本的唯一语义归属方。
- Context 只维护语境状态并构造 MessageStack，不直接读取 Workspace 或 Agent Home 文件。
- Workspace 正文和图片只在具体 action 内部成为临时 Prompt 输入，不进入 WorkingContext，也不作为普通 ActionResult 长期写入 TurnTraceHeap。
- Workspace 编辑目标使用 `target_link`，只读参考使用 `reference_links`；Phase2/Phase3 边界不传递文件正文。
- 原始 Agent Home 在普通 User Turn 中只读；进入运行期的内容从 `runtime/home` 副本读取。
- `how_domain` 和 `how_action` 是局部自动 Prompt mount，不属于普通 Background，也不暴露为渐进式 resource read。
- AppBuilder 只完成模块构建、registrar 注册和依赖注入，不拥有 Workspace/Home 业务逻辑。

## 已完成实施

### 1. Workspace 正文切片与临时输入

status: done

`WorkspaceTextSlice` 已成为 Workspace 文本临时输入的稳定表达，能够携带来源链接、范围、截断状态、大小和 digest。`WorkspaceEngine.read_text_slice` 支持按 1-based 行号读取局部文本，`prepare_task_input` 支持有界前缀读取，`WorkspacePromptInput` 只负责把这些切片渲染为 action 内部临时输入。

该能力没有新增模型可见的 `workspace.read` action。模型通过具体 action 的 `target_link` / `reference_links` 使用资源，正文不会因为一次通用读取而自动进入 Context。

实现位置：

- `tinysoul/infra/filesystem.py`：有界前缀和行范围读取；
- `tinysoul/workspace/engine.py`：`WorkspaceTextSlice`、`WorkspacePromptInput` 和类型化读取；
- `tinysoul/workspace/prompts.py`：Workspace slice 到 `PromptBlock` 的转换；
- `tests/workspace/test_workspace_engine.py`：前缀、行范围、截断、digest 和边界测试。

### 2. Workspace 写入、rewrite、patch 与逻辑删除

status: done

当前已实现：

- `workspace.write`：通过 action-internal LLM task 生成完整 UTF-8 文本，支持创建、显式覆盖、只读参考、retention 和 `expected_digest`；
- `workspace.rewrite`：读取目标与参考资源，在 action 内生成完整替换文本；
- `workspace.patch`：执行确定性的精确单点替换，要求 `old_text` 非空且只出现一次；
- `workspace.delete`：把资源移出 active Workspace 并放入可恢复 Trash；
- `workspace.trash.list`：列出可恢复项及其 Trash ref；
- `workspace.restore`：显式恢复逻辑删除或压力暂存资源。

成功结果只返回 link、summary、kind、size、mtime、digest、retention、trash ref 等元数据，不返回正文。参数错误、链接错误、文件冲突、patch 不适用和普通 I/O 失败优先收敛为局部 `ActionResult`；Runtime 控制异常保持穿透。

实现位置：

- `tinysoul/workspace/engine.py`：原子写入、patch、Trash/restore、回滚和 reconciliation；
- `tinysoul/workspace/actions.py`：Workspace action executor 和 Context snapshot signal；
- `tinysoul/workspace/trash.py`：prepare/move/commit 与未完成移动恢复；
- `tinysoul/action/catalog/workspace/actions/`：模型可见 action 定义；
- `tests/workspace/test_workspace_engine.py`：文件副作用、回滚、Trash、signal 和局部失败测试。

### 3. PromptBlock 与 llm_action 接入

status: done

`LLMActionTaskRunner` 已成为 action-internal LLM task 的共享服务，集中处理 Context MessageStack 构造、domain/action HOW 注入、`llm_action` profile 调用、JSON object 输出约束和局部失败归一化。

`core.reason` 与 `core.answer` 使用 PromptBlock-only `TaskPrompt`；通用 action 只接受 `reference_links`。`WorkspacePromptReferenceResolver` 按资源类型把 Workspace 链接解析为只读或目标 block，Workspace 编辑 executor 再负责文件读写和 Manifest 提交。

实现位置：

- `tinysoul/action/backends/llm_action.py`：共享嵌套 LLM task；
- `tinysoul/action/builtins/core/actions.py`：`core.reason` / `core.answer`；
- `tinysoul/workspace/prompts.py`：Workspace reference/target prompt 构造；
- `tinysoul/workspace/actions.py`：Workspace LLM action 业务语义；
- `tests/action/test_llm_action.py`、`tests/workspace/test_workspace_engine.py`、`tests/home/test_home_engine.py`：PromptBlock、引用解析和 HOW 注入测试。

### 4. Action timeout、Runtime transfer 与 Workspace 写入 guard

status: done

Action timeout result 已具有稳定 frame payload：`reason`、`cancel_requested`、`executor_started`、`executor_leaked` 和 `late_success`。并行 worker 在正常收取或 timeout grace 期间发现 `RuntimeException` / `RuntimeTransferInterrupt` 时，会立即请求取消 sibling，并原样传播原控制异常。

Workspace LLM 写入在构造 Prompt 时记录目标 digest，并在最终 Engine 写入边界校验显式 `expected_digest` 或观察 digest。Engine 使用操作前实际字节作为乐观前置条件；内容提交后 reconciliation 失败时尝试回滚。该语义是 Engine 实例内线性化和单进程单写者，不宣称跨进程 CAS。

实现位置：

- `tinysoul/action/core/runner.py`：deadline、cancel grace、transfer 传播和 sibling 清理；
- `tinysoul/workspace/engine.py`：实际字节 digest guard、原子替换和回滚；
- `tinysoul/workspace/prompts.py`、`actions.py`：观察 digest 的传递；
- `tests/action/test_hooks_runner.py`、`tests/workspace/test_workspace_engine.py`：竞态和写入前置条件测试。

### 5. Workspace Manifest、资源类型与一致性

status: done

Workspace 已完成以下基础闭环：

- 磁盘作为内容事实源，Manifest 作为版本化索引和语义描述层；
- `WorkspaceReconciler` 独立执行发现、完整性检查、候选状态复核和原子 Manifest 提交；
- text、image、document、binary 四类稳定资源分类；
- image 内容签名校验、单文件预算和 Context 总图片预算；
- description 通过 `described_digest` 绑定实际内容，内容变化后自动失效；
- reconciliation incomplete 时保留旧 Manifest，不发布权威 Context snapshot；
- Turn preparation 在首个 Cycle 前投影完整 Manifest；
- Workspace 变更成功后发布同 revision 的 `context.workspace.sync` 全量快照；
- Context pressure 只暂存未被活动 target/reference links 保护的 ephemeral/turn 资源，并在失败时回滚；
- active miss 可以通过确定的 Trash ref 进入恢复 Trap，恢复、同步 Context 后重试当前 Module。

明确一致性等级为：单进程、单写者、同一 `WorkspaceEngine` 实例内的公开操作按 `RLock` 获取顺序线性化。外部 writer、跨进程锁和跨数据文件/Manifest 的文件系统事务不在保证范围内。

实现位置：

- `tinysoul/workspace/manifest.py`、`reconcile.py`、`resources.py`；
- `tinysoul/workspace/projection.py`、`pressure.py`；
- `tinysoul/loop/pressure.py`、`trap_handlers.py`；
- `docs/design/workspace.md`；
- `tests/workspace/test_workspace_engine.py`、`tests/loop/test_pressure.py`、`tests/loop/test_trap_handlers.py`。

### 6. Agent Home 只读运行平面

status: done

原计划第 3 阶段中的检索与写入并未完成，但其只读和副本恢复前置能力已经落地，单独记录如下：

- `HomeTopLink`、`HomeResourceLink`、`HomePromptMountLink` 明确区分顶层背景、渐进资源和局部 HOW mount；
- `AgentHomeLayout` 统一解释 original/runtime 路径映射；
- `home:agent@core` 严格映射 `home/agent/AGENT.md`，项目根 `AGENT.md` 不参与运行时 Home；
- 默认 core 在启动 recovery 中物化，其它顶层背景在 Context Module frame 内按需读取；
- domain HOW 注入 Phase2，domain/action HOW 注入 action-internal LLM task；
- `home.resource.read` 有界读取渐进资源，并把普通参数/文件失败收敛为局部 ActionResult；
- runtime 副本使用同目录临时文件、flush/fsync 和原子 replace；
- 同一目标由进程内锁串行化，已物化副本消失或变为非普通文件时不会从 original 静默覆盖；
- runtime copy 缺页进入 `HOME_RUNTIME_COPY_REQUIRED` Trap，成功后重试当前 Module；启动 recovery 对同一链接只处理一次，防止无限重试。

实现位置：

- `tinysoul/home/links.py`、`layout.py`、`engine.py`；
- `tinysoul/home/runtime_copy.py`、`background.py`、`guidance.py`；
- `tinysoul/home/actions.py` 与 `tinysoul/action/catalog/home/`；
- `tinysoul/runtime/bridge/home.py`、`tinysoul/app/builder.py`；
- `tests/home/test_home_engine.py`。

### 7. 支撑上述能力的横切基础

status: done

在原计划实施期间，以下横切能力也已完成，并成为后续 Home/日终工作的稳定前置条件：

- 配置 main/include/env/override 来源诊断，各模块拒绝未知配置键；
- LLM provider 显式区分 endpoint identity、adapter 和 enabled，代理 provider 可独立持有凭据并提供模型；
- LLM 暂时性、永久性、能力缺失、Runtime 和未知异常采用不同模型链处置；
- Session 采用不可变 Turn record、幂等提交、确定性 summary、orphan reconciliation 和跨日归档前恢复；
- `ObservationEvent` / `OutputSink` 提供 normal、verbose、model 三档输出；
- `tinysoul` console script、终端 InputSource 和 `--once` 入口已接入同一 App/Program 主链；
- ProgramOutcome 对保留的 TurnOutcome 数量有界。

对应设计见 `docs/design/infra.md`、`llm.md`、`session.md`、`runtime.md` 和 `app.md`。

## 未纳入完成范围

以下能力没有在本文中标记为 done：

- Agent Home effective overlay manifest、runtime-only 资源和 tombstone；
- `home.top.search` 及语义 top-k；
- `home.resource.write` / `home.resource.patch`；
- `home.memory.append`、HOW 使用事实和 feedback；
- runtime Home 的日标识、归档、diff、合并计划和冲突处理；
- Workspace 日标识和日终归档；
- Program 同级 Daily Turn/maintenance 调度；
- 文档资源转换 action；
- 面向真实任务的 shell/script/capability action；
- 独立安装后的默认项目资产与初始化流程。

这些条目统一进入后续计划，避免把基础机制完成误写成业务闭环完成。

## 验证基线

当前实现的验证入口为：

```powershell
python -m pytest tests -q
$env:TINYSOUL_PYTHON='当前设备的 TinySoul python.exe'; .\scripts\typecheck.ps1
tinysoul --help
```

拆分文档时的实现基线为提交 `492fe06 feat(app.etc): harden provider, recovery, and output flows`。完整验证结果应以当前工作树重新运行后的结果为准。
