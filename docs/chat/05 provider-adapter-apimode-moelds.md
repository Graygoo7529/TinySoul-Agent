## 20261019 API 模式和模型映射

请重新阅读 AGENTS.md 整体设计思路与规约，关注干净一致的实现：注意检查现有模块的异常处理流程、现有模块设计思路和代码风格。

下面我们考虑对于 llm 相关配置和任务进行一轮重构，同时涉及文档设计、配置、后端模块和前端表现，请先理解一下问题，有不明确的地方可以继续与我讨论确认，也可以联网探索相关资料。


首先，就我所知，从总体模型调用层面，大约分为几种模型 API 模式/通用适配器： OpenAI Chat / OpenAI Responses /  Anthropic Messages / Google GenAI；利用这些协议，一版可以通过 http + baseurl + key + header(openai bearer、anthropic x_api_key、genai x-goog-api-key)；也可以安装相应的 python sdk，此时可以省略 header，这也是 agent 项目发起模型调用依赖（不直接用 http）；

请进一步理解和分析以下方面：

（1）需要把概念定义清楚，当前项目中有 tinysoul\llm\protocol 侧重于 tinysoul 内部协议；tinysoul\llm\provider\openai_sdk 有点类似刚刚提到的 OpenAI Chat / OpenAI Responses模型 API 模式；此外，kimi adapter 内部似乎也涉及 kimi 模型版本协议；请分析统一目录组织、术语和设计表述的合理方案；此外，后端目前使用 tinysoul\llm\provider，感觉叫做 adapter 更加合适？kimi adapter 内部的 protocol 有没有更合适的名称？

（2）我建议考虑提取通用模型 API 模式对接 tinysoul 内部协议的通用适配器，类似 tinysoul\llm\provider\openai_sdk，同时形成通用 API 模式的通用适配器，类似 openai chat adapter 和 openai response adapter；kimi、deepseek、glm、minimax、gpt adapter 应作为通用适配器的子类，复用通用适配器的适配并定制内部专属配置；对于自定义新 family 模型时，通用适配器也能够提供充分的能力满足其适配需求。

（3）在 provider 配置方面，我发现有些复合 provider 同时提供多个 API 模式，也即说 key 可以只写一次，但可以配置多个支持的 baseurl + API 模式；而当前 provider 支持能力的是以 adapter 为基础表述的（即 provider 声明支持的 adapter，模型声明所需的 adapter，模型配置筛选合适的 provider），导致为 provider 去声明 kimi、deepseek adapter 是繁琐的，更合适的配置逻辑是：provider 声明支持的（多个） API 模式+ 该模式 baseurl，模型依然只需声明所需的唯一 adapter，但判断合适的 provider 是基于该 adapter 所基于的 API 模式或通用适配器来觉得的；例如，deepseek 模型需要 deepseek adapter，那么什么支持 openai chat 模式的 provider 都可用，自定义模型使用通用 response adapter，那么支持 openai response 模式的 provider 都可用；此外，有些 provider 还需要自定义额外 header 的配置选项；

（4）在模型配置方面，进一步理解 adapter option、request override 的含义，一是当前 采样温度 似乎放在 request override，你觉得采样概率概率也放在 request override 更合理？另一方面，adapter option 可能也需要重构或进一步设计并同步前端：具体来说，model 使用唯一 adapter，adapter 可以是一个通用 adapter，也可以是一个具体 adapter，如 kimi，但它们都属于一个 API 模式；有就是说，adapter option 由 API 模式或更专用的 adapter 内部带来，这一点也可以分层使配置中可用的 adapter option 来源在设计上更统一一致；同一种 API 模式一般会带来类似的可配置项，如思考模式或思考强度、推理状态、提示词缓存等方面，而具体 adapter 又可能增加更多可配置内容；这些可配置项应该根据 API 模式和 adapter 选择合理呈现；此外，当前 adapter option 思考强度建议调整为输入一串以 , 分隔的字符，如 (high,xhigh,max)，同时在模型顶层选项根据字符选择一个思考强度如 xhigh；

请进一步分析和设计干净、一致的模型配置和接入方案，本轮重构可以先以改造现有 provider/model 为目标，但整体架构和理念必须基于 API 模式重新设计；你可先对于 OpenAI Chat / OpenAI Responses /  Anthropic Messages / Google GenAI 这四中 API 模式进行充分的探索和理解，特别是他们所支持对于模型思考强度、推理状态和提示词缓存的配置和调用思路；你可以安装所需 python sdk，也可以把对于 API 模式的调研分析写到 reference\api_mode
