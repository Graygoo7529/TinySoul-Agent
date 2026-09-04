# 测试权限、稳定性与冗余收敛执行计划

## 状态

- 文档状态：`in_progress`
- 权限问题诊断：`done`
- 前端依赖环境修复：`in_progress`
- 后端完整门禁与类型检查：`done`
- 后端项目初始化夹具收敛：`done`
- 进程等待稳定化：`done`
- 测试分层与冗余测试削减：`done`
- 完整验证与计划核对：`in_progress`

本计划用于指导并核对实施。测试代码改造和后端完整门禁已经按下述记录完成；前端干净依赖安装仍有明确环境阻断，因此文档继续保持 `in_progress`，只有全部退出条件满足后才更新为 `done`。

## 实施记录（2026-09-03）

已完成的测试代码改造：

1. 新增 `tests/support/project.py`，按 standard/development profile 在单次 pytest run root 中各初始化一次模板，并为每个用例复制独立项目。App builder/runtime、Home、LLM、infra、action catalog、supervised process policy、shell 以及 resetter/lease 的准备步骤已迁移；CLI init、initializer 本身和 wheel 安装验收仍直接验证生产初始化路径。
2. 新增 `tests/support/process.py`。只用于保持子进程存活的 30 秒 sleep 已替换为由被测生命周期显式终止的事件等待；脚本 wait 测试用线程事件和有界 `wait_until` 替换 `.1/.2` 秒固定调度等待。
3. App builder 的 9 个同构启动失败测试已参数化，保留所有模块 owner、错误 key 和 capability failure kind；缺失 Home、损坏 manifest、编程错误透传以及 App/LLM 特殊装配继续独立验证。Generation 用例从 Fast 分离后，Fast 执行 942 项，没有为了降低数字删除有意义案例；削减的是重复测试代码、重复初始化和无意义等待。
4. 端点配置激活测试的 WebSocket heartbeat 从生产默认 15 秒调整为测试值 0.05 秒，并按协议跳过合法 heartbeat、读取事件页。该文件由约 27.8 秒降至约 11.4 秒，其中原 15.7 秒用例降至约 0.6 秒。
5. 测试按业务逻辑与生成级契约分层：`pyproject.toml` 声明 `generation` marker，`scripts/test.ps1 -Suite Generation` 选择初始化器契约与 wheel release；Fast 排除 `generation`/`release`，Full 仍包含全部非 external 测试。初始化器直接调用只保留 4 个生成契约用例，reset、CLI 启动、Provider 和能力测试均复用不可变模板。
6. 未新增 Vitest worker 配置：依赖文件仍可直接复现 `EPERM`，worker 限制会掩盖环境问题。应在干净依赖安装完成后再依据实际并发数据决定是否需要配置。

验证结果：

- 实施前 Fast：945 passed、1 failed、2 skipped、22 deselected，75.36 秒；失败为 initializer `staging.replace` 的 `WinError 5`。
- 实施后 Fast：942 passed、2 skipped、26 deselected，50.45 秒；相对原始基线减少 24.91 秒，约 33%。其中 4 个生成契约移入 Generation，不属于业务逻辑删除。
- Python typecheck：通过。
- 生成级定向套件：5 passed（4 个 ProjectInitializer/CLI init 契约，1 个 wheel release 契约），11.10 秒；唯一较重项是 wheel 隔离安装，7.11 秒。
- 前端 Vitest：21 files、127 tests 全部通过，3.17 秒。
- 前端 TypeScript：通过（使用 `.\node_modules\.bin\tsc.CMD --noEmit`；当前 Windows shell 中 `pnpm exec tsc` 未正确解析可执行文件）。
- 前端 build：通过，Vite 构建 2597 个模块。
- Full 已完成 5 次连续通过（每次 947 passed、2 skipped、21 deselected，耗时分别为 58.83、61.17、60.57、59.51、61.54 秒），未再复现 `WinError 5`。

前端干净安装已按方案尝试：原 `node_modules` 先移动到 `B:\tmp` 可恢复备份，新 store 安装因沙箱访问 npm registry 返回 `EACCES`；受控权限请求又因审批服务 502 被拒绝。半安装目录已移到 `B:\tmp\TinySoul-Agent-node_modules-failed-install-20260903`，原依赖目录已完整恢复，仓库未留下依赖或锁文件修改。恢复后 test/build 可运行，但 Node 和 PowerShell 直接读取已知 `punycode.js`/KaTeX 字体仍返回 `EPERM`，所以环境修复不能标记完成。

后端连续 Full 已通过，之前的失败证据仍说明 Windows 外部句柄/扫描器竞争是可能的环境风险，但当前不构成可重复的生产缺陷。测试侧不增加重试或 skip；生产原子替换不作未经证据支持的改动，继续保留真实 release/初始化契约作为监测点。

## 背景与现状

本计划遵循仓库 `AGENTS.md` 的整体设计要求：测试应验证公开行为、模块所有权和异常边界，而不是堆积历史假设；异常处理必须保留三层语义（局部结果、模块边界、Runtime 对外错误）；不得通过宽泛 `except`、静默重试、测试专用兼容状态或第二套状态机掩盖问题。

已完成的现状核对如下：

1. 前端全量 Vitest 能通过 14 个测试文件、99 个测试，但有 7 个 worker 启动错误。错误集中在 `visualization/node_modules` 中读取 `punycode.js` 时的 `EPERM`；构建在解析 KaTeX 字体 `KaTeX_AMS-Regular.woff2` 时同样失败。TypeScript 检查和单独运行 `src/derive/chat.test.ts`（29 项）通过。
2. 前端受影响文件不属于源码，包目录的继承 ACL 看起来正常，但单文件读取、`Get-Acl`、`icacls` 和硬链接查询均被拒绝；同一依赖目录中的其他 TypeScript 文件可读取。这更符合依赖缓存/文件句柄/安全扫描导致的单文件访问异常，不是业务测试断言失败。
3. 后端 Full 套件两次运行分别出现 3 项和 6 项 `WinError 5`，失败点集中在 `ProjectInitializer`/`ProjectResetter` 的暂存目录原子替换，以及依赖该初始化的应用、Provider、能力策略和 release 测试。9 个不同失败用例逐个重跑均通过，说明目前证据指向 Windows 文件句柄或扫描器竞争，而不是确定性的业务回归。
4. 后端约有 106 个测试文件。应用构建与运行测试的 `_test_config` 会重复调用 `ProjectInitializer().initialize`，触发打包资源复制和目录替换；脚本、后端和钩子测试还存在 `sleep(30)`、`sleep(1)` 以及多个短固定 sleep。重复初始化和固定等待同时影响速度与稳定性。
5. 个别测试文件数量较大，例如 `tests/workspace/test_workspace_engine.py` 约 75 项、`tests/llm/test_provider_openai_sdk.py` 约 69 项。这些大多是协议/状态矩阵，不能仅按数量删除；必须先证明行为重复并核对分支覆盖。

## 问题判断与证据

| 问题 | 已有证据 | 当前判断 | 需要避免的误判 |
| --- | --- | --- | --- |
| 前端测试权限失败 | 单文件依赖读取 `EPERM`，源码测试和 `tsc` 可通过，构建卡在 KaTeX 字体 | 依赖安装/缓存或 Windows 文件访问环境异常 | 不在测试中吞掉 import 错误，也不以降低 worker 数量掩盖依赖损坏 |
| 后端 Full 间歇性权限失败 | 失败集中在暂存目录 `replace`，逐个重跑均通过 | 初始化目录原子替换与外部句柄/扫描器存在竞争 | 不立即在生产初始化器中加入无界重试，不把偶发失败标为业务失败 |
| 套件运行慢 | 重复的完整项目初始化、release 构建、进程测试固定等待 | 测试夹具和等待协议有可观收敛空间 | 不以并行化掩盖共享状态，不删除唯一的边界测试 |
| 测试数量偏多 | 应用启动配置错误测试结构相近，初始化器存在重复快照断言 | 可参数化并合并同一所有权边界的重复断言 | 不删除三层异常映射、资源来源、协议矩阵等架构证据 |

## 设计原则与非目标

- 先修复依赖环境并建立可重复基线，再调整测试结构；环境异常与测试重构分开验证。
- 生产代码保持现有异常所有权和错误码/错误原因映射。测试改造不能改变用户可见行为。
- 共享夹具只共享不可变模板；每个测试获得独立工作目录、配置和进程，禁止共享可变单例。
- 进程测试以确定性握手和总超时为依据，使用单调时钟轮询；保留一个真实超时/终止语义测试，删除重复的等待时长变体。
- 测试削减以行为和分支为单位，不以文件/用例数量为目标。删除前记录被覆盖的行为、保留的代表用例以及覆盖依据。
- 不引入宽泛异常捕获、无限重试、测试专用环境分支、第二套任务状态机或静默跳过。
- 本计划不包含自动删除 `.local-test/runs` 失败产物。保留失败现场有助于诊断；如需清理，另提供显式、可确认的 prune 操作。
- 在 Full 连续稳定前不启用无界 xdist。若后续并行，必须使用有界 worker、独立根目录和可复现实验记录。

## 可行方案

### 方案 A：修复环境并收敛测试夹具（采用）

使用新的本地 pnpm store 重装前端依赖；后端增加一次初始化的不可变项目模板，并为每个测试复制到独立目录；将固定 sleep 替换为确定性等待；参数化真正重复的应用启动失败测试；增加 Generation 生成级分层。该方案直接处理已观察到的文件访问竞争和重复开销，保持生产边界不变。

### 方案 B：只降低并发或增加重试（不采用）

降低 Vitest worker 或在 `replace` 失败时重试，可能暂时减少出现频率，却无法修复不可读依赖文件，也会掩盖句柄泄漏和清理缺陷；不符合异常处理和可观测性要求。

### 方案 C：大规模删除测试（不采用）

按测试数量或运行时间删除 workspace、OpenAI SDK 等矩阵测试，会丢失协议边界和回归保护；在没有行为映射和覆盖证据前不可执行。

## 目标架构与改动预览

### 1. 依赖环境与权限诊断

执行一次干净的前端依赖安装，使用仓库锁文件和新的可写 store（例如 `B:\tmp\tinysoul-pnpm-store`），不修改或提交 `visualization/node_modules`。验证依赖文件可读、KaTeX 字体可解析、Vitest worker 能启动。

可选的低风险配套是固定 `packageManager` 版本（与当前 pnpm 版本一致）并在测试文档中统一使用 pnpm；只有在仓库约定需要时才修改 `visualization/package.json`。不增加测试 fallback，不捕获模块加载异常。

若干净 store 仍复现单文件 `EPERM`，记录文件路径、ACL、进程句柄和安装来源，作为环境/主机问题阻断项，不通过代码绕过。

### 2. 后端共享项目模板

新增 `tests/conftest.py` 或 `tests/support/project.py` 中的项目夹具：

- session 级创建一次完整、只读的初始化模板，模板使用独立的 `.local-test/runs` 根目录。
- 用例级将模板复制到独立临时目录；需要修改配置的测试只修改副本。
- 对只需要配置解析的用例提供最小配置夹具，避免无必要地运行完整资源初始化。
- 保留 `tests/app/test_initializer.py` 对真正初始化、复制树、资源来源和原子替换的直接契约测试；这些测试继续调用生产初始化器。
- 不跨测试共享工作区、Home、Provider 或进程；fixture 清理失败必须显式失败并保留现场。

先统计所有 `_test_config`/`ProjectInitializer` 调用点，再逐个迁移 `tests/app/test_builder.py`、`tests/app/test_runtime.py` 以及 LLM、infra、action 中确实需要完整项目的调用点。每次迁移后核对路径根、配置覆盖和文档 source provenance 不变。

### 3. 进程等待与清理

在测试支持模块提供小型 `wait_until`（单调时钟、短轮询、总 deadline、失败时附带最后状态），或在现有领域 helper 中实现等价逻辑；不引入通用任务调度器。

- `tests/capabilities/script/test_script.py` 和 `tests/action/test_backends_engine.py` 的 30 秒固定等待改为子进程握手、事件/输出条件或短 deadline 轮询。
- `tests/action/test_hooks_runner.py` 的 `.02/.08/.2` 秒等待已核对并保留：它们是 timeout/grace/非协作执行语义的受控模拟，不是等待线程调度的 setup sleep；删除或改成无时间推进的断言会削弱该所有权边界覆盖。
- 保留每个进程所有权边界的一项超时、终止和清理测试；其余只验证相同结果的时间变体合并。
- 退出后明确断言进程已结束、临时目录可清理；失败时报告 pid、状态和日志，便于区分权限竞争与业务错误。

### 4. 测试分层与运行入口

在 `pyproject.toml` 增加严格声明的 `generation` marker，并在不改变现有 `external`、`release` 语义的前提下更新 `scripts/test.ps1`：

- `Fast`：默认本地业务逻辑测试，排除 `generation`、`release` 和 `external`。
- `Generation`：只运行 package-owned 项目/资源生成契约与 `release` wheel 验收，用于诊断初始化、资源物化和隔离安装边界。
- `Full`：全部非 external 的本地测试，包括 Fast、Generation 和 release。
- `External`：保持现有 external 入口和凭据要求。

没有为了隐藏权限失败增加 `slow`/`integration` 标记；剩余成本来自真实生成、wheel、Provider、进程或资源边界，已有 marker 和独立 Generation 入口足以表达当前职责。README 已记录 suite 边界和推荐命令。

前端依赖修复后再新增 `visualization/vitest.config.ts`，采用有界 worker 配置；保留纯 Node 测试的默认环境和文件级 `jsdom` 指令。配置只用于减少 worker 启动噪声和控制资源，不作为不可读依赖的 workaround。

### 5. 安全削减与重构顺序

按以下顺序处理，先降低重复执行成本，再减少重复断言：

1. 将 `tests/app/test_builder.py` 中同一启动错误映射的相似用例参数化，保留各 owner boundary、Runtime reason 和编程错误透传的代表用例。
2. 重新划分 `tests/app/test_initializer.py` 的完整项目树/配置快照与 profile 语义断言；完整快照只保留一个权威来源，release 测试只验证 wheel 特有行为。
3. 对重复调用完整初始化器的模块迁移共享模板；不改变 initializer 自身契约测试。
4. 盘点 workspace、OpenAI SDK、task runner 等矩阵，只有在两个用例覆盖相同输入类别、状态转换、异常映射和外部可见结果时才合并；否则保留矩阵。
5. 运行覆盖率/分支清单（必要时使用 mutation 结果）并在计划中记录每个删除用例的替代覆盖点。

## 文件影响预览

本计划阶段新增：

- `docs/analysis/20260903-test-permission-speed-stability-reduction-execution-plan.md`

实施阶段预期触及（按实际需要取舍）：

- `tests/conftest.py` 或 `tests/support/project.py`、`tests/support/process.py`
- `tests/app/test_builder.py`、`tests/app/test_runtime.py`
- `tests/app/test_initializer.py`、`tests/release/test_wheel.py`
- `tests/llm/test_config.py`、`tests/infra/test_config_catalog.py`、`tests/action/test_catalog_loader.py`
- `tests/action/test_backends_engine.py`、`tests/action/test_hooks_runner.py`、`tests/capabilities/script/test_script.py`
- `pyproject.toml`、`scripts/test.ps1`、`README.md`、相关测试文档
- `visualization/vitest.config.ts`，以及必要时的 `visualization/package.json`

明确不修改：生产初始化器和 Runtime 异常流程（除非后续证据证明生产原子替换本身有确定性缺陷并另立方案）、`visualization/node_modules`、与本问题无关的模块。

## 执行阶段与退出条件

### 阶段 0：建立基线（`done`）

- 保存 Fast、Full、typecheck、前端 focused/full test/build 的命令、耗时、失败栈和环境信息。
- 记录当前失败样本的路径、suite、是否可单独复现。

退出条件：任何后续优化都能与基线比较，且不把环境错误误记为测试回归。

### 阶段 1：依赖权限修复（`in_progress`）

- 使用新的 pnpm store 执行 frozen-lockfile 安装。
- 直接读取之前失败的 JS 和字体文件，并运行前端全量测试、`tsc`、build。
- 若仍失败，保留诊断记录并阻断前端验收，不添加代码绕过。

退出条件：依赖文件可读，worker 无启动权限错误，前端 test/typecheck/build 全部通过。

### 阶段 2：项目夹具迁移（`done`）

- 先实现不可变模板和独立副本，再按调用点迁移。
- 每批迁移运行涉及模块的 focused tests，并核对配置、资源树和 source provenance。

退出条件：重复初始化次数显著下降；所有迁移模块的行为断言和清理断言保持通过。

### 阶段 3：等待稳定化（`done`）

- 替换固定长 sleep，增加确定性握手和有限 deadline。
- 失败信息包含最后可观察状态，避免无上下文超时。

退出条件：进程相关 focused tests 连续运行无随机超时，且不延长正常路径等待。

### 阶段 4：测试分层与削减（`done`）

- 添加 `generation` marker 和 Generation suite 选择；参数化/合并已证明重复的断言。
- 记录删除用例到替代覆盖点的映射，核对异常所有权边界。

退出条件：Fast 运行时间下降，Full 覆盖保持；Generation 保留初始化、资源来源和 release 行为；没有因削减而丢失模块边界或异常映射。

### 阶段 5：完整验证与计划核对（`in_progress`）

- 连续运行至少 5 次后端 Full，确认不再出现间歇性 `WinError 5`；已完成 5 次连续通过。
- 执行 Fast、Full、typecheck、前端 test、`tsc` 和 build。
- 执行 `git diff --check`，回读本计划，把每项状态更新为事实状态。前端干净依赖安装仍受外部权限阻断，因此计划暂不移动到 `done`。

## 验收标准

- 前端在干净依赖安装中可读所有包文件，Vitest、TypeScript 和 Vite build 通过；不依赖隐藏的权限重试或异常吞噬。
- 后端 Full 连续 5 次通过；之前的偶发 `WinError 5` 不再被连续门禁复现，仍保留真实生成契约以捕获回归。
- Fast 的正常路径耗时相对基线下降，长固定 sleep 被确定性等待替代。
- 任何测试删除都有行为重复证明和替代覆盖；三层异常语义、模块 owner boundary、资源来源和 release 契约仍有直接测试。
- 未新增宽泛异常捕获、无界重试、共享可变状态、测试专用兼容分支或第二状态机。
- 代码风格、异常处理、文档状态和测试入口与 `AGENTS.md` 及现有模块保持一致。

## 建议验证命令

后端使用仓库约定的 TinySoul Python 环境：

```powershell
.\scripts\test.ps1
.\scripts\test.ps1 -Suite Generation
.\scripts\test.ps1 -Suite Full
.\scripts\typecheck.ps1
```

前端在 `visualization` 目录使用 pnpm：

```powershell
pnpm install --frozen-lockfile
pnpm test
.\node_modules\.bin\tsc.CMD --noEmit
pnpm build
```

每个阶段还应保存 focused test 命令和耗时，最后执行：

```powershell
git diff --check
git status --short
```

## 当前阻断与下一步

当前计划不能标记完成：测试结构、速度、等待协议、Generation 分层以及后端连续 Full 门禁均已完成，但前端干净依赖安装受外部权限审批故障阻断，已知依赖文件仍可由直接 Node 读取复现 `EPERM`。当前 `D:\nvm\nodejs` 已指向 `v24.9.0`，Node 24 下 Vitest、TypeScript 和 Vite build 全部通过；`nvm` 未在 PATH 中，直接执行 `D:\nvm\nvm.exe use 24` 无输出并超时，但不影响当前已生效版本。下一步仅需在可下载依赖的环境中重做 frozen-lockfile 安装并验证相关文件可读；后端不需要为已连续 5 次通过、不可重复的 `WinError 5` 修改生产原子替换语义。
