# Agent 重构 R3 收口：执行所有权与资源提交

状态：`done`（C1–C5 实现、文档、必要验证与主计划范围已逐项核对）。
建立与完成日期：2026-09-19。
依据：[主执行计划](../20260915-agent-architecture-refactor-plan.md)、[R3 领域重构记录](20260917-done-Agent重构第三轮子计划-领域语义与能力组织.md)。复审基线为 `160781e`。用户已授权分析、设计并实施收口，允许小幅同步主计划的过时表述。

## 1. 目标与边界

关闭复审已复现的四项缺口：父进程退出后后代逃逸、Workspace 移动/恢复在索引失败后丢失人工元数据、大小写路径别名绕过批次目标检查、嵌套失败漏报删除副作用。沿用 `plugins/execution + kernel/jobs + infra/process` 以及 Workspace 单 owner，不新增运行状态机、CAS、多文件事务或模型侧恢复协议。

主计划 S1/S2 保持完成，S3 的 organize/模型推导注释与 S4–S7 保持原范围。原 R3 归档记录保存当时实施与门禁结果，本计划补充其复审缺口和关闭证据。

## 2. 设计

### 2.1 完整受控执行单元

`infra/process` 拥有主进程及其受控后代。Windows 使用系统 Job Object，挂起创建、加入集合后才恢复执行；不依靠父 PID 存活后的临时枚举杀树。POSIX 使用启动时创建的进程组，根进程已退出也对该组执行停止。平台差异封装在 infra，Action 与 Job 继续共用 ManagedProcess。

主进程自然结束的退出码仍决定执行结果，结束后的后代由收尾回收；关闭整个执行单元后才允许 JobRegistry 确认 execution_closed。必要停止失败保持句柄可重试，并沿既有 Jobs bridge 处理；输出句柄等附属清理失败仍只产生诊断。这里的系统 Job Object 是 OS 资源容器，不是第二个业务 Job 状态 owner。

### 2.2 Workspace 元数据随资源迁移

移动与恢复共用一个 owner 内部的迁移步骤：同一锁内把目标及子项元数据合入现有 manifest，保留源记录；原子移动磁盘内容；普通 reconcile 按实际存在的内容刷新索引。源和目标均不依赖另一份长期元数据存储。

保存目标元数据失败时不移动内容；移动失败或进程中断时，源元数据及内容仍可解释；移动成功后索引失败时，目标元数据已持久保存，重新打开 owner 后的普通扫描即可恢复正确投影。成功操作才发布变更，失败准确保留已经发生的内容变化。不提供多文件回滚承诺，不增加 marker、事务 journal、恢复 Trap 或模型需要感知的内部字段。

### 2.3 身份与提交事实

批量写入和删除统一在 owner 解析后的 Path 上检查目标唯一性、交叉冲突与父子关系，结果也按同一资源身份匹配。Windows 的大小写等价路径不能被当作两个独立目标；合法覆盖保留磁盘规范身份。

模块异常重新包装时合并内层 committed_links 与外层已经完成的操作，按稳定顺序去重。bridge 与 SDK/Endpoint 沿用当前有限、类型化的失败协议；不暴露底层异常文本，不伪造回滚。

## 3. 执行与验收

| 条目 | 状态 | 验收 |
|---|---|---|
| C1 进程集合所有权 | done | `infra/process/managed.py` 的 ProcessScope 与 `windows.py` 原生集合；真实后代自然结束/取消、启动接管失败、根已退出时的停止失败重试、Job 终态与跨午夜归档全部进入最终 Full |
| C2 Workspace 迁移提交 | done | `storage/mutations.py::_relocate` 统一移动/恢复；去掉 reconcile 的临时 metadata 参数，元数据/移动/索引失败后的目录子项与重开恢复通过 |
| C3 路径和失败事实 | done | write_bundle 与 reconcile 按解析路径匹配；大小写目标、写删冲突、合法覆盖与嵌套提交事实通过；既有 bridge/SDK/Endpoint 继续传播同一失败协议 |
| C4 文档与规约核对 | done | AGENTS 补入统一抽象与模型信息边界原则；Workspace/Execution/Infra 设计同步；主计划仅调整 execution 目录、catalog 来源、Reflection 旧表述及完成证据 |
| C5 本地门禁与归档 | done | Fast、Full、typecheck 与差异检查通过；范围及验证限制见下文，本文件加 done 标记并归档 |

测试以 owner 契约完整覆盖为主，跨模块仅验证真实 Job/Turn/日切代表路径。进程用真实子进程，存储用必要的提交故障注入，不固化保存次数或私有布局。没有新增业务语义待确认；若平台约束或实现发现与上述边界冲突，先讨论再改变设计。

## 4. 实施核对与验证记录

按 AGENTS 的所有权、数据流、失败、生命周期及简约接口要求核对：

- 业务 Job 状态仍只由 JobRegistry 维护。ProcessScope 仅抽象系统执行单元的停止与句柄关闭，由 Windows 集合与 POSIX 组实现，消费者为已有 ManagedProcess；没有新增调度器、事件流或业务状态副本。
- 正常结束保留根退出码；必要停止失败保持执行未关闭并可重试；附属资源失败仍为有界诊断。原始系统错误只留异常链，模型与 Runtime 不接收原始路径或异常文本。
- Workspace 仍以磁盘为内容事实、单一 manifest 为索引和人工元数据 owner；移动/恢复使用同一迁移步骤，已提交部分沿现有 committed_links 传播。没有 CAS、源版本复验、新存储格式、迁移脚本或模型侧协议字段。
- Action、SDK、Endpoint 和 Context 的既有门面及依赖方向保持成立。本次没有协议参数变化，无需增加 Endpoint 接口文档；没有改动 visualization、部署数据或运行 reset。
- 主计划 S1/S2 保持 done；S3 的 organize/模型推导注释仍为后续设计，S4–S7 不扩大完成范围。原 R3 记录增加收口关联，不改写历史验收结果。

2026-09-19，使用 Conda TinySoul 的 Python，经 TINYSOUL_PYTHON 显式选择：

| 验证 | 结果与范围 |
|---|---|
| 聚焦 | Workspace 80 passed、Infra process 12 passed；跨午夜 SDK 聚焦通过。之后新增的根已退出而后代停止失败分支纳入最终 Full |
| Fast | 1075 passed、28 deselected；运行目录 `.local-test/runs/5c2b93d359904bc0823ef5cbf0a2864f` |
| Full | **1081 passed、23 deselected**，包含项目生成、wheel 安装与 worker；运行目录 `.local-test/runs/5d9dc99f75304769ad642c1818c7162f` |
| typecheck | `scripts/typecheck.ps1` 全仓通过；进程模块另以 `ty --python-platform linux` 检查通过 |
| 差异与架构 | `git diff --check` 通过；依赖方向、公共入口与新进程导入路径纳入 Full |

第一次 Fast 的新增 SDK 测试子进程继承了主进程交互 stdin，导致测试等待；该后台子进程明确不消费输入，改用 DEVNULL 后聚焦、Fast 和 Full 均通过。进程终止的 socket 验证同时接受 EOF 与 Windows 强制关闭的 reset，不接受超时。现有 Starlette/httpx 弃用提示不影响验证结果。

验证边界：真实进程测试在 Windows 完成；当前没有可用 Linux 运行环境，POSIX 完成源码核对与目标类型检查，未宣称实机通过。POSIX 主动脱离 session/group 不属于进程组所有权保证。真实 provider/network 23 项按 Full 语义排除，未运行。没有提交 Git 或改变实际部署。
