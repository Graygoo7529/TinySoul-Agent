## 全面设计和架构重构
这是一次彻底地、大范围地、无需向后兼容的全面重新设计、清理冗余设计和重构；

对现有代码的层次进一步划分，上下层次之间提供 agent/sdk api 风格的清爽调用和依赖解耦，不同功能范畴之间提供插件式的通用注入和内聚能力可维护、可替换性。

以 agent 概念出发，将一切定义为输入、输出和 agent 状态的改变；例如，app/gateway 通过接口输入配置启动 agent /重启/查询状态，以及发起一次 turn（用户对话、记忆维护、home 维护）；将 agent 置于运行环境之中，可以看作一个事件驱动的系统（可以考虑 dds 消息的解耦），使得 agent 能够收集感知环境状态、对环境进行操作，也可以接收用户追加输入，订阅环境发生的变更，暂停 agent turn 并于用户交流对话，执行脚本或 shell 指令或派遣 sub-agent，对于后台任务以一定间隔唤醒自己的下一个 cycle，或者等待后台任务发出的事件来激活下一个 cycle。

进一步地，考虑 agent 内部封装，kernel 依然是 turn-cycle-stage-loop 和 context 语境维护；其中，background context 在 before turn 即有所准备，且允许在 turn 期间通过 异常触发（如上下文压缩）或 stage1 tool 变更，background context 呈现堆的形态（冰山理论），堆顶是线索，并可向下按需追溯； interaction trace 以栈的形态，在当前 turn 运行中的追加新的消息；workspace 呈现最新的工作状态（可用的本地资源、待办和里程碑，里程碑类似寄存器一样的备忘数据或真实值）；
在 agent 内部另一个关键架构设计是，kernel 负责利用 context 中不同的语境段，但 kernel 本身不需要知道和维护 context 不同语境段的内容和含义；依赖反转，外围插件式申明 context 语境段内容和 kernel 的内容使用方法和收集方法（turn 前/中/后），并在外围模块内部维护属于这个段的相关内容和结构，内容的维护和管理依靠外围具体的功能模块。

会话历史：对于 session map 的构建，建议先设计结构化方法，在 turn 结束时保存所需 trace（问答、追问、补充输入、推理 action、所设计的 links），可以采用无模型方法固定构建，并增加 core action 支持新 turn 开始时对前一个成功的 turn 进行整理；此外，建议考虑是否需要引入额外的形状，而不仅仅是通用 Heap 来支持 session 语义地图；压缩时也不要过度折叠 session 段，因为 session 语义地图承担了会话历史的作用，还是比较重要的（在 session 段过大时才有限折叠）；

记忆与知识沉淀：把 maintenance 重构为  Reflection，但还是建议区分 专属的 memory_reflection/home_reflection Domain（不合并单一 reflection，同时与常规运行的 action domain 分开，仅在相应的  memory/home Reflection 时使用）；Memory Reflection 可以删除 8 步控制器、preview、多文档事务与 CAS、evision/activation_count/session_revision/digest，做更加轻量的 memory_reflection；Home 还是需要 review，白天 turn 会通过常规 home domain 改写 home 副本，home_reflection actions 可以检查副本 diff，查看 diff 详情，接收/拒绝/改写 diff；可以不引入 git；最关键的设计是：User Turn 仍不写持久 Memory、不直接更新 Home，持久 memory 和 home 更新通过 reflection 插件以及相应的专属 domain 实现。


## 联调和轨迹优化


## 局部改进
 - 配置切换
 - 备份指令（zip），reset 不影响
 - 允许整理当日 memory（当前 skip）
 - 检查或改进 milestone 提示词，类似寄存器一样的备忘数据或真实值
 - Observation 级别，只设置 normal/verbose，避免烦复的配置


## 前后端对接
 - 前端本地配置
 - 字体可配置
 - 配置页进一步改进界面和交互：检查整体配置页切分，以及每一页中子页的布局和逻辑；检查每一个配置项的意图和意义；检查配置项的可操作性


## 工作区和会话语义
- 检查 skill meta 在 context 中的呈现和 skill top/reference 正确加载
- 检查工作区 digest 含义，避免过于严格工作区约束，工作区行为和提示词优化，digest、revision
- 工作区 外部 link 混入 references（要说明 references 只能放 工作区 links）；Workspace references link 只能是工作区内部的链接，包括在产生回答时

- workspace 类型支持，输入（外部，工作区项目类型）文件夹、pdf/ppt/word/excel、图片、二进制
- workspace 资源 pinned 标记（手工）
- workspace 资源 to-library 收藏标记（手工），library 似乎可以独立于 home
- workspace 资源 tmp 标记，并鼓励即时清理（手工或自动
- 前端支持把 tmp 标记的资源以独立文件夹折叠显示，并支持其它标记的筛选
- workspace 前端文件与目录

- 会话语义地图，把 workspace 资源、turn 问答和中间推理、相关链接建模绘制为语义地图反馈给模型（background 段）
- 前端 background context 扩展呈现语义地图

- 图片输入使用场景：workspace 图片和 input 图片；input 复制到工作区，旧 user turn 使用图片引用，可通过工作区工具本轮次读取图片内容（工具把图片按需求读成文本）；当 frame 模型不支持图片时，message stack 不产生异常（不回放 base64），并可用图片工具读取图片为文本内容


## 智能体行为
- 加入 core idle 动作，运行跳过本轮执行
- 用户追加（当前，是直接加载 query 里面，考虑额外进入 trace 提示收到了新讯息，这样带有先后性）；改造 trace 为消息接收系统/loop 内的事件驱动系统；但需要设计好与工具调用的关联，避免底层回放错误
- 前端回答内容渲染；代码块设计为插件形式，允许后续 agent 产生更多代码块类型并进行渲染，类似 obsidian 丰富的 markdown 插件改造的渲染支持
- 暂停 agent 等待输入（提供可选项+others（允许用户自行输入，可作为追加记录 ask+choice/append submit）；目前，若等待输入后结束 turn，turn 内部记录会丢失，如何让其进入 turn 级别的记录，并使 ask/append/reason/answer 的结果会在 turn end 后被整理


## 长期维护
- 考虑将 home/memory 作为与 user turn 类似，区别只有新增 home/memory maintenance domain 和一条表示需求的 turn input
- tinysoul\maintenance\catalog\maintenance 没有区分 home/memory
- maintenance action 没有类似通用 action 的可配置性，包括模型链：memory_daily；检查 home_search，不要硬编码 home_search 的模型链：若 home_search 是通用 action，应通过通用 action 配置，若 home_search 是 maintenance action，应通过 maintenance action 设置模型链；；初始配置应提供通用 maintenance action 模型链，或直接复用 llm action 模型链，配置界面应区分，但初始配置项可共用
- 阐述 memory-note，加入 home-library
- 工作区提出加入 library
- library 检索和拉取到工作区
- 检查会话上下文中 memory target 的出现
- memory 段专门放一段出现在 session 中的 memory links（每 turn 结束后从 memory action result 中提取），便于快速再次召回

- home maintance 时 home top/skills/reference 确认/改写
- 日常运行中 home 积极地改写和提交，包括临时 script 提交为长期 script，考虑是否以 skill 包的局部的形式；强化对于 home 维护倾向
- 对齐 openclaw home 文档 (skills)
- home library，工作区即时收藏；无需显示地上下文挂载，可以由前端呈现知识库，并由用户提供收藏链接（类似 chatgpt 网页版）；实施基于 tag/其它方案的搜索，可以在用户要求收藏工作区文件时填写标签


## 提示词
- 实现一个 prompts 模块 
- 管理所有内部使用的提示词

### 提示词优化
- 主动提出问题，有想象力和创造力，引导、启发思考和深入交流，主动提出自己的看法
- 对话加入意图 []，如：[赞同]、[提问]、[反对]、[执行]；一次回答中可以有多个意图，有逻辑
- 在思考和回复时结合当日语境、工作上下文、长期记忆、home 知识经验、用户和自己的身份来进行推理和行动
- 不懂的地方搜素或打断进行追问


## 项目与编码
- 建立工作区项目类型（包括权限）
- 子智能体派遣，考虑 acp
- coding 能力由 execution/workspace/sub-agent domain 构成，workspace 写设计，execution 查看项目情况，sub-agent 写代码；coding 通过 skill 组合基础能力体现
- 元能力：查看自身编码


## 前端优化
- markdown 不要求使用严格换行
- 点击会话内链接合理跳转；网页 URL 打开外部浏览器
- 侧边展示 memory
- 侧边展示 home
- 侧边展示 library
- 支持拖拽图片/PDF 等到目录树，自动创建 workspace 资源
- 右键目录操作语义
- 桌面机器人启动对话


## 内部功能接入
- tikzjax
- 图像生成
- openai-search
- 网页搜索：基于类型给出搜索域/（kimi）数据库/推荐的核心网站（课程）：如 斯坦福/MIT课程资料或课程笔记/Arxiv  // ps：我是否应该有一个”收藏夹“，让 agent 去记忆一些”好用“的网站，这些网站如何放到上下文里面？走 skill 还是记忆

## MCP 功能接入
- mcp/expand
- ego lite
- Kimi Datasource 
- 数学等实用工具
- search/font-icon
- 邮箱读取和解读


## 成熟方案研习
- 参考 codex/deepseek harness/kimi code 等源代码进一步优化现有系统


## 主机部署和迭代优化
- 在主机部署后端，在远程笔记本使用前端（跳过公网服务器中转代理请求）
- 开发版本快速更新至部署版本：前端可配置一个便捷更新选项：先可选地提示下载 home/memory，然后后端执行 github 项目源码拉取和更新，完成快速更新迭代
