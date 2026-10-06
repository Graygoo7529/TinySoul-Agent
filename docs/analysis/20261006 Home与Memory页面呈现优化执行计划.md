# Home 与 Memory 页面呈现优化执行计划

日期：2026-10-06

状态：待逐项确认与实施

范围：`visualization/src/features/home/`（HomePage.tsx、HomeDirectory.tsx、HomeContentView.tsx、HomeChanges.tsx）、`visualization/src/features/memory/`（MemoryNav.tsx、MemoryDocumentView.tsx、ActiveMemoryView.tsx）、`visualization/src/features/resources/ReferencesPanel.tsx`。

**架构前提（不可逾越）**：Home/Memory 页面是**只读**呈现——持久 Memory 与 actual Home 的写入只属于 Reflection 的受约束服务，日常修改走对话。本计划不引入任何编辑/Save 能力、不新增后端端点；所有改进为纯前端呈现与导航增强。

## 目标

Home 持有身份、偏好、Skill 与行动指导；Memory 持有活动记忆与五类持久知识文档。两页的功能链路（目录/内容/变更/diff/引用/整理入口）已经完整，但呈现层是"裸数据直出"：五类文档视觉零区分、目录行无元信息、overlay 改动不渗透目录、引用关系是一串等宽 ref。本计划让两页的信息层次与图形语义配得上其数据模型的完整度。

---

## 改进点 1：Memory 五类文档色彩与图标系统

### 现状分析

`features/memory/MemoryNav.tsx:238`：daily/entity/concept/fact/note 五类文档的 kind 徽标**全部粉色**（`<Badge tone="pink">{item.kind}</Badge>`），无图标、无色彩区分；`MemoryDocumentView.tsx` 头部同样处理。用户无法在列表中扫读文档类型。

### 修改范围与内容

- 新建 `features/memory/kindMeta.ts`（单一来源）：

| 类型 | 图标（lucide） | Badge tone | 语义 |
|---|---|---|---|
| daily | CalendarDays | yellow | 按日的记录 |
| entity | User | blue | 人与项目 |
| concept | Lightbulb | purple | 概念与模式 |
| fact | Pin | green | 事实与引用 |
| note | StickyNote | pink | 便签 |

  导出 `memoryKindMeta(kind): { Icon, tone, label }`（label 中文：日记/实体/概念/事实/便签；未知 kind 灰 fallback）。
- 应用到四处：`MemoryNav.tsx` 行徽标（图标+中文 label，替代纯粉色原值）、`MemoryDocumentView.tsx` 头部、Memory 页 kind tabs（All/Daily/… 切换处）、SearchPanel 在 memory 域的结果行（结果行组件若共享则自动获得，不共享则单独应用）。

### 预期效果

列表扫读时类型一眼可辨（黄日记、蓝实体、紫概念、绿事实、粉便签）；kind 语义从机器枚举变成中文词 + 图标。

---

## 改进点 2：Memory catalog 行元信息与 status 语义化

### 现状分析

`MemoryNav.tsx` 目录行只有 display 名 + redirect 徽标 + 裸 status 枚举字符串（:236 `<Badge tone="gray">{item.status}</Badge>`）；无日期、无大小、无摘录。

### 修改范围与内容

`MemoryNav.tsx` 行组件：

- status 枚举翻译为语义词：active→"生效中"（绿）、其余状态灰色中文词（归档/重定向等按实际枚举值映射，未知值原样）；redirect 徽标保留橙色；
- 行内追加元信息小字：daily 显示日期（名字本身即日期，不重复）；其余类型显示 catalog 提供的更新时间/大小字段（**先核实 catalog item 载荷里实际有哪些字段**，有则显示，无则不加——不向后端要新字段）；
- 行 hover 显示一行摘录 tooltip（从文档首段推导需要额外请求，成本高——**不做**；仅在 catalog 已带摘要字段时显示，否则省略）。

### 预期效果

每行能读出"类型 + 状态 + 时间/规模"；裸枚举消失。

---

## 改进点 3：引用呈现语义化（ReferencesPanel）

### 现状分析

`features/resources/ReferencesPanel.tsx:165-196`："It references"（direct refs）与 backlinks 都是等宽 ref 字符串按钮 + copy/quote 图标——`memory:entity/tinysoul` 这类机器标识是行的全部内容，无语义标题、无类型提示。

### 修改范围与内容

`ReferencesPanel.tsx`（Home 与 Memory 共用此面板，改动两处同时受益）：

- ref 行升级为 LinkChip 风格：按 ref 命名空间给图标（workspace→FileText、home→Home、memory→MemoryStick，memory 再按路径段细分五类图标——复用改进点 1 的 kindMeta）；显示文本为语义名（取 ref 末段，如 `entity/tinysoul` → `tinysoul`），完整 ref 收 title；
- copy/quote 图标按钮保留在行尾；
- backlinks 区同样处理；空态文案中文化（"暂无引用"）。

### 预期效果

引用列表从机器 ref 串变成"带类型图标的语义条目"，扫读与点击导航都更直接。

---

## 改进点 4：Home overlay 状态渗透目录

### 现状分析

- 哪些条目被 overlay 改过，只能切到 Changes 面板对照；header 的 "Changes" 按钮（`HomePage.tsx:126-135`）**无计数徽标**——用户无法一眼知道有待审改动（数量只在 ReflectionDialog 里出现）；
- HomeChanges 面板每行已有 created/modified/deleted 三色徽标与 diverged 标记（`HomeChanges.tsx`，KIND_TONES green/yellow/red）——数据通道是现成的 `/v2/home/changes`。

### 修改范围与内容

- `HomePage.tsx`：Changes 按钮加计数徽标（`Changes 3`）。计数来源：HomeChanges 已用 `usePagedSequence` 读 changes——将 changes 计数提升到 store（`useHomePage` 增加 `changeCount`），由 HomeChanges 的读取结果写入；首屏不主动读 changes（保持懒加载），但在用户开过 Changes 面板后计数常驻；ReflectionDialog 打开时已知 pending overlay 数，也同步写入该计数。
- `HomeDirectory.tsx` DirectoryRow：对存在于 changes 集合中的 link，行右侧加状态点（绿 created/黄 modified/红 deleted/橙 diverged，复用 KIND_TONES），点击状态点直接打开对应 diff（`useHomePage.getState().openDiff(link)`，机制已有）；changes 集合同样来自提升后的 store，目录行在未读 changes 时不显示点（不伪造）。

### 预期效果

有待审改动时 header 直接报数；目录里被改的条目有颜色标记，一点直达 diff——overlay 状态从"藏在另一个面板"变成目录的一层信息。

---

## 改进点 5：Home 内容头部去重

### 现状分析

`HomeContentView.tsx:85-91`：标题是 `link.replace(/^home:/,"")`，下一行又放完整等宽 link——两行几乎同一字符串，raw link 对读者是噪声。

### 修改范围与内容

`HomeContentView.tsx` 头部：

- 标题只保留语义名（`home:agent@identity` → `agent · identity`；`home:skills_domain:workspace` → `域指导 · workspace`；解析函数放 `home/catalogModel.ts` 或组件内小函数）；
- 完整 link 收进头部右侧的 ref chip（等宽小字 + 复制按钮，复用 copyReference）；view 徽标（effective/actual）保留；
- MemoryDocumentView 头部同样检查：`display` + 等宽 link 两行是否重复，重复则同样收口。

### 预期效果

头部一行读懂"这是什么"，机器标识降级为可复制的小 chip。

---

## 改进点 6：diff 视图的聚焦整理入口

### 现状分析

HomeDiffView 只读（设计如此），diverged 横幅有说明文字但无可点击出口；唯一行动是 header 的 "Organize Home" 自由文本指令，用户需要自己描述"整理哪条"。

### 修改范围与内容

- `HomeDiffView.tsx`：头部增加一个次级按钮"就这条发起整理"——打开 `ReflectionDialog kind="home"` 并预填 instructions 为 `请聚焦 review <link> 的改动`（ReflectionDialog 已有 instructions 文本框，增加一个可选 initialText prop）；
- 不新增任何写权限与后端调用——仍走现有 `POST /v2/reflection` 提交流程。

### 预期效果

从"看到一条可疑改动"到"发起聚焦整理"一次点击；review 闭环仍完全由 Reflection 持有。

---

## 改进点 7：Memory 单文档关系图（ego graph 第一期）

### 现状分析

引用/backlinks 只能在 ReferencesPanel 浮层里以列表读（改进点 3 语义化后仍是列表）；"这条知识与哪些知识相连"没有结构性呈现。数据通道已存在且够用：文档 `metadata.direct_refs`（它引用了谁，免费随文档返回）与 memory search 的 backlinks 来源（谁引用了它，现有"显式点击才查"的许可语义）。

### 修改范围与内容

- `ReferencesPanel.tsx`：头部增加 List / Graph 分段切换（默认 List）；
- 新增 `features/memory/MemoryGraph.tsx`（纯 SVG 手绘，**不引入 d3/react-flow 等任何新依赖**）：
  - 布局：当前文档居中节点，左列"谁引用了它"（backlinks，入边指向中心），右列"它引用了谁"（direct refs，出边指出）；
  - 节点：圆角块 + 改进点 1 的 kind 图标/色调 + 语义标题（ref 末段），完整 ref 收 title；
  - 边：细线带方向；hover 高亮整条边与对端节点；
  - 交互：点击邻居节点经 ResourceRouter 跳转该文档，图谱以新文档为中心重建（浏览即沿引用漫游）；
  - 有界：每侧最多 12 个节点，超出折叠为 `+N 更多` 计数节点（点击展开该侧列表）；
  - 许可：切到 Graph 模式才发起 backlinks 查询（与面板现状一致），direct refs 免费；
  - 空态：两边都无引用时显示"该文档暂无引用边"，不画空图；
- 语义红线：只呈现真实引用边（direct_refs + backlinks），不做词法猜测、不做"相似文档"伪边、不做边类型标注（后端引用边不携带类型）。

### 预期效果

读任何一条 memory 都能一眼看到它在知识网中的位置，并沿边漫游到相关文档；图谱与列表两种视图服务不同阅读习惯。全局知识图谱（全量节点 force layout）**不在本计划内**——它需要后端全量引用边通道，届时单独评估立项。

---

## 改进点 8：Active Memory 快捷提问入口

### 现状分析

Active Memory 视图（`ActiveMemoryView.tsx`）只读，操作只有 copy/quote `memory:current`；空库空态已有 "Start a conversation" 的真实下一步（好设计），但读到内容后没有"就此提问/补充"的快捷路径。

### 修改范围与内容

`ActiveMemoryView.tsx` 头部操作区增加一个次级按钮"就今日记忆提问"：跳转 chat tab 并向 Composer 预填对 `memory:current` 的引用（复用 `quoteReference`，机制已存在）——与 copy/quote 并列，不改变只读语义。

### 预期效果

从"读到今日记忆"到"就此与 agent 对话"一次点击，与空态的 "Start a conversation" 形成完整回路。

---

## 实施顺序与验收

建议顺序：1（kind 系统，2/3/7 依赖）→ 4+5（Home 侧）→ 2+3（Memory 列表与引用）→ 6+8（小入口）→ 7（ego graph，最重，放最后）。

验收标准：

1. 五类文档在列表/头部/tabs/搜索结果中图标与色彩一致；kind 全中文；
2. status 无语义裸枚举；行元信息按 catalog 实际字段显示；
3. 引用行为图标+语义条目，ref 收 title；
4. Changes 按钮有计数（开过面板后常驻）；目录改动条目有状态点且点击直达 diff；
5. Home/Memory 内容头部无重复 link 行；
6. diff 视图可一键发起聚焦整理（预填 instructions）；
7. ReferencesPanel 有 Graph 模式；ego graph 纯 SVG、数据只来自 direct_refs/backlinks、邻居可点击漫游、超界折叠；
8. Active Memory 头部有"就今日记忆提问"。

边界：两页保持全只读；不改 catalog/content/changes/diff 的读取与分页逻辑；不动 ReflectionDialog 的提交链路（仅加 initialText prop）；不动 SearchPanel 的能力声明机制。
