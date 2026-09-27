# Search 本轮重构完成情况独立复核

- 日期：2026-09-27。
- 检查提交：`76012da5306d0eb403d61cd614ff6d8cd9eced6e`，`fix: close retrieval schema and session sdk contracts`。
- 状态：`done`；独立 review 与收尾复核已完成，R1、R2 均已修正并通过本地门禁，于 2026-09-27 归档。
- 初次 review 只新增本文。后续收尾基于 `65a6814`，修改 R1/R2 对应实现、开发依赖、类型检查脚本及契约说明；既有验证事实保留。

## 1. 结论与推进建议

本轮已经实质完成 Search 的核心重构目标：以 `source + steps + page` 表达有限函数管道，让 Agent 选择候选来源、业务查询和约束步骤；把实现、模型用途及 provider 选择留在用户配置中。来源 owner、公共候选内容、操作执行、模型输入投影和结果分页之间的职责清楚，没有发现正常主线上同时运行旧、新两套 Search 协议。

这不是只把旧 `mode` 改名。query/backlinks/directory、refs/result 输入、filter/select/rerank、真实内容快照、命中依据、模型评估和页面投影已经贯通；五类来源实际接入了公共链路。之前重点指出的 lexical 否决 Embedding、模型只看零碎元数据、结果先截断再操作、缓存随一次查询覆盖等问题，已有对应实现和行为测试。

核心重构与两项局部收尾均已完成，可以按现行契约进入前后端对接。没有发现需要维护者重新裁决的核心设计分歧；修正及验证见第 3、9、10 节。

| 项目 | 判断 | 影响 |
| --- | --- | --- |
| 统一检索语义、来源与操作组合 | 已落实 | 可以作为后续功能基础 |
| 真实内容、语义命中、模型输入与分页 | 已落实 | 覆盖有限且如实披露，不等同于读过全文 |
| SDK、Action 与 owner 接入 | 已落实 | Session SDK 的旧字段问题已修正 |
| R1：不开放任何约束操作的 policy | done | 空操作配置生成合法 schema；Action 参数校验与 parser 一致 |
| R2：新安装环境的类型检查 | done | 三个 JSON 边界已明确；Conda 环境升级后 `ty 0.0.84` 全量通过 |
| 真实供应商效果 | 本次未验证 | 不把本地替身结果当成 LLM/JEV 检索质量证据 |

## 2. 复核依据与范围

重新读取了根目录 `AGENTS.md`，并以以下文件及当前代码共同判断：

- `docs/analysis/done/20260926-done-action-model-retrieval-review-and-refactor-plan-r4.md`。
- `docs/chat/finished-review-or-plans/20260927 检索统一语义与改进方案.md`。
- `docs/analysis/done/20260927-done-检索统一内容流与来源契约执行计划.md`。
- `docs/analysis/done/20260927-done-检索提交后复核.md`。
- `docs/design/action-model-retrieval.md`，相关 owner、配置、Endpoint 文档与当前测试。

后续已确认的设计收敛优先于 r4 的历史建议：JEV 只做逐候选 Score；LLM 的 `basis_ids` 可以为空；MCP 可以对真实工具定义做 literal/regex query；Reflection 通用 Home Search/Inspect 使用 effective Home；Home top 的 refs 精读与 query/directory 聚合分别有明确含义。本次没有把这些已确认调整重新列成缺陷，也没有把归档稿中的历史 `pending` 当作当前实现未完成的证据。

检查聚焦正常功能、清晰所有权、接口契约、模型配置与使用、内容/结果一致性及必要失败分类；没有扩展为新的沙箱、全局检索记忆、分布式搜索或防御性恢复平台设计。

## 3. 问题与解决记录

### R1 — P2：空 operations 配置通过 policy 解析，却生成无效 Action Schema

状态：`done`。初次 review 独立复现，已在 `retrieval_schema()` 修正；默认配置的普通 query 原本不受影响。

**原始位置与触发条件（76012da）**

- `tinysoul/kernel/retrieval/policy.py:278–280`：配置解析允许 `operations = []`，省略时也默认空集合。
- 同文件 `RetrievalPolicy` 及请求校验允许只执行来源、没有任何 step。
- 同文件 `retrieval_schema()`，尤其 `486–489`：无条件生成 `steps.items = {"oneOf": steps}`。
- `tinysoul/kernel/action/catalog/specs.py:90–98`：真实 `ActionToolSpec` 构造会校验 Schema。
- `tinysoul/kernel/action/catalog/schema.py:108–114`：正确地拒绝空 `oneOf`。
- `tinysoul/agent/composition/builder.py`：配置编译通过 `replace(action.tool, schema=...)` 重建该对象，因此此错误会阻止相应配置的装配。

当用户只开放 query/directory/refs/result，不开放 filter/select/rerank 时，配置和请求都合法，但 schema 变成：

```json
{"type": "array", "items": {"oneOf": []}, "maxItems": 8}
```

这破坏了同一 policy 对配置、Action、SDK 的统一表达。它不是“正常 query 必须附加步骤”：**在当前默认 policy 下省略 steps 已经正常工作；问题仅发生在 policy 本身不开放任何操作时。**

**实际复现**

以下代码在检查提交上无需模型、网络或业务数据即可复现，并使用生产装配同样会构造的 `ActionToolSpec`：

```python
from tinysoul.kernel.retrieval.policy import (
    parse_retrieval_policies, retrieval_schema,
)
from tinysoul.kernel.retrieval.requests import parse_retrieval_request
from tinysoul.kernel.action.catalog.specs import ActionToolSpec

policy = parse_retrieval_policies({
    "home.search": {
        "sources": ["query", "directory", "refs", "result"],
        "operations": [],
    }
})[0]

parse_retrieval_request({
    "source": {"kind": "query", "query": "knowledge"},
}, policy)  # 成功，steps == ()

ActionToolSpec(
    name="home.search",
    description="Search Home",
    schema=retrieval_schema({}, policy),
)
```

最后一步抛出：

```text
ActionSchemaDefinitionError: oneOf requires nonempty schema alternatives
key=ActionToolSpec(home.search).schema.oneOf.0.properties.steps.items.oneOf
```

**最小修正方案**

保留“只有来源也能独立使用”的设计。无开放操作时，将可选的 steps 发布为只接受空数组的合法 schema，例如：

```json
{"type": "array", "items": {"type": "object"}, "maxItems": 0}
```

有开放操作时继续使用现有有限 `oneOf`。这种修正复用现有 schema 子集，不需要允许空 `oneOf`、增加兼容分支或放宽 Action 通用校验。

必要验收：配置解析、实际 ActionToolSpec 构造、参数 schema 校验与请求 parser 对省略 steps、`steps: []` 都成功；对任意非空 step 都拒绝。用一个组合契约测试覆盖即可，不必为每个插件复制同样的测试。

落实位置：`tinysoul/kernel/retrieval/policy.py` 在没有操作变体时发布 object items 与 `maxItems: 0`；有操作时保持既有 `oneOf` 和步骤上限。`tests/kernel/retrieval/test_search.py::test_source_only_policy_shares_config_schema_and_parser_contract` 覆盖 operations 省略/空数组、steps 省略/空数组，以及三类非空操作的拒绝，贯通配置解析、ActionToolSpec、两套既有 schema 校验入口和请求 parser。设计文档与 Endpoint 配置说明同步这一契约。

### R2 — P2：类型门禁在依赖允许的新版本中仍有三处不一致

状态：`done`。三个 JSON 输出边界已明确，升级后的 `ty 0.0.84` 全量通过。这是类型边界/验证可复现性问题，不是已证明的 Search 运行时错误，也不说明历史记录中的旧环境验证虚假。

初次 review 基线的 `pyproject.toml:40` 声明 `ty>=0.0.57`。当时在 Python 3.13.15 环境中安装项目开发依赖后使用 `ty 0.0.84`，运行与脚本相同的检查参数，得到：

| 位置 | 诊断 | 复核时表达 |
| --- | --- | --- |
| `tinysoul/infra/model_services/protocol.py:96` | invalid-assignment | `dict[str, str]` 赋给递归 `JsonValue` |
| `tinysoul/kernel/action/engine.py:748` | invalid-return-type | `scenarios` 内层为 `dict[str, bool]` |
| `tinysoul/plugins/session/actions.py:78–81` | invalid-argument-type | `created_refs` 内层为 `dict[str, str]` |

使用独立的 `ty 0.0.57` 对同一源码、同一 Python 环境检查，结果为 `All checks passed!`。

**建议修正**

在三个 JSON 输出边界明确构造 `JsonObject` 类型的内层对象，再组合外层 payload。可使用带明确类型的字典推导式，或现有 JSON 转换设施。不要为消除诊断把内部类型整体改成 `Any`，也无需改变任何运行协议。

将实际通过的 Python/ty 版本记录到本次收尾记录。若项目另行选择固定工具版本，应明确记录；但对这三处简单边界，优先修清类型表达比单纯压住检查器版本更合适。

必要验收：当前采用的类型检查器通过，JSON 序列化结果不变。无需再增加一套逐字段镜像测试。

落实位置：上述三个文件分别通过带 `JsonObject` 标注的字典推导式构造 criteria、scenarios、created_refs，再装入原有 payload，保持键、值、顺序和序列化语义。没有扩大为 Any 或新增忽略。`pyproject.toml` 的开发依赖下限提高到 `ty>=0.0.84`；维护者批准后，Conda TinySoul 中的 ty 从 0.0.61 升至 0.0.84，Python 保持 3.13.12。`scripts/typecheck.ps1` 输出实际 Python 和 ty 版本后执行原有全量检查；仍使用范围依赖，没有另设固定版本锁文件。

## 4. 对原始目标的逐项判断

### 4.1 六个操作是否真正形成统一而灵活的 Search

已经形成。对外仍是各 owner 的 Search Action，由同一有限请求语言表达操作；不需要为六个概念各建一套 Action runner。

| 概念 | 当前职责 | 输出/顺序约束 |
| --- | --- | --- |
| query | 在声明范围中按配置通道发现候选 | 独立词法/向量结果融合；不隐式追加模型 select |
| backlinks | 查 owner 自己来源中的真实入边 | 返回来源候选、正文及关系依据；anchor 可跨空间 |
| directory | 不依赖关键词命中的来源枚举 | 真实内容或如实标记的 metadata，owner 稳定顺序 |
| filter | 对当前集合做显式属性比较 | 稳定子集，不读文件、不调用模型 |
| select | 按 criterion 和可选 Context 决定成员 | 稳定子集，允许空集 |
| rerank | 按 criterion 和可选 Context 决定次序 | 保留全部成员，不冒充筛选 |

`refs` 是已知入口，`result` 是当前生命周期中的完整结果输入，不再作为新的发现算法。可以纯 query、refs 纯读、refs → filter、refs → rerank，也可以 query → rerank → select、backlinks → select、directory → select。Backlink select 和 MCP select 都是同一个候选 select 操作使用不同来源，并没有特殊的第二种 select。

组合是有限线性管道。来源只在请求开头执行一次，后续操作处理显式 CandidateSet；每步拥有自己的 criterion，没有隐式继承 query，也没有由内部模型再创造子搜索循环。这一边界符合本轮目标。

主要实现：`kernel/retrieval/contracts.py`、`requests.py`、`policy.py`、`operations.py`、`engine.py`。

### 4.2 真实内容是否贯穿输入、命中依据和输出

已经建立统一内容流：

1. owner 读取真实资源，生成 `ContentUnit`，保留原文、ref 和位置。
2. `SearchCandidate` 持有内容快照、属性及来源依据；`SearchEvidence` 引用实际单元范围，不另外保存一份可能失真的正文。
3. `project_candidate()` 生成模型输入和页面需要的有界真实摘录；两者复用投影机制，拥有各自预算。
4. LLM/JEV 对每个候选接收真实展开，而不是只接收 ref、标题或零碎属性。
5. SearchPage 返回候选 ref、真实 fragments、位置、命中依据、覆盖信息及必要模型评估。

来源是否完成、候选快照是全文/摘录/metadata、模型实际看到了多少、当前页展示了多少分别表达。缩短页面不会反向改变快照，也不会把模型的局部读取变成“已读全文”。

LLM 的非空 `basis_ids` 只能指向本次给该候选的真实片段，不能自行编造正文。空 basis 合法。JEV 仅承诺 Score 和实际输入覆盖，不伪称识别了某个命中位置。Embedding 保留参与计算的真实贡献单元。

这满足“至少有实际内容预览”的目标。仍须准确理解能力：Embedding 命中单元是语义证据，不是模型已经证明了某个词或句子为何相关；有界摘录也不能保证包含长文中的全部相关信息。后续精读通过 Inspect/read/describe 继续完成，当前实现没有用虚假的解释抹平这些差异。

### 4.3 lexical 是否仍会否决或裁剪 Embedding

未发现这条旧问题残留在当前公共 query 链路。

- `SearchSession._query_candidates()` 分别执行启用的 lexical 与 Embedding 通道。
- `embedding_rank()` 在合格候选的真实内容单元上计算，不先使用 lexical 结果作为候选全集。
- `fuse()` 合并各通道成员与依据；语义命中即使没有相同关键词，也可以留下。
- 页面与模型输入投影会为来源通道的依据安排空间，混合命中有专门回归用例。
- 来源资格来自显式 `source.where` 和 `exclude_refs`；后续删除来自显式 filter/select；rerank 不删除。
- 超过内容/输入容量会明确返回 `scope_required`；不会静默保留最前面的若干候选并谎称搜索完成。

标准配置目前 query 默认 lexical。这是模板中的明确选择，不是运行时把混合检索降级。需要语义向量召回时，应启用相应 owner 的 Embedding use 和 query 通道。若配置的某个可恢复通道失败，输出保留已完成通道并披露缺失；这与“lexical 否决 Embedding”是不同语义。

### 4.4 select/rerank 是否具有语境下的排除性与顺序性

已具备我们确认的机制，不需要额外的自动黑名单体系。

- LLM/JEV 操作可按 capability/policy 使用 `context=current`，同一次 Search 使用一次准备好的 Context。
- criterion 表达本次要找什么、排除什么；select 可删除无用候选，rerank 可改变优先顺序。
- `exclude_refs` 是本请求的显式身份排除，不把“看过”“低分”“上一轮没采用”自动升级为永久事实。
- 新请求使用 `result_ref` 时复用完整内容与原始来源覆盖，但清除旧模型评估/分数，再按新语境重新处理。翻页则保持旧评估，不重调模型。
- Embedding similarity 只按显式 criterion 工作，不擅自把完整 Context 拼成 query，也不承诺与 LLM/JEV 一样的语境判断。

因此，不同 Context 可以影响新的 select/rerank；框架不保证模型每次必然输出不同次序。Agent 若已明确知道某个候选此次无用，最可靠的表达仍是显式排除或明确 criterion。这与“让 Agent 自主决策、保持基础设施简洁”的目标一致。

### 4.5 Inspect 与 Search 是否各司其职

保持了合理边界。

- `core.context.inspect` 继续对 Trace/Session 已知 refs 做确定性渐进披露；不在内部再执行 LLM/JEV 搜索。
- Home/Memory 已知文档、Workspace 文件、MCP 工具可通过各自 inspect/read/describe 继续展开。
- Search 负责发现、约束和排序，返回足够真实线索；Search 页面续接只处理已有结果成员，深读正文仍交给来源 owner。
- Search 的辅助模型调用不解除此前 Inspect 结果面向实际决策模型的展示保护。

“迭代式、渐进式信息披露”体现在 Agent 可以沿真实 ref 继续追溯，而不是要求每个 Inspect 都自行调用模型。现在的实现与初始理念一致。

## 5. 各来源的实际接入

| 来源 | 当前实现核对 | 重要差异保留 |
| --- | --- | --- |
| Home | `HomeEngine.search_corpus()` → 公共 SearchSession | 搜索 agent/skills 公开空间；query/directory 的普通 Skill 按 top 聚合；真实深层命中仍保留资源位置；其他内容返回 resource；refs top 只读 SKILL.md |
| Memory | `MemoryEngine.search_corpus()` → 公共 SearchSession | 五类持久文档、文字/文档 query、结构化及正文链接的反链；refs 保序且支持 fragment；无效引用局部失败 |
| Context/Session | Context 搜集 Trace/Session 原始事实与解释 → `disclosure_corpus()` | 不依赖当前压缩展示内容搜索；事实/解释属性区分；共用 context.inspect；Session SDK 限定自己的来源 |
| MCP | `ExpandEngine.search_corpus()` → 公共 SearchSession | 实际工具定义是内容；query 对定义词法匹配，directory → select/rerank 提供语义发现；不伪造 Embedding 或 backlinks 能力 |
| Workspace | `WorkspaceEngine.retrieval_corpus()` → 公共 SearchSession | manifest/属性归 owner，实际正文及 Markdown 边进入快照；原生逐行 literal/regex matcher 注入公共 query；没有第二套 SDK 搜索结果或向量库 |

Home 的聚合先确定候选和聚合属性，再判断来源资格，不因筛选 `.py` 就把同一 Skill 的 `.md` 内容丢掉。backlinks 返回真实引用源资源，不为凑统一格式强行变成 Skill top。Reflection 的检索来源选择与接受 overlay 的写权限仍分离。

反链目标身份由目标 owner 的 ReferenceResolver 解释，来源边由当前 owner 提供；没有扫描其他 owner 来建立第二套全局持久关系库。这符合“允许 anchor 指向其他空间，每个 owner 搜索自己的来源”的确认。

最新 Session SDK 修正已经读取 `request.source.scope`，并通过实际 SDK 回归测试；未见旧 `request.options.scope` 在此路径继续使用。

## 6. 架构、配置与编码一致性

### 6.1 责任划分成立

| 层次 | 当前职责 |
| --- | --- |
| owner/plugin | 资源身份、来源范围、读取、属性、关系、生命周期与自身 I/O 失败 |
| retrieval | typed 请求、有限操作、统一内容投影、候选集合、模型操作和快照分页 |
| Action/model-use | 代码声明可用实现，配置绑定 consumer；Action executor 准备业务参数与 Context |
| LLM / ModelServices | 模型请求、provider 协议与切换、重试、typed 输出，不决定业务来源 |
| Agent / SDK | 显式装配、解析后 policy/capability、generation/day 服务 lease |

SearchSession 是本轮查询视图和组合门面，没有成为新的 Agent 调度器。模型调用没有变成另一套 Action 执行循环。Workspace 的专用 matcher、各 owner 的 source 适配保留了真实领域差异，并未导致公开 Search 语义分叉。

### 6.2 用户配置与 Agent 决策已分离

- 用户配置 query 是否使用 Embedding、各操作的 implementation/use/profile、provider 链、预算与允许的 Context。
- Agent 选择已开放的 source、scope、query/anchor、where、criterion、步骤顺序和 page。
- LLM/JEV 的输入构造差异位于公共模型操作中，模型服务不猜测业务 Context。
- Home/Memory 的向量 query 与 similarity 操作复用 owner 的向量用途，不制造另一份语义模型选择。
- Action Schema 从已解析 capability/policy 生成；Endpoint 投影与配置编辑遵循同一对象。
- `action.retrieval` 使用包含完整 Action ID 的原子 map，不把带点 ID 误拆为路径层级。

这些方面已落实。R1 所遗漏的空操作组合现已补齐，继续使用同一 policy、schema 和 parser。

### 6.3 失败和生命周期没有引入第二套语义

可修正的请求、容量和模型输出问题走有限 `SearchFailure`；无法继续的来源 I/O 或不可恢复模型失败保留模块边界处理；取消与总期限服从既有 Action/Turn。单步模型失败不会被静默当成成功跳过，也不会跨 LLM/JEV/Embedding 自动切换实现。

结果快照保存完整最终成员，续接不读盘、不重调模型；result 派生不改旧快照。视图在 Turn/profile 或 SDK lease 范围内生效，owner 的持久文件仍是唯一事实来源。

局部实现中仍可做格式和辅助表达整理，例如几处较长的构造表达式，但本次没有把这类编码美化列成架构阻塞项。不要因此再抽象一个万能检索插件平台。

## 7. 上轮 F1–F4 的闭环判断

| 原问题 | 当前判断 | 依据 |
| --- | --- | --- |
| F1：真实内容、语义命中、候选操作与分页未贯通 | 核心问题已关闭 | ContentUnit/Evidence/Preview、独立召回、统一 selector、完整 SearchViews；混合深层命中与输入映射测试通过 |
| F2：查询子集覆盖完整向量缓存 | 已关闭 | `infra/model_services/vectors.py` 按内容身份保留缓存、跨 scope 合并与有界回收；disjoint scopes/provider 切换测试通过 |
| F3：无效 Memory 引用升级为内部错误 | 已关闭 | owner 的引用归一化与 SearchSession 对 ReferenceError 的局部转换；缺失 seed/document 行为有测试 |
| F4：无消费者 Memory 日报链与旧协议说明 | 已关闭主要问题 | 当前生成资源与活跃代码无旧 memory_daily 消费要求，Search/Reflection 当前设计已同步；历史稿保留历史内容不构成并行实现 |

新增 R1、R2 不应被写回成“F1 整体未完成”，也不应因 F1–F4 已修复而忽略它们。

## 8. 初次独立复核验证（修正前）

环境：Linux、Python 3.13.15；新建隔离环境并安装项目开发依赖。当前环境没有执行 PowerShell 标准脚本，使用了其对应 pytest marker 和 ty 参数；这是本次独立结果，不覆盖仓库原有 Windows 验证记录。

| 验证 | 结果 |
| --- | --- |
| retrieval / model_services / Home / Memory / Workspace / MCP / Session 聚焦测试 | **98 passed, 2 deselected，3.58 秒** |
| `python -m pytest -m 'not external' --durations=10` | **1175 passed, 6 skipped, 25 deselected，80.93 秒** |
| `python -m ty check --python <同一环境 Python>`，ty 0.0.84 | **3 diagnostics**，见 R2 |
| 独立 ty 0.0.57，指向同一 Python 环境 | **All checks passed** |
| 空 operations 的 config → parser → ActionToolSpec 探针 | **稳定复现 R1** |

完整非外部测试包含生成与 wheel 验收；最慢单项为 wheel 构建和隔离安装，14.52 秒，其余前列主要为 Agent/进程集成。没有观察到本轮检索测试导致异常长时间运行；不建议为缩短总耗时删掉关键集成验收，也没有必要在文档改动后重复运行全部测试。

真实 LLM/JEV/Embedding provider 的调用与检索效果本次未运行。已验证的是代码路径、协议、内容映射、组合、配置和替身环境中的行为。模型质量与成本需由代表性真实输入衡量，不能通过增加本地断言来冒充；当前尚未发现因此需要改变核心设计的证据。

## 9. 收尾清单核对

| 项目 | 状态 | 对应实现与证据 |
| --- | --- | --- |
| R1：空操作 policy | done | retrieval schema 修正与公共组合契约测试；来源可独立使用 |
| R2：JSON 类型边界 | done | criteria/scenarios/created_refs 显式 JsonObject；ty 0.0.84 全量通过 |
| 开发环境与检查版本 | done | dev 下限升级、Conda ty 0.0.84、typecheck 输出 Python/ty 版本 |
| 设计与 Endpoint 同步 | done | `docs/design/action-model-retrieval.md`、`docs/endpoint/configuration.md` |
| 必要验证及 review 归档 | done | 聚焦、Fast、Full、typecheck 通过，本文移入 done 并保留初次复核事实 |

复核第 4–7 节的统一管道、真实内容、独立召回、语境选择、Inspect、来源 owner 及生命周期结论，仍与本次实现一致。本次修正没有扩展模型调用或改变结果协议，已确认的 JEV、Reflection 和 Home top 语义保持成立。

## 10. 收尾验证（2026-09-27）

环境：Windows，Conda `TinySoul`，Python 3.13.12，ty 0.0.84（8dd9a7f7f，2026-09-24）。脚本通过 `TINYSOUL_PYTHON` 选择该环境，并使用进程级 ExecutionPolicy Bypass 执行。

| 验证 | 结果 |
| --- | --- |
| 检索、ModelServices、Action catalog/engine、Session organize 聚焦测试 | 81 passed，2.93 秒 |
| `scripts/test.ps1`（Fast） | 1178 passed, 30 deselected，141.46 秒 |
| `scripts/test.ps1 -Suite Full` | 1183 passed, 25 deselected，153.72 秒 |
| `scripts/typecheck.ps1` | 输出 Python 3.13.12 / ty 0.0.84，All checks passed |
| `git diff --check` | passed |

Full 包含生成与 wheel 验收；真实 provider/network 测试本次未运行。本次收尾已逐项核对实现、文档和验证，没有剩余的 R1/R2 待办。

提交建议：`fix: finish search review contracts and upgrade ty`。
