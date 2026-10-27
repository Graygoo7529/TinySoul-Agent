## 联调和轨迹优化


## Doing
- 用 openrouter：hakimi4、gpt l6、deepseek 和 grok；全面真实 api 测试
- gpt luna6 opencode 验证 其图片输入、JSON、工具调用、推理回放、缓存创建和命中等
- 检查 skill meta 在 context 中的呈现和 skill top/reference 正确加载
- Observation 级别，只设置 normal/verbose，避免烦复的配置
- 扁平目录结构：此外，可以考虑的是，当前 tinysoul 下几个大模块 agent/kernel/environment 等划分非常合理，不过模块内部目录结构可能有些扁平，可以考虑划分更多有层次地子包维护管理
- 调试输出：梳理终端的调试输出，可考虑仅用两种模式（normal/verbose），前端作为主要交互界面，后端控制台输出可以呈现更多、更结构化、更可读的运行时状态便于了解和调试（类似系统 gateway 的终端监控）

 
## WorkSpace
- workspace action & context 段检查，摘要
- workspace ignore 标记/目录（默认不放入上下文快照中）？或者指定类型的文件才放入 eorking 段中？或者可以放入 context 但不需要有摘要？
- workspace 资源 pinned 标记，标记后日切不归档（或考虑复制归档，避免回顾时丢失）；检查归档最长保持时间
- workspace 资源 tmp 标记，并鼓励即时清理
- workspace 类型和动作支持，pdf/ppt/word/excel/scv、图片、二进制
- 图片输入使用场景：workspace 图片和 input 图片；input 复制到工作区，旧 user turn 使用图片引用，可通过工作区工具本轮次读取图片内容（工具把图片按需求读成文本）；当 frame 模型不支持图片时，message stack 不产生异常（不回放 base64），并可用图片工具读取图片为文本内容
- workspace 项目类型（包括权限）

## Coding
- coding 能力由 execution/workspace/sub-agent domain 构成，workspace 写设计，execution 查看项目具体情况，sub-agent 写代码；coding 通过 skill 组合基础能力体现
- 元能力：查看自身编码


## Context
- 在现有 Session 和 TurnTrace 语境段中各加入一段自然语言摘要：Session 总结较早对话中的用户意图、约束、共识和未决问题，TurnTrace 总结当前轮较早的执行过程、关键结果和失败经验。压缩时，模型结合已有摘要、即将折叠的原始内容和近期语境，决定哪些信息值得继续保留，生成供后续模型接续工作的交接说明；程序管理摘要的覆盖范围和预算，保留近期原始消息及历史检索入口。摘要在 session/turn trace 压缩时通过 trap 触发，还需要考虑摘要模型的配置；
- 综合考虑 context 段、哪些触发压缩、哪些值得完整保留、summary 生成与存放等等；
- Plan 模式，Plan 段：跨 turn 保存的 milestone，寄存器/关键状态/核心任务
- 提示现有 user 为 system；system 改进


## Agent Behavior
- 检查 core ask/reply：补充回答如何进入 turn trace；是否允许同时选择选项 + 补充回答；补充回答有气泡；
- 加入 core idle 动作，运行跳过本轮执行
- core 行动：发散方案 redirect / scout（research and exploration）、reason、review
- core 行动：中间叙事（运行中回答）


## Intelligence Interaction
- Tikzjax & markdown 渲染 / Intelligence UI，前端回答内容渲染；代码块设计为插件形式，允许后续 agent 产生更多代码块类型并进行渲染，类似 obsidian 丰富的 markdown 插件改造的渲染支持
- 运行中回答，中间叙事；中间回复模式：core 内部 action 支持不中断 turn 的中间信息呈现
- comment 模式：划线弹出评论框，评论块出现在下方的输入区，可以新增 session map 连接；comment 进入 turn；
- by the way 模式：不进入 turn/session；btw 输出可以和中间回复合并；输入接口？-> 建议新增一个侧页用于显示中间回复和 btw 输入；comment 模式也可与 btw 结合：comment 可以同时出现在正式/btw输入框中
- 桌面精灵模式：by the way 和 中间回复；呈现中间回复，允许快捷 btw 输入，允许点击自动输入 btw：例如询问进度


## Session Map
- 检查会话语义地图，把 workspace 资源、turn 问答和中间推理、相关链接建模绘制为语义地图反馈给模型（background 段）
- 检查 input/append/ask-reply/answer/reason 等动作是否进入 turn（处理链路：对这类 action 有统一标记和处理方式）
- 会话语义地图的维护（turn 前/turn 后/turn 中自发），session orgnize 自然发生和 debug 优化
- 前端 background context 扩展呈现语义地图



## Memory/Home Reflection
- workspace 资源 important，提示 home 整理吸收
- reflection turn input 改进
- reflection 中涉及 llm 的行动和模型使用
- reflection 中 inspect/search 的应用，以及涉及专用模型 embedding/decision 的行动和模型使用
- 检查当前 search 工具的范围筛选、标签过滤、属性过滤能力；以及检查标签和属性添加的时机
- memory 节点类型和连接建立的有效性；考虑 memory-note 是否可以删除；
- memory/home 中的引用（前向/反向）是如何体现和应用的；考虑是否需要 memory 引用结构，还是在文本中写入引用即可
- 检查会话上下文中 memory target/current/latest 的出现，清理 business day 语义
- home reflection 时 home agent/skills/reference 确认/改写
- 日常运行中 home 积极地改写和提交，包括临时 script 提交为长期 script

- 考虑加入 home/knowledge：思考，利用 home 能够在 reflection 期间，对于重要知识组织和优化；knowledge 可作为 agent 自主维护的知识空间；知识具有不同领域、来源、切分长度，彼此可能存在冲突、重复、缺失；agent 应该维护完整的知识空间，以知识点/文档笔记为粒度，对知识粒度、引用（关联）即时更新，最终形成有特征、聚类、图谱的知识空间
- 两个问题：（1）如何避免 search 时 skill/agent 混淆？让 home 更多地承担行为指引而不是内容知识会不会更加合理？
- （2）若加入，如何即时、自发地进行有结构、有层次的组织和切分（文档级别的拆分、再整理、清理或重构），以及相互引用的链接？

- skill 迁移 openclaw home 文档 (skills)、gpt、kimi 的好的 skills


## Libraries
- library 作为用户接口；libraries 与 agent 自行维护的 memory/home 存在区别，memory/home 只会有纯文本可读的数据（md、py），但 libraries 存在多模态数据类型；应考虑在存入 libraries 时就对存入数据进行解析，例如 onlyoffice 2 md、图片 2 description；值得考虑得是，workspace 把图片和文档视为同等存在，但 libraries 可能需要考虑将图片作为文档的一种附属（但也应该允许孤立的图片）；因为，例如一篇 pdf 解析出多个图片，或者一个 md 内嵌多个图片，把这些图片同时传入 libraries 参与检索不是好的策略；更进一步的设计时，对 libraries 的文档建立更抽象的文档概念；在试图传入 pdf 时，将其解析为 md、同时将关联的图片嵌入在 md 里，此外对图片进行识别，把图片包含的内容转为可检索的文字也写到 md 里，最终以 md 作为参与这一份文档检索的文本依据；之后，生成并传入这份文档的资源标签/属性/摘要等元信息，打包原始 pdf、md、关联图片）完成上传，而当下载这份文档到工作区时，可以考虑下载这份文档的原始 pdf 或全部已解析内容；
- workspace 资源 to-library 收藏标记（手工），library 似乎可以独立于 home；
- 手工或推荐生成标签/属性（可以在用户要求收藏工作区文件时填写标签）；
- 工作区即时收藏；无需显示地上下文挂载，可以由前端呈现知识库，并由用户提供收藏链接（类似 chatgpt 网页版）；应参考 omnibox 多模态知识库和 chatgpt 知识库，允许用户提交内容到 libraries，由 agent 解析、标记和检索；
- library 可以在检索后拉取到当前工作区中；实施基于 tag/其它方案的搜索；




## MCP/ACP 和相关功能接入
- ACP Subagent 和状态呈现
- Execution 状态呈现
- 后台 browser 状态呈现
- Ego lite
- Openai-search
- Opencode Hosted Web Search
- DeepSeek Search
- Web-fetch
- Web-star：基于类型给出搜索域/（kimi）数据库/推荐的核心网站（课程）：如 斯坦福/MIT课程资料或课程笔记/Arxiv  
- Star：一个”收藏夹“，让 agent 去记忆一些”好用“的网站，可以走 skill；优秀的数据站点（去检索或寻找资源和信息）；
- Learning：主动找一些学习内容，优秀的学习网页、知识星球、公众号、博客进行探索、推送、学习
- Kimi Datasource 
- Maths
- Search/font-icon / ppt / scv skill
- Email
- Image Gen
- Computer Use


## 前端优化
- markdown 不要求使用严格换行
- 涉及 markdown 的复用性
- markdown 内容交互可复制
- 对话输入框 markdown 实时渲染和自动扩展
- 上下文用量、运行方案、k/m 单位、当前模型额度提示；上下文窗口配置和运行时使用情况
- 网页 URL 打开外部浏览器
- 支持拖拽图片/PDF 等到目录树，自动创建 workspace 资源；workspace 即时渲染，按标签筛选
- 右键目录操作语义
- 桌面精灵：形象设计和 grok bot 风格连贯生动的动画；
- 桌面精灵：双击展开对话或悬浮球；单击快速输出（运行中-btw 进度；闲置-问候或额外的 btw 输入）；
- cycle 顶栏（cycles 视窗也可以展示桌面精灵，复用）
- 后台 bash/terminal 状态和执行情况
- 后台（内置）浏览器页面和协调操纵
- 后台 ACP/MCP 连接和运行中的情况


## 成熟方案研习
- 参考 codex/deepseek harness/kimi code 等源代码进一步优化现有系统


## 主机部署和迭代优化

- 在主机部署后端，在远程笔记本使用前端（跳过公网服务器中转代理请求）
- 数据目录备份指令
- 开发版本快速更新至部署版本：前端可配置一个便捷更新选项：先可选地提示下载 home/memory，然后后端执行 github 项目源码拉取和更新，完成快速更新迭代
