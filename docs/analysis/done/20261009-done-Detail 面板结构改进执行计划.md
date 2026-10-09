# Detail 面板（Turn Trace）结构改进执行计划

日期：2026-10-09

状态：**done**（2026-10-09 实施完成，tsc + 全部 807 前端测试通过）

范围：`visualization/src/features/trace/ProcessPanel.tsx`。只改面板结构与 Cycle 折叠卡呈现，不动事件读取、facts 关联与 Inspector 机制。

## 目标

Turn Trace 面板当前是单长列（Overview → Working Context → Cycle 树 → Jobs → Activity），Cycle 折叠卡只有"Cycle N + 耗时 + N actions"一行，不含语义。本计划给面板加顶部两栏结构，并让折叠的 Cycle 卡自身就能回答"这个 Cycle 做了什么、成败如何"。

---

## 改进点 1：顶部两栏切换（概览 / 过程）

### 现状分析

所有内容串在一条长列里：Overview 与 Working Context 之后是 ProcessTree，Activity 时间线在最底部（Collapsible）——概览信息与过程细节混排，长 turn 时需要长距离滚动。

### 修改范围与内容

- 面板顶部状态行（`finished · Export trace…` 行）加入分段切换栏：**概览 / 过程** 两个 tab（等宽文字，选中态沿用 Tabs 组件或同级样式）；
- **概览**（默认栏）：Overview + Working Context + Activity 三个同级卡片；Activity 从底部 Collapsible 升级为同级卡片（抬头同 Working Context 的 SectionCard 样式），**默认有界高度 + "展开全部 N 条"**，过滤芯片与 phase 组头保持现状；
- **过程**：ProcessTree（Cycle 树）+ Jobs + unscoped/searches/other model tasks 散段；
- Export 保留在切换栏右侧。

### 预期效果

打开面板默认看到"规模/成本/工作上下文/活动流"的概览一屏；要追过程切到"过程"栏。两个栏目各司其职，不再长滚。

---

## 改进点 2：Cycle 折叠卡两行摘要

### 现状分析

折叠的 Cycle 卡只有 `Cycle N + 耗时 + N actions`——扁、且完全看不出这个 Cycle 做了什么、成败如何。

### 修改范围与内容

折叠卡升级为标题行 + 两行摘要：

```
▸ Cycle 2                                    7.4s · 1 action
  搜索 2026-10-09 上海天气并写入工作区记录…     ← 意图行
  ● ● ●   ✓ web.search · ✓ workspace.write   ← 相位光点 + 关键动作
```

1. **意图行**：取该 Cycle phase1 的 select intent（`select_action_domains` 的 arguments.intent），备选 phase1 首个 reasoning 首行；两者都没有时**保留行占位、不坍塌高度**（卡片高度一致，列与列对齐）；
2. **相位光点**：三个小圆点依次代表 phase1/2/3，按状态着色（成功绿 / 失败红 / 未运行灰），不用勾和 p1 符号；悬停 title 显示 `phase1 · 更新语境并选择行动域`（复用 `phaseHint`）；
3. **关键动作**：最多 2 个动作名 + 状态图标（复用 ActionRow 的状态图标语义）；
4. **失败 Cycle 不加红边框、不内联失败原因**——相位光点与关键动作已承载状态信息；
5. 数据来源全部现有（phases 的 controls/reasoning/status、actions），无新增数据通道。

### 预期效果

不展开任何卡片就能扫读整轮过程：每个 Cycle 一行意图知道"它要做什么"，三个光点知道"跑到哪、败在哪"，动作名列出"做了什么"。

---

## 实施与验收

一次实施，顺序：1（两栏结构）→ 2（Cycle 卡）。

验收标准：

1. 顶部有 概览/过程 切换栏，默认概览；Activity 为同级卡片、有界可全展开；过程栏含 Cycle 树与散段；Export 在位；
2. Cycle 折叠卡显示意图行（无意图时占位不塌）、三个相位光点、≤2 个关键动作；失败 Cycle 无红光边框；
3. 全部测试通过（tsc + vitest），受影响断言同步更新。
