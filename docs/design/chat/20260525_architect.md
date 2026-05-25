graygoo:
我目前的规划是这样的：不再是传统 Agent 会话式的用户-助手一股脑塞进上下文，而是以 query-loop 为核心：（1）每天维护一个 session，建立这次 session 内的语义地图；（2）维护长期的 memory，分为知识记忆和情景记忆，分别使用结构化存储和语义存储，情景存储可带有时间标识；（3）维护 home/agent，存放 skill、agent.md 等；（4）在 query-loop 开始前，基于 session、memory、home/agent 去筛选工作区和上下文；（5）语义地图和记忆可以通过命题逻辑和位于关系进行抽象和推演；（6）每天会根据对话内容维护多个工作区和行为草案 draft；（7）行为草案 draft 是长期固化 skill 的 diff；（8）渐进式披露，工作区引用、skill 和 draft 引用、home/agent 引用通过特殊标记在上下文中标识，使用相对路径；（9）每天在固定时段根据当天的 session、draft 等对 skill、memory 进行更新。


codex:
我建议保留这个方向，但要注意一个核心风险：**不要一开始就把 memory、semantic map、逻辑推演、skill 固化、每日更新全做成复杂系统。先把“引用、筛选、记录、回放”这条主干打通。**

**总体判断**
你的 9 点规划可以成立，尤其是这几条很关键：

- 以 `query-loop` 为核心，而不是以会话 transcript 为核心，这是对的。
- 每天维护 session semantic map，比简单 summary 更适合长期 Agent。
- knowledge memory 和 episodic memory 分开是必要的，二者写入策略完全不同。
- `home/agent` 作为 Agent 自我结构目录也合理，适合放 `AGENT.md`、skills、偏好、工具说明。
- draft 作为 skill 的 diff，这个设计很好，能避免 Agent 直接污染长期能力。
- 渐进式披露 + 特殊引用标记，是控制上下文膨胀的关键。

我会调整的地方是：**“每天一个 session”可以作为默认时间边界，但不要作为唯一任务边界。**  
实际任务可能跨天，单日也可能有多个项目。所以最好同时有：

- `daily_session_id`
- `task_id`
- `workspace_id`
- `query_id`

这样日记、任务、项目不会互相混淆。

**推荐从哪里开始**
从 **Context Fabric** 开始，也就是“资源引用 + 上下文筛选 + 持久事件记录”这一层。

原因很简单：memory、semantic map、draft、skill 固化，最终都依赖同一件事：系统必须知道某条信息来自哪里、何时出现、为什么被选进上下文、后来产生了什么影响。

建议第一阶段做这几个最小能力：

1. **Persistent Event Log**
   把 query、action、LLM step、workspace 引用、输出结果都落盘，带稳定 ID。

2. **统一引用模型**
   例如：
   - `@workspace:project/path/file.py`
   - `@session:2026-05-25/node/xxx`
   - `@memory:knowledge/xxx`
   - `@memory:episode/xxx`
   - `@skill:python_debug/SKILL.md`
   - `@draft:2026-05-25/skill_x.patch`

3. **ContextBundle**
   在 `QueryLoop` 开始前增加一个 prelude：
   `query + session map + memory + home/agent + workspace index -> ContextBundle`

   之后原来的 Step1/Step2/Step3 不直接面对所有信息，只面对被筛出来的 bundle。

4. **Session Semantic Map**
   先不要做复杂逻辑推理，先做节点、边、命题、证据引用：
   - node：人、项目、文件、任务、概念、偏好
   - edge：属于、依赖、修改、提到、解决、阻塞
   - proposition：一句结构化事实，带 source refs、confidence、timestamp

5. **Nightly Consolidation**
   固定时段只做“候选更新”，不要一开始全自动永久写入：
   - session -> memory candidates
   - action records -> skill draft candidates
   - repeated user preference -> knowledge memory candidate
   - successful repeated workflow -> skill draft

**整体设计分层**
我会这样规划：

**1. Inner Loop**
保留现在的 `QueryLoop`：

`choose action -> take action -> update state -> signal/trap`

这是执行内核，不要让它承担长期记忆和全局检索职责。

**2. Context Layer**
新增 `ContextPlanner / ContextBundleBuilder`：

输入：
- 当前 query
- daily session semantic map
- long-term memory
- workspace index
- `home/agent`
- active drafts

输出：
- 本轮需要的 workspace refs
- memory refs
- skill refs
- draft refs
- compact summaries
- context budget 分配

**3. Memory Layer**
分两类：

Knowledge Memory：结构化事实、偏好、规则、技能知识。  
适合 SQLite/JSON schema，字段包括 `content`、`type`、`source_refs`、`confidence`、`valid_from`、`updated_at`。

Episodic Memory：发生过的事情。  
适合语义检索，必须带 `timestamp`、`session_id`、`event_refs`、summary、embedding。

**4. Home Agent Layer**
`home/agent` 可以变成 Agent 的自我目录：

- `AGENT.md`：稳定身份和行为原则
- `skills/`：长期固化能力
- `preferences/`：用户偏好
- `drafts/`：待评估 diff
- `profiles/`：不同任务模式
- `memory_policy.md`：什么能写入长期记忆

**5. Draft Layer**
draft 不只是文本建议，而是有状态对象：

`proposed -> tested -> accepted -> promoted -> deprecated`

每个 draft 应有：
- target skill
- diff
- rationale
- source refs
- expected behavior
- validation result

**6. Consolidation Layer**
每日固定时段运行：

`session events + semantic map + drafts + action results -> memory updates + skill draft promotions`

这里可以先半自动，生成 patch 和报告；成熟后再自动提交。

**关于命题逻辑和位于关系**
这个方向可以做，但建议放在后面。早期不要做完整 theorem prover。先做轻量图推理：

- A 属于 B
- A 依赖 B
- A 修改了 B
- A 解决了问题 P
- 用户偏好 X 在多个 session 中重复出现
- draft D 来源于行为模式 M

推理结果必须保留 `inferred_from`，不要覆盖原始事实。

**最推荐的路线**
我建议按这个顺序推进：

1. 事件持久化和统一引用标记。
2. `ContextBundle` pre-loop 集成到现有 `QueryLoop`。
3. daily session semantic map。
4. knowledge/episodic memory 的 candidate 写入机制。
5. draft 机制和 skill diff 生命周期。
6. nightly consolidation。
7. 轻量图推理。
8. 更复杂的逻辑抽象和自动 skill 固化。

一句话总结：你的设计方向是对的，但关键不是先做“更聪明的记忆”，而是先做 **可追踪的上下文资源系统**。只要引用、来源、筛选、回放这四件事稳了，后面的 memory、semantic map、draft、skill 演化都会自然长出来。
