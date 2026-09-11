# 测试契约与内容快照清理执行计划

状态：`done`

## 目标

让测试聚焦当前稳定架构契约、跨模块协作和真实失败边界，清除对可编辑人格、提示词、配置偏好、Catalog 清单和历史结构的重复快照，降低正常内容调整造成的无意义失败。

## 边界

- 不修改生产业务语义、模块所有权或公开协议。
- 保留 MessageStack role/顺序、Action scope、三层失败、Runtime bridge、持久化一致性、取消/超时和发布可用性等稳定契约测试。
- 内容与模板测试验证解析、装载、引用、路由和资源完整性，不锁定自然语言措辞或当前可编辑清单。
- 同一语义优先在 owner 测试中覆盖；集成与发布测试只保留跨边界和代表性验收。

## 实施项

- [x] 重新核对 `AGENTS.md`、Context/Loop/Home/Action 设计与异常处理边界。
- [x] 在 `AGENTS.md` 中补充精炼的测试规约。
- [x] 清理默认 Home、人格、用户画像和 Phase prompt 的生产文案断言。
- [x] 将 Action Catalog、Scope 和初始化模板的精确清单或偏好快照收敛为结构与数据流测试。
- [x] 将 wheel 手写资源枚举改为 package 源资源与 wheel 内容的动态完整性校验，清除历史墓碑断言。
- [x] 同步 `docs/design/agent_home.md`，说明默认 Home 验收保护结构与装载契约而非文案快照。
- [x] 运行聚焦测试、Fast、Full、typecheck 和 `git diff --check`，逐项复核异常与 Runtime bridge 覆盖未被削弱。
- [x] 完成后更新实施结果，将本文件标记为 `done`、加入 `-done-` 并移动至 `docs/analysis/done/`。

## 预期改动

- `AGENTS.md`
- `docs/design/agent_home.md`
- `tests/app/test_default_home.py`
- `tests/app/test_initializer.py`
- `tests/loop/test_phases.py`
- `tests/action/test_catalog_loader.py`
- `tests/action/test_action_scope.py`
- `tests/release/test_wheel.py`

## 验收

- 调整 Agent 名称、人格、用户画像或等价提示词措辞时，不需要修改测试。
- 新增合法 Home、Skill、Action 或 package resource 时，不需要维护手写完整清单。
- Context role/顺序、prompt mount、Action scope、配置入口、失败分类与 Runtime 转移仍有直接覆盖。
- 初始化项目和隔离安装 wheel 仍能通过真实装配验收。

## 实施结果

- 测试规约已收敛为稳定契约、owner 边界、代表性协作和结构化失败语义，未再固定可编辑文案或重复快照。
- 默认 Home、初始化 profile、Phase prompt、Action Catalog/Scope 与 wheel 资源测试已完成清理；生产代码未修改。
- 聚焦测试通过；Full 门禁通过 `974 passed, 2 skipped, 23 deselected`；typecheck 和 `git diff --check` 通过。
