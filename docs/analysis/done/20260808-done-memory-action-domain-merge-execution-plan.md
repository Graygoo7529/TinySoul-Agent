# Memory Action Domain 合并执行计划

## 背景与状态

- 状态：`done`
- 目标：将 User Turn 的 Memory Action 规划域合并到 `core`，降低 Phase1 在内部状态来源之间的预判负担，同时保持 Memory 模块的事实所有权和执行边界不变。
- 范围：`tinysoul/action/catalog`、Memory Action 的公开 catalog identity、相关测试和设计文档。
- 不在范围：不迁移 `tinysoul.memory` owner，不改变 `memory:` Link、活动记忆 CAS、持久文档事务、Memory Maintenance catalog 或配置 namespace。

## 确认的设计语义

1. Action domain 是 Phase1 的粗粒度行动方向，不等同于业务模块 owner。`core` 表达当前 Turn 的内部认知与收敛，包括 Context/Session/Memory 检查、推理、活动记忆维护和回答。
2. Memory executor 继续由 `tinysoul.memory` 注册：catalog 的公开 identity 与 backend handler 分离。
3. 三个 User Memory Action 的公开 identity 迁移为：
   - `core.memory.inspect` -> `memory.inspect`
   - `core.memory.recall` -> `memory.recall`
   - `core.memory.memorize` -> `memory.memorize`
4. 不保留 `memory.*` catalog alias，不在 Action、Home 或 Provider 层增加双读兼容。开发迭代阶段不执行旧 trace、旧 prompt mount 或部署数据迁移。
5. Memory Action 不显式设置 timeout 时继承 core domain 的 `60s` 默认值；只有确认存在较长执行需求时，才由具体 Action 显式覆盖。Action 仍保持原有串行策略声明。
6. Memory 持久事实仍只有 Memory owner 写入。User Turn 的 `memorize` 仍只能 patch 活动 `Memory.md`；持久 daily/entity/concept/fact/note 仍只能由 Memory Maintenance 维护。

## 实施步骤

### 1. Catalog 迁移 (`done`)

- 将三个 Memory Action TOML 移入 `tinysoul/action/catalog/core/actions/`。
- 将 `name` 和 `domain` 更新为 `core.memory.*` / `core`。
- 删除 `tinysoul/action/catalog/memory/domain.toml`，使 `memory` 不再是 User Action domain。
- 更新 core domain 的 description 和 selection hint，保持精简、泛用，不把 Memory 细节硬编码到 Phase1 协议。

### 2. Action identity 契约 (`done`)

- 在 Action Catalog 注册边界校验 action identity 必须以 `${domain}.` 开头，并校验 loader 中 package domain 与声明 domain 一致。
- 保持 Home reconciliation 的防御性校验；它只消费已加载的 catalog，不承担 Action catalog 的首要身份验证。
- Memory executor 的注册 key、owner bridge、failure scope 和内部 Memory 方法保持 owner 语义。

### 3. 文档与测试 (`done`)

- 更新 `AGENT.md`、`docs/design/action.md`、`docs/design/memory.md` 和默认 tinysoul 文档 skill 中的 User Action 名称与域语义。
- 更新 catalog、Phase3 Memory 集成和 domain scope 测试；区分公开 `core.memory.*` identity 与 `memory.*` backend handler。
- 保持 `maintenance.memory.*` 测试与实现不变。

### 4. 验证与收尾 (`done`)

- 运行 Action/Loop/Memory/Home 聚焦测试。
- 在 `conda activate TinySoul` 环境运行 Fast、Full 和 typecheck 门禁。
- 复核 domain/action 列表、Home prompt mount 派生和 trace identity，确认本计划各项均与实际实现一致后将文件标记为 `-done-`。

验证结果：

- Action/Loop 聚焦测试：通过。
- Full：`881 passed, 2 skipped, 21 deselected`。
- typecheck：`All checks passed!`。
- 有效 User Action domain：`core`、`execution`、`home`、`web`、`workspace`；`memory` 已移除。
- core Action：`core.answer`、`core.context.inspect`、`core.memory.inspect`、`core.memory.memorize`、`core.memory.recall`、`core.reason`、`core.session.inspect`。

## 风险与取舍

- 新 core domain 会多暴露三个工具，但总量仍是有界的；Action semantic 的 use/avoid 语义继续区分只读检查和活动记忆修改。
- 新 trace 的 domain/action identity 会变化，这是明确的 catalog 破坏性变更，不通过兼容 alias 掩盖。
- 旧 `skills_domain/memory` 或 `skills_action/memory/*` 不做自动迁移；catalog reconciliation 按新 identity 管理合法 mount。当前模板没有这些旧 mount。
