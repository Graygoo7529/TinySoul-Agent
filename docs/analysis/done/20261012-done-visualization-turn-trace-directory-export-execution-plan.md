# Turn Trace 目录包导出执行计划

状态：`done`。桌面目录包导出已完成；提交后真实 ZIP 暴露的根路径缺陷已修复，Turn 概览已补齐。补充实施见 [Trace 包根与 Turn 叙事计划](20261012-done-trace-package-root-and-turn-narrative-execution-plan.md)。2026-10-12 已核对实现、设计文档和必要验证，归档本计划。

## 目标

将 Detail 面板的 `Export trace` 从单个事件窗口 JSON 导出，改为桌面端可选择保存位置的 ZIP 目录包。目录包服务于轨迹研究：能够按 `turn → cycle → phase → LLM task → attempt` 定位每一次真实模型调用，读取该次调用的实际请求语境和模型响应，并保留足够的执行关联信息。

导出是 Observation 事件的有界投影，不建立第二套持久日志，也不声称事件窗口之外的历史完整可得。

## 已确认的现有语义

1. `llm.model.request` 的 `messages` 是已经装配好的 provider-neutral `MessageStack`，其中包含本次调用实际使用的 context、TaskPrompt 和此前反馈；`tools` 与 `tool_selection` 表达本次调用可见的工具定义和选择约束。
2. `llm.model.response` 表达一次实际 provider attempt 的模型响应，包括文本、tool calls、停止原因、usage 和有限 reasoning 摘要。
3. 一个逻辑 LLM task 可能有多个 provider attempt。重试或切换 provider 时，attempt 的 model/provider/adapter 可能不同，但逻辑 request 通常相同。
4. `provenance`、`resolved_references` 是当前 Detail 面板用于解释消息来源和引用的内部观测标注，不是 provider request 的参数，也不是模型可见消息本身。它们继续保留在现有事件中供面板使用，但不进入导出包的实际 request 投影。
5. `action.call` 在 Phase2 归一化和准备，`action.result` 在 Phase3 执行并产生。Action 是导出的辅助关联信息，不取代 LLM request/response。
6. LLM、Embedding、JEV 等模型调用都通过带 scope 的 Observation 事件出现；Phase3 也可能包含 Action 内部的 LLM 调用，因此不能只导出 Phase1/Phase2 的模型事件。
7. 当前前端把整个事件窗口序列化为单个 JSON Blob；Tauri 已有保存对话框插件和文件写入命令，但前端尚未接入，现有写入命令也不是 ZIP 导出接口。

## 目标目录结构

桌面端选择一个 `.zip` 文件，ZIP 内使用稳定的顺序目录和 JSON 文件。顺序编号用于阅读和避免把长 ID 放入路径，原始 ID 始终保留在 JSON 中。

```text
turn-trace-20261012-5/
├── manifest.json
├── index.json
├── turn.md
└── cycles/
    └── 001/
        ├── cycle.json
        ├── phase1/
        │   ├── llm/
        │   │   └── tasks/
        │   │       └── 001/
        │   │           ├── task.json
        │   │           ├── request.json
        │   │           └── attempts/
        │   │               ├── 001/
        │   │               │   ├── meta.json
        │   │               │   └── response.json
        │   │               └── 002/
        │   │                   ├── meta.json
        │   │                   └── response.json
        │   └── auxiliary-model/
        │       └── 001/
        │           ├── meta.json
        │           └── detail.json
        ├── phase2/
        │   ├── llm/
        │   ├── auxiliary-model/
        │   └── actions/
        │       └── calls/
        │           └── 001.json
        └── phase3/
            ├── llm/
            ├── auxiliary-model/
            └── actions/
                └── results/
                    └── 001.json
```

### Manifest 与索引

`manifest.json` 只保存包级元数据：

- schema version；
- 精确 `turn_id`、day、导出时间、`instance_id`；
- 固定事件窗口的 `through`、`truncated`、事件数量；
- cycle、phase、task、attempt、auxiliary call 数量；
- 内容说明：这是 retained observation window 的导出。

`index.json` 提供导航和关联：

- cycle、phase 的顺序和原始 scope；
- 每个 task 的 `task_id`、consumer、target/profile、状态和 attempt 列表；
- 每个 attempt 的 request 引用、response 路径、model/provider/adapter、状态；
- auxiliary model call 的 consumer、implementation、target、call/search 关联和 detail 路径；
- action call/result 的 `call_id`、action、状态及跨 Phase 路径。

索引不复制完整 messages、工具定义或响应正文。

### Task 与 Attempt 的分层

以 task 作为逻辑容器，以 attempt 保存每次实际调用结果：

- `task.json` 保存 task_id、scope、consumer、target/profile、task 生命周期状态和 attempt 数量；
- `request.json` 保存经过导出投影的逻辑 request：`messages`、`tools`、`tool_selection`；不声称包含 provider HTTP 报文的全部参数；
- 每个 attempt 的 `meta.json` 保存 attempt、model、provider、provider_model、adapter、时间和状态；
- 每个 attempt 的 `response.json` 保存该次真实模型 response；
- 如果某个 attempt 的逻辑 request 与 task 级 request 不同，则该 attempt 自己保存 `request.json`，并在 `meta.json` 中使用本地 request 引用；
- 如果 request 相同，attempt 通过 `request_ref` 指向 task 级 request，不重复保存完整 messages 和工具定义。

导出器通过稳定 JSON 投影计算逻辑 request 是否相同，不把 provider、attempt、时间等调用元数据纳入比较。这样重试调用仍全部保留，但不会重复写入相同的长语境。任何缺失的 request/response 都如实标记，不补造文件内容。

`request.json` 不包含 `provenance`、`resolved_references`。这些字段不是实际发送给模型的内容；它们继续留在事件窗口，供现有 Model Call Detail 面板按来源分组和显示引用。这样本次导出不需要修改现有事件契约，也不会破坏前端已有的解释视图。

### Phase 与模型调用归属

所有带有有效 cycle/phase scope 的 `llm.model.request/response` 和 `model.call.*` 都按事件 scope 写入对应 phase。Phase3 下的 LLM 调用与 Phase1、Phase2 使用完全相同的 task/attempt 结构，不做特殊排除。

辅助模型调用使用对应 phase 的 `auxiliary-model/` 目录。`model.call.*` 只导出已有的调用元数据和 `model.call.detail`；如果事件没有完整 provider-neutral messages，就不伪造 LLM request/response。无法归属 phase 的辅助调用才使用包顶层的 fallback 目录。

### Action 归属

Action 记录保持现有执行语义：

- Phase2 的 `action.call` 写入 `phase2/actions/calls/`；
- Phase3 的 `action.result` 写入 `phase3/actions/results/`；
- `index.json` 用 call_id 关联两者。

不把 `action.call` 重新标记为 Phase3，也不复制完整 ActionResult 模型叙事。模型 response 中的 `tool_calls` 已在 response 文件中保留；Action 记录只作为从模型意图到执行结果的紧凑关联。

## 实施范围

### 前端 visualization

1. 在 trace 功能内新增纯函数式导出构造器：
   - 读取已有 `EventWindow`；
   - 按 scope 构造 cycle/phase；
   - 归并 LLM task、attempt、request、response；
   - 归并 auxiliary model call；
   - 归并 Phase2 action call 与 Phase3 action result；
   - 生成 `manifest.json`、`index.json` 和各 JSON 文件内容。
2. 导出构造器只依赖原始 `ObservationEvent[]` 和固定窗口元数据，不复用面板的摘要状态，也不重新读取后端或调用模型。
3. `ProcessPanel` 的 Export trace 改为：
   - 在读取窗口时固定 `through`；
   - 构造导出文件集合；
   - 桌面端调用原生保存对话框，默认文件名为 `turn-trace-<safe-turn-id>.zip`；
   - 调用 Tauri archive 命令写入 ZIP；
   - 成功后显示保存路径，失败显示有限自然语言错误；
   - 保留 `truncated` 提示，不能把部分窗口标成完整 trace。
4. 浏览器开发模式保留可用的下载 fallback。没有 Tauri archive 能力时，可下载当前导出 JSON 或浏览器 ZIP 实现；该 fallback 不改变桌面端协议。
5. 更新前端设计文档，说明导出是按 retained event window 生成的目录包，模型 request 是 provider-neutral 实际请求投影，Action 与 auxiliary model 的归属规则如上。

### Tauri 桌面端

1. 用专用 `write_export_archive` 命令替换当前未接入的目录文件写入命令。
2. 命令接收用户选定的 archive path 和相对路径文件集合，校验相对路径不能逃逸包根目录。
3. 使用 Rust ZIP writer 生成归档，先完成临时文件后替换目标文件；当前覆盖已有目标时先删除再 rename，不宣称原子覆盖。
4. 写入命令只负责文件归档，不解释 turn、cycle、LLM 或 Action 语义。
5. 删除未使用的旧 `write_export_files` 命令和对应死路径，避免保留两套导出写入协议。

### 后端事件协议

本计划不修改后端 Observation 事件结构。原因是 `provenance` 和 `resolved_references` 当前仍被 Model Call Detail 面板用于解释消息来源；导出层过滤它们即可满足“实际 model request”语义，避免为导出需求扩大后端协议变更范围。

如果以后要收窄 `llm.model.request` 事件本身，应另行更新事件契约、Detail 面板和相关测试，不在本次导出改造中顺带完成。

## 验证计划

1. 导出构造器单元测试：
   - 多 cycle、多 phase 的顺序和路径；
   - Phase1、Phase2、Phase3 均有 LLM task；
   - 同一 task 多 attempt 共享 request；
   - request 发生变化时退回 attempt 级 request；
   - request 只有而 response 缺失、response 只有或 task failed 的情况；
   - auxiliary model call 按 phase 归档；
   - action call/result 分属 Phase2/Phase3 且 index 可关联；
   - provenance/resolved_references 不出现在 request 投影；
   - `through`、`truncated` 和原始 turn_id 保留。
2. Tauri 命令测试或最小集成验证：
   - 正常生成 ZIP 并能解压读取；
   - 路径校验拒绝绝对路径和 `..`；
   - 写入失败返回有限错误；
   - 旧目录写入命令不再注册。
3. 前端组件验证：
   - Detail 面板点击 Export trace 会打开保存流程；
   - 取消保存不产生错误提示；
   - 成功显示保存位置；
   - 截断窗口明确显示部分导出。
4. 运行 `visualization` 的类型检查、测试和构建；必要时运行 Tauri 检查。

## 预期效果

用户打开导出的 ZIP 后，可以先从 `index.json` 找到某个 cycle 和 phase，再进入具体 task。每个 task 能看到一次逻辑请求；每个 attempt 能看到实际 provider、重试顺序和对应 response。Phase3 内的 Action LLM 不会漏掉，辅助模型调用也能在触发它们的 phase 中定位。完整语境只在真实 request 文件中出现一次，避免多个重试复制相同的大文件，同时不牺牲 attempt 级响应和失败轨迹。

总包大小仍然取决于保留的完整 messages 和 response；目录包解决的是定位、分步读取和轨迹分析问题，不承诺压缩语境内容本身。

## 完成标准

- 桌面端可通过保存对话框生成可解压 ZIP；
- 每个保留的模型 attempt 都能定位到 request（直接文件或 task 级引用）和 response/缺失状态；
- request 投影包含实际 messages、tools 和 tool selection，不包含仅用于解释的 provenance/resolved references；
- Phase1/Phase2/Phase3 的 LLM 调用均按 scope 导出；
- auxiliary model 和 action 记录归属清楚，未建立第二套执行状态机或持久日志；
- 事件窗口边界、截断状态和缺失事实如实保留；
- 前端现有 Model Call Detail 的解释能力不受影响。

## 实施复核

### 已完成

- [x] 新增 `trace/export.ts`，从固定 `EventWindow` 生成 ZIP 内部文件集合、manifest 和 index。
- [x] LLM task 按 cycle/phase 归档，attempt 按实际 request/response 和 provider 事件归并。
- [x] 相同 task request 提取到 task 层；request 改变时回退到 attempt 层文件。
- [x] 导出 request 只保留 messages、tools、tool selection；现有事件中的 provenance/resolved references 继续供 Detail 面板解释使用。
- [x] Phase1、Phase2、Phase3 的 LLM 事件均按 scope 处理。
- [x] auxiliary model call 放入所属 phase，保存已有 meta/detail，不伪造 LLM request/response。
- [x] Phase2 action.call 与 Phase3 action.result 分开导出，并写入 index 关联信息。
- [x] `ProcessPanel` 接入桌面保存对话框、Tauri archive command、浏览器 JSON fallback、取消/成功/失败提示和导出中状态。
- [x] Tauri 删除旧的 `write_export_files`，新增校验相对路径、重复路径和临时文件替换的 `write_export_archive`。
- [x] 更新 Trace 和 Action renderer 设计文档。
- [x] 新增导出构造器测试，覆盖多阶段、task request 复用、attempt request 差异、auxiliary 和 action 归属。

### 验证结果

- `visualization/pnpm.cmd test`：90 个测试文件、797 个测试全部通过。
- `visualization/pnpm.cmd build`：TypeScript 检查和 Vite 构建通过。
- `visualization/src-tauri/cargo.exe check --offline`：Tauri crate、ZIP writer 和归档命令编译通过。
- `visualization/src-tauri/cargo.exe fmt -- --check`：Rust 格式检查通过。
- `visualization/src-tauri/cargo.exe test --offline`：归档写入/读取和路径逃逸拒绝测试通过，Tauri binary 和 doc tests 也通过。
- Cargo.lock 已加入 `zip 2.4.2` 及其压缩依赖。
- `git diff --check`：无空白错误。

上述 Cargo 命令使用仓库环境中已安装的 stable Rust toolchain 执行；该 toolchain 未默认加入 PowerShell PATH，但不影响代码和锁文件验证。

### 实施后边界

浏览器 fallback 仍下载包含 manifest、index 和文件内容的 JSON；只有桌面 Tauri 路径生成 ZIP。导出总大小仍由完整 messages 和 response 决定，目录层级负责定位和分步读取，不承担内容去重以外的压缩协议。

### 提交后真实导出复核

`reference/traces/turn-trace-2026-10-11-7/turn-trace-2026-10-11-7.zip` 包含 17 个真实 Cycle、30 个 LLM task/attempt 和 18 条 Action 记录。旧 manifest 的 18 包含一个 unscoped 分组，不代表 18 个 Cycle；本次已修正计数。`unscoped/cycle.json` 继续保留没有 cycle scope 的 Turn 级事件范围。

发现的缺陷是 `addActionFiles` 漏加包根，造成两个顶层目录。现已改为所有构造器只产生包内相对路径，最终统一添加一次包根；测试核对每个文件、index、attempt request_ref 和 turn.md 的证据链接均可解析到同一包内。

根目录已增加 turn.md，使用同一事件窗口生成阶段、模型返回、行动和请求语境摘录，明确首次捕获时点与缺失边界。Phase 协议和输出预算改进另列独立 pending 计划，不属于本次导出完成范围。

### 最终验证（2026-10-12）

- 导出器及保存桥接定向测试：7 项通过，覆盖统一根、证据链接、阶段失败与请求语境、Phase3 LLM、截断、request/response 缺失，以及保存对话框调用、取消/失败和浏览器 fallback。
- 前端全量 Vitest：91 文件、802 项通过；TypeScript `--noEmit`、Vite build 通过。使用安装包的 Node CLI 执行，与 package scripts 相同工具；当前 pnpm exec 的命令解析失败不作为测试结果。
- Tauri `cargo test --offline`：ZIP 写入/读取和路径拒绝测试通过。
- `scripts/test.ps1 -Suite Fast`：1270 passed、30 deselected。
- `scripts/test.ps1 -Suite Full`：1275 passed、25 deselected；`scripts/typecheck.ps1`：通过。
- 设计文档已同步。真实旧 ZIP 仅用作诊断依据，未改写，也未把它宣称为修复后重新导出的文件。保存对话框沿用原实现，本次未手工运行桌面 GUI。
