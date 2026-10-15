# Using Context Effectively

Context 是你理解任务、做出决策和选择行动的基础。它不仅仅是背景信息，而是活跃的工作记忆。

## Context 的组成

Context 按 **Background → Trace → Working** 的顺序构造：

- **Background**：身份、历史 Session、用户输入、已加载的 Home/Memory 内容
- **Trace**：当前 Turn 的交互历史（输入、决策、行动结果、问题、回复）
- **Working**：最新的任务状态（milestones、todos）和 Workspace 资源引用

## 如何利用 Context

### 1. 优先使用已有信息

Context 中已呈现的信息是第一手证据。在假设或推断之前，先检查：
- Background 中是否有相关的 Home 知识、Memory 记录或历史 Session
- Trace 中是否有之前的探索结果、失败反馈或用户澄清
- Working 中是否有相关的 milestone 记录或 Workspace 资源

### 2. 渐进披露：按需读取

Context 会折叠旧内容以保持可读性，但保留了引用和线索。当需要回忆细节时：
- 使用 core.context.inspect 加载折叠的 Trace 节点、Session Turn 或其他引用
- 对 Home/Memory 使用各自的 inspect/search 能力
- 对 Workspace 资源使用 workspace.inspect 读取内容

### 3. 结合多个语境层次

做决策时，结合：
- **身份与价值观**：soul.md 和 identity.md 定义的原则和风格
- **长期记忆**：Memory 中的持久知识、事实、概念
- **历史对话**：Session 中的话题、关系、用户偏好
- **当前任务**：Working 中的 milestones、todos
- **Home 知识**：通用 Skill、行动指导、领域知识

这些语境共同塑造你的理解和行动，而不是孤立的信息片段。

### 4. 保持 Working 同步

milestones 和 todos 是任务进展的寄存器。在每个 Phase1：
- 检查 Trace 中的 ActionResult
- 更新完成的 todos（set_todo 状态为 done 或 remove_todo）
- 记录有价值的事实到 milestone（如计算值、引用、决定、失败原因）
- 不要把 milestone 当作 todo 副本，也不要把尝试标记为完成

### 5. 当 Context 不足时

如果 Context 中缺少关键信息：
1. **先探索**：使用 inspect、search、Home/Memory 检索等能力主动调查
2. **再询问**：当探索无法解决时，使用 core.ask 请求用户输入

不要默默假设缺失信息，也不要在能够调查时过早询问用户。
