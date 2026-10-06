# visualization Home 与 Memory 可视化优化执行计划

**状态**：待执行  
**创建日期**：2026-10-05  
**修订日期**：2026-10-06  
**预计工作量**：2.5 个工作日  
**负责人**：Claude Opus 5.5

---

## 执行计划总览

本计划旨在优化 Home 和 Memory 资源的可视化呈现，提供关系图谱和快速导航，严格遵守 AGENTS.md 设计边界。

**核心原则**：
- 尊重架构边界：前端不提供 actual Home 或持久 Memory 编辑功能
- 只读可视化：增强展示和导航，不增加编辑
- 符合设计语义：编辑通过 Settings 或 Reflection（受约束）
- 真实增量：Memory 关系图谱、Home 资源导航

**修订说明**：
原计划包含 Home 资源内联编辑功能，违反 AGENTS.md 设计边界。本版本去掉违规功能，保留合理的可视化增强。

---

## 背景分析

### AGENTS.md 设计边界

**Home 的设计语义**：
```
Home 持有身份规约、用户偏好、通用 Skill 和行动指导。
actual Home 是已接受基线；普通 Turn 的修改写入跨日 runtime overlay，
形成 effective Home，只有 Home Reflection 的受约束 review 服务
能接受回 actual Home。
```

**关键约束**：
- ✅ 普通对话可以**读取** effective Home（actual + overlay）
- ❌ 普通对话**不能编辑** actual Home
- ✅ 可以通过 Settings 编辑（配置入口）
- ✅ 可以通过 Home Reflection 编辑（受约束 review）

**Memory 的设计语义**：
```
Memory 持有活动 Memory.md、五类持久 Markdown、Link/codec、catalog、
backlinks 与可重建 embedding cache。普通 Turn 在 memory 域通过
memorize 原子 patch 活动记忆、search 发现候选、inspect 读取已知
文档内容和 direct refs；只有 Memory Reflection 的写服务可提交
持久文档。
```

**关键约束**：
- ✅ 普通对话可以 search/inspect Memory
- ✅ 普通对话可以 memorize（patch 活动 Memory.md）
- ❌ 普通对话**不能提交**持久文档（daily/entity/concept/fact/note）
- ✅ 可以通过 Memory Reflection 提交持久文档（受约束）

### 前端的合理职责

基于上述约束，前端应该：

**Home 前端**：
- ✅ 展示 effective Home 资源（只读）
- ✅ 提供快速导航到 Settings（编辑入口）
- ❌ 不提供内联编辑功能

**Memory 前端**：
- ✅ 展示活动 Memory.md 和持久文档（只读）
- ✅ 提供 search 和 backlinks 可视化
- ✅ 提供关系图谱
- ❌ 不提供持久文档编辑功能

---

## 阶段一：Home 资源展示优化（只读）

**目标**：优化 Home 资源的展示，提供快速导航到 Settings。

### 1.1 创建 Home 独立页面

新建文件：`visualization/src/features/home/HomePage.tsx`

**功能设计**：

1. **左右分栏布局**：
   - 左侧：资源列表（分类浏览）
   - 右侧：Markdown 内容展示

2. **资源分类**：
   - Identity（身份规约）
   - Preferences（用户偏好）
   - Skills（通用技能）
   - Guidance（行动指导）

3. **只读展示**：
   - 无编辑按钮
   - 底部提示只读
   - 可写资源显示"在 Settings 中编辑"按钮

4. **快速导航**：
   - 点击"在 Settings 中编辑"跳转到 Settings Home 页面
   - 符合架构设计（编辑通过 Settings）

**核心代码结构**：

```typescript
import { useState, useEffect } from "react";
import { FileText, Settings, ExternalLink } from "lucide-react";
import { Markdown } from "../../components/Markdown";
import { useNavigate } from "react-router-dom";

interface HomeResource {
  link: string;          // home:agent@identity
  title: string;
  content: string;
  category: string;      // identity / preferences / skills / guidance
  writable: boolean;     // 是否可通过 Settings 编辑
}

export function HomePage() {
  const [resources, setResources] = useState<HomeResource[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  
  useEffect(() => {
    async function loadHome() {
      setLoading(true);
      try {
        const response = await fetch("/api/v2/home");
        const data = await response.json();
        setResources(data.resources);
        setSelected(data.resources[0]?.link ?? null);
      } catch (error) {
        console.error("Failed to load Home:", error);
      } finally {
        setLoading(false);
      }
    }
    loadHome();
  }, []);
  
  const current = resources.find(r => r.link === selected);
  
  return (
    <div className="flex h-full">
      {/* 左侧资源列表 */}
      <div className="w-64 border-r border-fg-faint/10 flex flex-col">
        <div className="px-4 py-3 border-b border-fg-faint/10">
          <h2 className="text-sm font-medium">Home Resources</h2>
          <p className="text-[10px] text-fg-faint mt-0.5">
            身份、偏好、技能与指导
          </p>
        </div>
        
        <div className="flex-1 overflow-auto p-2 space-y-1">
          {resources.map(resource => (
            <button
              key={resource.link}
              onClick={() => setSelected(resource.link)}
              className={`
                w-full text-left px-3 py-2 rounded-lg
                transition-colors text-xs
                ${selected === resource.link 
                  ? "bg-accent/10 text-accent" 
                  : "hover:bg-fg-faint/5 text-fg-base"}
              `}
            >
              <div className="flex items-center gap-2">
                <FileText size={12} className="shrink-0" />
                <span className="flex-1 truncate">{resource.title}</span>
              </div>
              <div className="text-[10px] text-fg-faint mt-0.5">
                {resource.category}
              </div>
            </button>
          ))}
        </div>
        
        {/* 底部说明 */}
        <div className="px-4 py-3 border-t border-fg-faint/10 bg-surface-2">
          <p className="text-[10px] text-fg-faint leading-relaxed">
            💡 Home 资源只读展示。如需编辑，请前往 Settings 或使用 Home Reflection。
          </p>
        </div>
      </div>
      
      {/* 右侧内容展示 */}
      <div className="flex-1 flex flex-col">
        {current ? (
          <>
            {/* 标题栏 */}
            <div className="px-6 py-4 border-b border-fg-faint/10 flex items-center gap-3">
              <div className="flex-1">
                <h3 className="text-base font-medium">{current.title}</h3>
                <p className="text-xs text-fg-faint mt-0.5">{current.link}</p>
              </div>
              
              {/* 导航到 Settings */}
              {current.writable && (
                <button
                  onClick={() => navigate("/settings/editors/home")}
                  className="
                    flex items-center gap-1.5 px-3 py-1.5 text-xs
                    bg-accent/10 hover:bg-accent/20
                    border border-accent/30 rounded-lg
                    text-accent transition-colors
                  "
                >
                  <Settings size={12} />
                  在 Settings 中编辑
                  <ExternalLink size={10} />
                </button>
              )}
            </div>
            
            {/* Markdown 内容 */}
            <div className="flex-1 overflow-auto px-6 py-4">
              <Markdown
                className="prose prose-sm prose-invert max-w-none"
                origin={{ type: "home", link: current.link }}
              >
                {current.content}
              </Markdown>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-fg-faint">
            {loading ? "加载中..." : "选择一个 Home 资源查看"}
          </div>
        )}
      </div>
    </div>
  );
}
```

### 1.2 后端支持检查

**需要确认**：后端是否已有 `/api/v2/home` 接口？

**如果不存在**，需要在后端增加：

```python
# tinysoul/gateway/endpoint/home_routes.py
@router.get("/home")
async def get_home_resources():
    """获取 effective Home 资源列表（只读）"""
    # 从 Home Plugin 获取 effective Home
    home = get_effective_home()
    
    return {
        "resources": [
            {
                "link": resource.link,
                "title": resource.title,
                "content": resource.content,
                "category": resource.category,
                "writable": is_writable_in_settings(resource.link)
            }
            for resource in home.all_resources()
        ]
    }
```

**改动文件**：
- `visualization/src/features/home/HomePage.tsx`（新建约 150 行）
- `visualization/src/App.tsx`（添加路由）
- `tinysoul/gateway/endpoint/home_routes.py`（可能需要新建约 30 行）

**验收标准**：
- [ ] Home 页面显示所有 Home 资源
- [ ] 左侧列表，右侧内容
- [ ] 只读展示（无编辑功能）
- [ ] 可写资源显示"在 Settings 中编辑"按钮
- [ ] 点击按钮跳转到 Settings Home 页面
- [ ] Markdown 正确渲染
- [ ] 底部说明提示只读

**工作量**：1 天

---

## 阶段二：Memory 关系图谱

**目标**：可视化 Memory 的引用关系，支持交互式探索。

### 2.1 安装依赖

使用 react-force-graph-2d 实现力导向图：

```bash
npm install react-force-graph-2d
```

### 2.2 创建 MemoryGraphView 组件

新建文件：`visualization/src/features/memory/MemoryGraphView.tsx`

**功能设计**：

1. **力导向图**：
   - 节点：Memory 文档（daily/entity/concept/fact/note）
   - 边：引用关系（cites/mentions/relates）
   - 自动布局（力导向算法）

2. **节点视觉编码**：
   - 颜色：按文档类型区分
   - 大小：按被引用次数（入度）
   - 标签：文档标题

3. **交互功能**：
   - 点击节点：显示详情
   - 拖拽节点：调整布局
   - 缩放/平移：探索大图

4. **侧边详情面板**：
   - 显示选中节点的完整内容
   - 显示入边/出边列表
   - 提供导航到相关节点

**核心代码结构**：

```typescript
import { useEffect, useState, useCallback } from "react";
import ForceGraph2D from "react-force-graph-2d";

interface MemoryNode {
  id: string;           // memory:entity/alice
  type: "daily" | "entity" | "concept" | "fact" | "note";
  label: string;        // Alice
  content?: string;     // 预览
}

interface MemoryLink {
  source: string;       // 引用来源
  target: string;       // 引用目标
  type: "cites" | "mentions" | "relates";
}

interface MemoryGraph {
  nodes: MemoryNode[];
  links: MemoryLink[];
}

export function MemoryGraphView() {
  const [graph, setGraph] = useState<MemoryGraph>({ nodes: [], links: [] });
  const [selectedNode, setSelectedNode] = useState<MemoryNode | null>(null);
  const [loading, setLoading] = useState(true);
  
  useEffect(() => {
    async function loadGraph() {
      setLoading(true);
      try {
        const response = await fetch("/api/v2/memory/graph");
        const data = await response.json();
        setGraph(data);
      } catch (error) {
        console.error("Failed to load memory graph:", error);
      } finally {
        setLoading(false);
      }
    }
    loadGraph();
  }, []);
  
  // 节点颜色
  const getNodeColor = useCallback((node: MemoryNode) => {
    const colors = {
      daily: "#60a5fa",      // 蓝色
      entity: "#34d399",     // 绿色
      concept: "#a78bfa",    // 紫色
      fact: "#fbbf24",       // 黄色
      note: "#f87171",       // 红色
    };
    return colors[node.type] || "#9ca3af";
  }, []);
  
  // 节点大小（根据入度）
  const getNodeSize = useCallback((node: MemoryNode) => {
    const inDegree = graph.links.filter(l => l.target === node.id).length;
    return 4 + Math.min(inDegree * 2, 12);
  }, [graph.links]);
  
  // 点击节点
  const handleNodeClick = useCallback((node: MemoryNode) => {
    setSelectedNode(node);
  }, []);
  
  return (
    <div className="flex h-full">
      {/* 图谱主区域 */}
      <div className="flex-1 relative bg-surface-1">
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center text-fg-faint">
            加载关系图谱...
          </div>
        ) : (
          <ForceGraph2D
            graphData={graph}
            nodeLabel="label"
            nodeColor={getNodeColor}
            nodeRelSize={6}
            nodeVal={getNodeSize}
            linkColor={() => "rgba(156, 163, 175, 0.3)"}
            linkWidth={1}
            linkDirectionalParticles={2}
            linkDirectionalParticleWidth={2}
            onNodeClick={handleNodeClick}
            backgroundColor="rgb(5, 7, 12)"
            nodeCanvasObject={(node, ctx, globalScale) => {
              const label = (node as MemoryNode).label;
              const fontSize = 12 / globalScale;
              ctx.font = `${fontSize}px Sans-Serif`;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillStyle = "rgba(255, 255, 255, 0.8)";
              ctx.fillText(label, node.x!, node.y! + 12);
            }}
          />
        )}
        
        {/* 图例 */}
        <div className="absolute top-4 left-4 bg-surface-2 rounded-lg p-3 border border-fg-faint/10">
          <div className="text-xs font-medium mb-2">文档类型</div>
          <div className="space-y-1 text-[10px]">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#60a5fa" }} />
              <span>Daily</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#34d399" }} />
              <span>Entity</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#a78bfa" }} />
              <span>Concept</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#fbbf24" }} />
              <span>Fact</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#f87171" }} />
              <span>Note</span>
            </div>
          </div>
        </div>
      </div>
      
      {/* 侧边详情面板 */}
      {selectedNode && (
        <NodeDetailPanel
          node={selectedNode}
          graph={graph}
          onClose={() => setSelectedNode(null)}
          onNavigate={setSelectedNode}
        />
      )}
    </div>
  );
}

// 节点详情面板
function NodeDetailPanel({ 
  node, 
  graph, 
  onClose, 
  onNavigate 
}: {
  node: MemoryNode;
  graph: MemoryGraph;
  onClose: () => void;
  onNavigate: (node: MemoryNode) => void;
}) {
  const inLinks = graph.links.filter(l => l.target === node.id);
  const outLinks = graph.links.filter(l => l.source === node.id);
  
  return (
    <div className="w-96 border-l border-fg-faint/10 flex flex-col bg-surface-2">
      {/* 标题栏 */}
      <div className="px-4 py-3 border-b border-fg-faint/10 flex items-center gap-2">
        <div className="flex-1">
          <h3 className="text-sm font-medium">{node.label}</h3>
          <p className="text-[10px] text-fg-faint mt-0.5">{node.id}</p>
        </div>
        <button onClick={onClose} className="p-1 hover:bg-surface-3 rounded">
          <X size={14} />
        </button>
      </div>
      
      {/* 内容 */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {node.content && (
          <div>
            <div className="text-xs font-medium mb-2">内容预览</div>
            <div className="text-xs text-fg-faint leading-relaxed">
              {node.content}
            </div>
          </div>
        )}
        
        {/* 入边（被引用） */}
        {inLinks.length > 0 && (
          <div>
            <div className="text-xs font-medium mb-2">
              被引用 ({inLinks.length})
            </div>
            <div className="space-y-1">
              {inLinks.map((link, i) => {
                const sourceNode = graph.nodes.find(n => n.id === link.source);
                return sourceNode ? (
                  <button
                    key={i}
                    onClick={() => onNavigate(sourceNode)}
                    className="w-full text-left px-2 py-1 text-xs hover:bg-surface-3 rounded"
                  >
                    ← {sourceNode.label}
                  </button>
                ) : null;
              })}
            </div>
          </div>
        )}
        
        {/* 出边（引用） */}
        {outLinks.length > 0 && (
          <div>
            <div className="text-xs font-medium mb-2">
              引用 ({outLinks.length})
            </div>
            <div className="space-y-1">
              {outLinks.map((link, i) => {
                const targetNode = graph.nodes.find(n => n.id === link.target);
                return targetNode ? (
                  <button
                    key={i}
                    onClick={() => onNavigate(targetNode)}
                    className="w-full text-left px-2 py-1 text-xs hover:bg-surface-3 rounded"
                  >
                    → {targetNode.label}
                  </button>
                ) : null;
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

### 2.3 后端支持检查

**需要确认**：后端是否已有 `/api/v2/memory/graph` 接口？

**如果不存在**，需要在后端增加：

```python
# tinysoul/gateway/endpoint/memory_routes.py
@router.get("/memory/graph")
async def get_memory_graph():
    """获取 Memory 关系图谱"""
    # 从 Memory Plugin 获取所有持久文档和引用关系
    memory = get_memory_plugin()
    
    nodes = []
    links = []
    
    # 收集所有文档节点
    for doc_type in ["daily", "entity", "concept", "fact", "note"]:
        for doc in memory.list_documents(doc_type):
            nodes.append({
                "id": doc.link,
                "type": doc_type,
                "label": doc.title,
                "content": doc.preview  # 前 200 字符
            })
    
    # 收集引用边
    for doc in memory.all_documents():
        for ref in doc.outbound_refs:
            links.append({
                "source": doc.link,
                "target": ref.target,
                "type": ref.type
            })
    
    return {"nodes": nodes, "links": links}
```

**改动文件**：
- `visualization/src/features/memory/MemoryGraphView.tsx`（新建约 200 行）
- `visualization/src/App.tsx`（添加路由）
- `visualization/package.json`（添加 react-force-graph-2d 依赖）
- `tinysoul/gateway/endpoint/memory_routes.py`（可能需要修改约 40 行）

**验收标准**：
- [ ] Memory 关系图谱正确显示
- [ ] 节点按类型着色
- [ ] 节点大小按入度调整
- [ ] 点击节点显示详情面板
- [ ] 详情面板显示入边/出边
- [ ] 可导航到相关节点
- [ ] 力导向布局正常
- [ ] 缩放/平移流畅

**工作量**：1 天

---

## 阶段三：Memory 搜索与过滤（可选）

**目标**：提供 Memory 搜索和过滤功能，快速定位文档。

### 3.1 在 MemoryGraphView 中增加搜索框

```typescript
const [searchQuery, setSearchQuery] = useState("");
const [filterType, setFilterType] = useState<string | null>(null);

const filteredGraph = useMemo(() => {
  let nodes = graph.nodes;
  let links = graph.links;
  
  // 按类型过滤
  if (filterType) {
    nodes = nodes.filter(n => n.type === filterType);
    const nodeIds = new Set(nodes.map(n => n.id));
    links = links.filter(l => nodeIds.has(l.source) && nodeIds.has(l.target));
  }
  
  // 按关键词搜索
  if (searchQuery) {
    nodes = nodes.filter(n => 
      n.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.content?.toLowerCase().includes(searchQuery.toLowerCase())
    );
    const nodeIds = new Set(nodes.map(n => n.id));
    links = links.filter(l => nodeIds.has(l.source) && nodeIds.has(l.target));
  }
  
  return { nodes, links };
}, [graph, searchQuery, filterType]);
```

**工作量**：0.5 天

---

## 总体工作量

| 阶段 | 内容 | 状态 | 工作量 |
|------|------|------|--------|
| 一 | Home 资源展示优化 | ⏳ 待执行 | 1 天 |
| 二 | Memory 关系图谱 | ⏳ 待执行 | 1 天 |
| 三 | Memory 搜索与过滤 | 🔵 可选 | 0.5 天 |

**必做**：2 天  
**可选**：0.5 天

---

## 验收清单

### 阶段一验收
- [ ] Home 页面创建
- [ ] 左右分栏布局
- [ ] 只读展示（无编辑功能）
- [ ] "在 Settings 中编辑"按钮功能正常

### 阶段二验收
- [ ] Memory 关系图谱显示正常
- [ ] 节点颜色/大小正确
- [ ] 点击节点显示详情
- [ ] 详情面板功能正常
- [ ] 力导向布局流畅

### 阶段三验收
- [ ] 搜索功能正常
- [ ] 类型过滤功能正常
- [ ] 过滤后图谱更新正确

### 整体验收
- [ ] TypeScript 类型检查通过
- [ ] 不破坏现有功能
- [ ] 性能无明显问题
- [ ] 符合 AGENTS.md 设计边界

---

## 风险与缓解

### 风险 1：后端接口缺失

**缓解**：
- 先检查后端是否已有 `/api/v2/home` 和 `/api/v2/memory/graph`
- 如需新增，与后端 agent 协商或提交需求文档
- 提供 mock 数据降级方案

### 风险 2：关系图谱性能问题

**缓解**：
- 限制节点数量（如最多 500 个）
- 提供分页或按需加载
- 优化力导向算法参数
- 考虑使用 WebGL 渲染（react-force-graph-3d）

### 风险 3：react-force-graph-2d 依赖冲突

**缓解**：
- 检查 package.json 现有依赖
- 考虑使用 vis-network（替代方案）
- 或使用 D3.js 自行实现简单力导向图

### 风险 4：违反架构边界

**缓解**：
- 严格遵守"只读"原则
- 不提供任何编辑按钮（除了跳转到 Settings）
- 在底部明确说明只读
- Code review 时检查是否有违规编辑功能

---

## 与其他计划的关系

- **依赖**：无
- **优先级**：P3（可视化增强，优先级较低）
- **后续**：为 Home/Memory 提供更丰富的可视化能力

---

## 改动效果

### 用户体验提升
- Home 资源集中浏览，快速定位
- Memory 关系一目了然（图谱）
- 快速导航到编辑入口（Settings）
- 符合架构设计，避免误操作

### 技术指标
- 不违反 AGENTS.md 设计边界
- 保持前后端职责清晰
- 关系图谱流畅（力导向算法）
- 不增加显著 bundle 大小

---

**计划结束**
