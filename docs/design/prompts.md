# 固定模型文案设计

`tinysoul/prompts` 是随代码发布的 Python 内容包，集中维护框架编写、设计给模型阅读的固定文案。维护者可以从内容定义直接找到消费位置；实际消息、任务和业务决策仍由原 owner 组织。

## 所有权与依赖

内容按 LLM、Kernel 子模块、插件及 User 情景分组，保存任务指引、代码定义的工具说明、自然语言展示包装和可修正局部反馈。静态内容使用字符串或不可变 tuple；动态文本函数接收明确的基础类型，只插入调用方准备好的值。

内容包不导入业务模块，不读取配置、文件或服务，也不持有运行状态。实际消费者显式导入自己的 owner 内容模块；这种内容依赖不改变既有业务依赖方向，不通过内容包绕过 owner 边界。没有独立装配门面、动态发现、模板注册或内容加载生命周期。

## 模型展示与失败

业务 owner 决定可见时机、消息 role、顺序、label、refs、工具范围和输出约束。Context 继续定义 TaskPrompt 与来源协议，Loop 组合 Phase 提示，Action 与领域 Builder 准备局部输入并解析资源；Reflection 选择情景指引。模型请求中的 MessageOrigin 仍指向实际业务来源，源码路径不成为模型资源身份。

retrieval/JEV 的选择指令和问题、Web worker 的供应商 system 提示、ACP 引用包装、LLM 的工具结果包装也在内容包中管理，但它们保留各自请求出口，不统一套入 TaskPrompt。

问答叙事、Session 的 Turn 分隔和交互标签、引用目录及 Inspect 的读取范围说明也由所属文案模块维护。`kernel.interaction` 从类型化问题和回答补全选项正文、说明与 comment；Session 从同一组事实生成历史叙事。ActionResult 的可读文字独立于结构化 payload；foldable 结果还可提供精简投影的文字。文字不能反向成为事实解析来源，也不能替代应保留的动态反馈、完整问题选项或实际读取范围。

局部失败文本通过既有 TaskFailure、PhaseFailure、ActionLocalFailure 或 owner 的结构化结果进入模型。校验、失败分类、异常捕获、取消与 Runtime bridge 留在原 owner。Action owner 应区分已整理的稳定反馈、动态约束/结果和内部诊断；不以 `str(exc)` 的语法形式判断可见性。动态诊断保留在结构化摘要中，不把原始异常、traceback 或供应商原始正文传给模型。内容包不接收异常对象，不新增失败枚举、全局恢复策略或空内容降级。仅供存储、SDK、日志和 Runtime 诊断使用的文字不属于提示文案。

## 独立内容来源

Action Catalog 的语义属于可配置能力定义，继续由项目 TOML 和 Action loader 管理。内容包提取代码中的固定说明及包装，不保存 Catalog 副本，也不改变它的配置与生效语义。

Home 继续拥有身份、偏好和 Skill；运行期间接受的用户输入、资源正文、模型输出及外部工具定义由各自 owner 提供。schema 键、工具 identity、引用/ref、状态、失败原因和事实投影也留在原协议中，不能为了消除字符串字面量而挪入文案包。

## 维护与验证

[内容导航](../../tinysoul/prompts/README.md) 按 owner 标明实际可见位置，定义旁的注释定位消费函数。修改固定文字时沿显式引用检查消费者；涉及输出约束、输入限制或结果反馈时，同时核对 schema、解释器、实际配置值和 payload/feedback/constraint 的真实传递，不另存重复协议。提取工作不得把动态配置或执行结果压缩成通用句子。

依赖测试保护内容包与业务 owner 的边界；组合测试保护角色、块顺序、Skill 来源及动态内容传递。自然语言措辞不做重复快照。Python 模块随既有包发现机制发布，安装验收与完整本地门禁验证真实消费路径。
