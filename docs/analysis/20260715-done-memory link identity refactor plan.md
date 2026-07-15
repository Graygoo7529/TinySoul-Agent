# 20260715 Memory Link Identity Refactor Plan

## 状态

status: done

依赖：`20260715-done-home top link identity refactor plan.md`。

## 目标

将 Memory-owned 日期 Link 统一为无格式后缀的逻辑身份，同时保持项目顶层 Memory store 的物理 Markdown 路径不变。该重构在能力扩展前完成，避免后续 Memory 片段检索或其它能力继续依赖物理格式进入 Link identity。

## 已确认语义

1. canonical Link 为 `memory:YYYY-MM-DD`，Context 引用形式为 `<memory:YYYY-MM-DD>`；
2. 物理路径继续为 `memory/yyyy/mm/yyyy-mm-dd.md`；
3. `MemoryLink` 独占日期 Link 与物理相对路径的双向映射，业务模块不得自行拼接 `.md`；
4. Search candidate id、recall 参数/结果、昨日 Background、Maintenance outcome 和 Observation 全部使用无后缀 Link；
5. 旧 `memory:YYYY-MM-DD.md` 不提供 alias、双读或迁移入口，必须明确失败；
6. Memory 正文仍是 Markdown，文档契约、日期 H1、单日一文档、读取上限和 Maintenance 写入边界不变；
7. Home Top、Home progressive resource、Workspace、Session/Trace 与 prompt mount Link 均不改变；
8. 当前项目没有实际 Memory 文档或 persisted 旧 Memory Link，不需要内容或磁盘迁移。

## 映射

| canonical Link | physical relative path |
| --- | --- |
| `memory:2026-07-14` | `2026/07/2026-07-14.md` |

`MemoryLink.parse()` 只解释无后缀日期身份；`MemoryLink.from_relative()` 只解释严格的物理年月 `.md` 路径；`relative_path` 继续返回物理路径，`str(link)` 只返回逻辑 Link。

## 实施项

1. 修改 `MemoryLink` regex、错误消息、string rendering 和 relative reverse mapping；
2. 更新 Memory search LLM output protocol、consolidator、正文 Link validator 和 Action Catalog；
3. 更新 Loop/App outcome、Background、默认 Home reference、AGENT 与 design docs；
4. 机械迁移测试和模型可见示例，增加旧 `.md` Link 拒绝与 round-trip 回归；
5. 运行全量测试、`ty check`、wheel 隔离安装和旧 Link 残留审计。

## 验收

- 所有模型可见 Memory Link 均为 `memory:YYYY-MM-DD`；
- 物理 store 仍只接受 `yyyy/mm/yyyy-mm-dd.md`；
- 旧 `.md` Memory Link 明确失败；
- search、recall、Background、Maintenance 与 Program output 使用同一 Link；
- Home/Workspace/progressive resource Link 不受影响；
- 当前数据不需要物理迁移，全量验证通过。

## 实施结果

`MemoryLink.parse()` 与 `str(link)` 现统一使用 `memory:YYYY-MM-DD`，`from_relative()` 和 `relative_path` 继续严格解释 `yyyy/mm/yyyy-mm-dd.md`，因此逻辑身份与物理 Markdown 格式完全分离。旧 `.md` Link 明确失败且无 alias，物理 store、原子写和年月扫描未改变。

Memory search candidate、recall 参数/结果、昨日 Background、Maintenance Link validation、Loop/Program outcome、Observation、LLM search/consolidation prompt、Action Catalog、默认 HOW reference 和当前设计文档已全部迁移。Memory 正文引用统一为 `<memory:YYYY-MM-DD>`；Home、Workspace、progressive resource 和 prompt mount Link 未变化。

当前项目没有实际 Memory 文档或 persisted 旧 Memory Link，因此无磁盘或内容迁移。定向 Memory/Loop/App 测试、全量测试、wheel 隔离构建/初始化、旧 Link 残留审计与 `ty check` 均通过。
