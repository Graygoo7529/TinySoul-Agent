# MCP 工具发现与调用

ExpandEngine 是 MCP 服务绑定、运行期目录、原始工具定义和结果归一的唯一 owner。四个本地 Action 接入现有 Action/LLM Task；远端工具不成为新的 Action Catalog、Context 段或 Job。连接可以跨 Turn 复用，一次调用始终在当前 Action 内收敛。

## 四动作与同一目录

| Action | 职责 |
|---|---|
| `expand.describe_servers` | 按需取得允许服务及工具摘要，支持服务范围和有界分页 |
| `expand.describe_tools` | 按结构化工具身份列表或完整服务范围取得原始定义，二选一，支持分页 |
| `expand.search` | 以 query 在全局或指定服务目录上执行 seed refinement，使用已配置 LLM/JEV |
| `expand.call` | 对指定 server_id、tool_name 和 arguments 校验并调用一次 |

工具身份固定为配置 server_id 与远端原始 tool_name，不把不同服务的同名工具混同。服务目录不常驻挂载。已知身份可直接 describe_tools；search 已返回完整定义时可直接 call，不要求走完四个动作。单个服务不可用时返回其有限状态，其它服务结果继续可用。

owner 完成一次上游目录分页遍历后才发布本地目录。超过容量、中途失败或分页不收敛时不发布半份列表。目录命中有效 TTL 时复用；列表变更通知使其失效，下一次访问刷新。现代订阅与旧通知由 SDK adapter 归一，监听失败停止监听并使目录失效，不自动后台重连。没有 TTL 的目录在后续访问时重新读取。完整遍历不承诺远端跨页事务一致性。

面向模型的分页按完整定义分组，同时限制条目数和总大小，单个 schema 不拆页。page 只是 owner 内的有界临时引用，操作类型不匹配、目录已换或引用过期时要求重新描述。模型无需管理 revision/digest。各 projection 和调用约束始终派生自同一份目录。

## 有界语义搜索

先应用服务启用与工具选择，再把全部允许、可调用候选的身份、用途、描述和参数摘要放入本 Action 的 TaskPrompt。空候选直接返回事实；候选超过字符上限或完整 LLM Task 超过上下文预算时返回 scope_required 与服务范围提示，由父 Agent 缩小范围。没有隐藏初筛、递归搜索或新向量索引。

来源由 ExpandEngine 的目录操作提供，公共 SearchSession 使用 expand.search.select 绑定的 LLM/JEV selector。ActionTaskFactory 提供局部 Skill 和可选 Context；MCP 默认 context=none。模型只选择候选 ID，结果映射回真实 mcp:server/tool 身份。完整定义装不下时返回 describe_tools 入口，不提供残缺 schema。Search 的有限结果视图按页返回，后续页不重做选择；服务目录仍归 MCP owner。

输入容量不足反馈 scope_required；必需选择失败不冒充空结果，全部服务器不可用返回来源失败。单服务器失败保留可用候选并说明 coverage 不完整。协议测试验证一次选择、范围、分页和真实定义；真实 JEV 小样本验证了相关工具命中、无关工具排除和空选择，不代表开放规模检索质量。

## Schema、结果与失败

Action 的受限 schema 只校验调用外壳；远端 inputSchema/outputSchema 交 infra/json 的标准 validator。支持默认 2020-12、2019-09 和 Draft 7，拒绝未支持的必需 vocabulary、非法 schema 和无法解析的引用；引用只在给定 schema 内解析，不联网抓取。超过完整定义上限的工具明确不可调用。协议 header 等传输语义由 SDK 处理。

短文本与结构化内容有界返回，相同内容不重复投影。长文本、图片/音频和嵌入资源经 Workspace 写成 Link；总反馈过大时保存 result.json。外部 resource URI 保持外部身份，不自动抓取、不伪装 Workspace。原始 stdio 日志和诊断不进入 Context。

isError、参数不符、服务不可用和协议能力不足为局部结果；Workspace 写入失败、配置与必要关闭失败保留 owner bridge。写调用超时或断流返回结果未知，可能已产生副作用，不自动重放。取消交 Action 执行事实处理，不伪造工具响应。现代 input-required 自动续交次数为零，不启动隐藏的授权、sampling 或 elicitation 流程。

## 用户配置与生命周期

安装 TinySoul 的 `.[external-tools]` extra，使用 MCP SDK 2.2.0 和 jsonschema 4.26 系列以上的支持范围。用户自行安装本地服务或准备远程 URL，然后通过正常配置 include、候选 PATCH 与空闲 reload 加入服务：

```toml
[capabilities.expand.servers.notes]
enabled = true
description = "读取个人笔记"
transport = "stdio"
command = 'C:\Tools\notes\python.exe'
args = ["-m", "notes_mcp"]
cwd = 'D:\Notes'
env_refs = { NOTES_API_KEY = "NOTES_MCP_API_KEY" }
tools_default = true
tools = { "notes.delete" = false }

[capabilities.expand.servers.docs]
enabled = true
description = "检索团队文档"
transport = "streamable_http"
url = "https://mcp.example.com/mcp"
header_refs = { Authorization = "DOCS_AUTHORIZATION" }
tools_default = false
tools = { search = true, read = true }
```

配置位于 `configs/capabilities/expand.toml`。工具名中的点与数字原样保存在完整 tools 映射中；tools_default 提供域内默认选择，单项覆盖同时约束发现、描述、搜索与调用。普通 domain/action visibility 控制情景选择，不能绕过服务或工具硬边界。User/Home Reflection/Memory Reflection 复用这套能力，不因此获得其它 owner 的专属写权限。

stdio 直接使用 argv 和受控进程；cwd 省略时使用项目根，相对位置以项目根解析。Streamable HTTP 可连接 localhost 或远程服务；TinySoul 只拥有本地 client，不拥有远端服务进程。env/headers 用于非敏感固定值，env_refs/header_refs 引用 ConfigEnvironment 变量并覆盖同名固定值；Authorization 使用包含认证前缀的完整值。配置投影只暴露引用名称并脱敏被引用环境值。

候选检查只验证配置、本地依赖、可执行文件和引用，不启动进程或联网枚举。第一次操作才建连，服务新工具随下一次目录刷新出现，无需编写新的 Action TOML。日切及世代关闭释放连接与目录，后续按新绑定重建。没有自动服务注册、包安装、旧 SSE 传输、OAuth 登录、resources/prompts 浏览或 MCP Tasks 平行任务体系。
