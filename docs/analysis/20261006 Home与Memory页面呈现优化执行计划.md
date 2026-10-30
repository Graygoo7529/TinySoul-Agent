# Home 与 Memory 页面呈现优化执行计划

日期：2026-10-06；2026-10-27 按最新引用与页面实现复核

状态：待逐项确认与实施

范围：`visualization/src/features/home/`、`memory/`、`resources/ReferencesPanel.tsx`、SearchPanel 相关结果行及测试。

**架构前提**：Home/Memory 页面保持只读。持久 Memory 与 actual Home 的写入只属于 Reflection 的受约束服务；本计划不引入编辑/Save、不新增后端端点、不把引用面板变成审核工具。

## 最新基线

- Home 引用已统一为 `home:top|resource|mount/...`，内容页可直接使用真实 ref；
- ReferencesPanel 的 direct refs 已展示 owner 提供的 `title + clue + ref`，backlinks 也已有标题、ref 与 evidence，不能再按旧描述把它们当成“只有机器 ref 的列表”；
- Memory catalog 当前只有 ref/kind/display/status/redirect_to，没有更新时间、大小或摘要；
- Active Memory 已有 Quote in conversation，能够跳转对话并预填 `memory:current`，因此取消重复的“就今日记忆提问”按钮。

## 改进点 1：Memory 五类文档色彩与图标系统

状态：done（2026-10-30）

### 现状与修改

daily/entity/concept/fact/note 在目录和文档头部都使用粉色徽标，类型扫读弱。新建 `features/memory/kindMeta.ts` 作为唯一映射：

| 类型 | 图标 | Badge tone | 中文语义 |
|---|---|---|---|
| daily | CalendarDays | yellow | 日记 |
| entity | User | blue | 实体 |
| concept | Lightbulb | purple | 概念 |
| fact | Pin | green | 事实 |
| note | StickyNote | pink | 便签 |

应用到 MemoryNav 行、MemoryDocumentView 头部、kind tabs 和 Memory 搜索结果行；未知 kind 使用灰色与原值，不猜类型。共享 Tabs 的 label 仅扩展为 React 节点以承载图标，其它 Tab 的呈现与行为不变。完整验证为 98 个测试文件、851 个用例，TypeScript 检查与生产构建通过。

### 预期效果

五类文档在列表、头部、筛选和引用中保持同一视觉语言，机器枚举只在需要精确定位时保留。

## 改进点 2：Memory catalog 状态语义化

状态：done（2026-10-30）

### 修改范围与内容

- 保留当前“active 不额外显示徽标”的克制列表，不给每行增加绿色噪声；
- redirect 与非 active 状态显示中文语义和适宜色调，未知枚举保留原值；
- 不添加更新时间、大小或首段摘录：catalog 没有这些字段，本计划不新增请求或端点；
- display 继续作为主标题，完整 ref 留在 title/复制入口。

实施映射：merged 为已合并、superseded 为已被取代、retracted 为已撤回，redirect_to 独立显示为重定向；active 目录不显示状态徽标，文档头部复用同一 memoryStatusMeta，未知状态使用灰色原值。完整验证为 98 个测试文件、854 个用例，TypeScript 检查与生产构建通过。

### 预期效果

状态可读且不稀释主标题；每行仍只表达 catalog 真正拥有的事实。

## 改进点 3：引用呈现语义化

### 修改范围与内容

- direct refs 保留 owner 提供的 title 作为主文本、clue 作为辅助说明、完整 ref 作为精确定位，**不得用 ref 末段覆盖 title/clue**；
- backlinks 保留 title/ref/evidence，增加与 Memory kind 或 Home/Workspace 命名空间一致的淡色图标；
- copy/quote 和现有 ResourceRouter 导航保持；区标题与空态中文化；
- LinkChip 若复用，按当前 `resourceRef` prop 签名，不恢复旧 link 字段。

### 预期效果

引用从“可用但朴素”提升为类型可辨的知识条目，同时保留 owner 对标题与线索的解释权。

## 改进点 4：Home overlay 状态渗透目录

状态：done（2026-10-30）

### 修改范围与内容

- Changes 按钮在已读取 changes 后显示计数；首屏不额外请求，打开 Changes 后计数常驻，ReflectionDialog 已取得 home_change_count 时可同步；
- 将已加载的 changes 集合提升到 useHomePage，DirectoryRow 对实际匹配 ref 显示 created/modified/deleted/diverged 状态点；
- 点击状态点调用现有 openDiff 直达对应 diff；未读取 changes 时不显示、不伪造；
- effective 中不存在的 deleted 项不制造目录行，仍可从 Changes 列表读取。

实施验证：首屏无 Changes 请求；打开后显示计数，返回目录仍保留状态点；created/modified/deleted 与 baseline_diverged 分开呈现，状态点复用 openDiff。98 个测试文件、852 个用例，TypeScript 检查与生产构建通过。

### 预期效果

overlay 不再只藏在独立面板里；目录能定位有变化的资源，同时不增加首屏数据请求。

## 改进点 5：Home/Memory 内容头部去重

状态：done（2026-10-30）

### 修改范围与内容

- Home 标题优先使用当前正文的 frontmatter title 或首个 H1；没有可读标题时，mount domain/action 使用对应路径，其它资源使用 ref 末段，未知 ref 保留原值，不新增请求；
- `Skill`、`Agent`、`域指导`、`动作指导` 作为独立徽章放在标题旁，不再把 skills/agent 或指导类型拼成标题前缀；完整 ref 收为辅助 chip，effective/actual 徽标保留；
- Memory 保留 owner display 为主标题，kind/status 使用改进点 1、2 的映射，完整 ref 降级为辅助 chip；
- 文档正文与 redirect 提示不变。

实施验证：frontmatter/H1、mount 回退、独立徽章和 ref chip 均有回归覆盖；98 个测试文件、853 个用例，TypeScript 检查与生产构建通过。

### 预期效果

头部先回答“这是什么”，机器引用仍可复制但不再与标题重复抢占注意力。

## 改进点 6：diff 视图的聚焦整理入口

- HomeDiffView 增加次级按钮“就这条发起整理”，打开现有 ReflectionDialog kind=home，并通过可选 initialText 预填聚焦当前 ref 的说明；
- 仅预填用户可编辑的 instructions，提交仍走现有 POST /v2/reflection，不新增写权限或 review token；
- diverged、actual/effective 差异和只读语义保持不变。

预期效果：从发现可疑 overlay 到发起聚焦整理少一次手工描述，审核仍完全归 Reflection。

## 改进点 7：Memory 单文档关系图（ego graph）

### 数据与边界

只使用文档 DisclosurePage items 中的 direct refs 与显式 memory.search backlinks；它们都是真实引用边。不做相似度猜边、不标注后端未提供的边类型、不建设全局 force 图谱。

### 修改范围与内容

- ReferencesPanel 仅在 `actionId="memory.search"` 时增加 List / Graph 切换，默认 List；Home 继续只有现有列表，不获得额外图谱入口；
- 新增 `MemoryGraph.tsx`，纯 SVG，不引入 d3/react-flow：当前文档居中，左列为引用它的文档、右列为它引用的文档，方向与真实边一致；
- 节点复用 kindMeta 图标/色调，跨到 Home/Workspace 的邻居使用对应命名空间图标；中心与邻居优先使用 owner title/display，clue 可作辅助，完整 ref 收 title；
- 点击邻居沿 ResourceRouter 打开并以新文档为中心重建；hover 只高亮真实边与对端；
- 每侧最多 12 个节点，超出为 `+N 更多` 并展开该侧列表；
- Graph 首次需要 backlinks 时才发起查询，已查询结果可复用；空态直接说明无引用边，不画空图。

### 预期效果

用户能看到一篇知识在局部关系网中的位置并沿边漫游；列表服务阅读，图谱服务结构判断，二者共享同一份事实。

## 实施顺序与验收

顺序：1 → 4+5 → 2+3 → 6 → 7。

- 五类文档与状态在所有入口一致，active 列表不过度着色；
- direct refs 的 title/clue 不丢失，catalog 不虚构元信息；
- Home changes 计数和目录状态只来自已加载事实；
- diff 可聚焦整理，仍无前端直接审核/编辑；
- 图谱数据仅来自 direct refs/backlinks，邻接可导航、有界、无伪边；
- `npx tsc --noEmit` 与 `npx vitest run` 通过。

边界：不新增 Active Memory 提问按钮（现有 Quote 已覆盖）；不改读取、分页、Search 能力声明或 Reflection 提交链路；不做全局知识图谱。
