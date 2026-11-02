TinySoul-Agent 设计理念：小结与规划

vibe、设计思考、一直进行着的尝试

（1）组合式上下文和模型链
内部协议
标准四大协议 sdk
adapter/provider 思考、推理回放、断点
模型任务与模型链，适用于不同的任务（如 gemini 擅长讲解）

（2）组合式上下文和插件式上下文构造
背景（turn 内相对稳定）、trace（turn 内时序事件响应）、working（最新状态）
上下文插槽和插件式注册构造

（3）上下文的检索和按需载入
上下文压缩和追溯
inspect/search 两种跨越插件的统一语义（无中生有和渐进披露）

（4）agent sdk：环境与事件响应
user append、ask、reply
进程状态，wait 与定时/信号量唤醒
工作区监听
子智能体返回

（5）agent loop 
三段式
mount skill
可观测性

（6）session 会话
以 turn 为中心，session 作为 background，没有显示的会话区分，一天就是一个 session
session 中的会话线性历史和分支线索图
session 和日切

（7）memory/home reflection
memory 类型和生命周期
home 类型和生命周期
进行中

（8）能力扩展
mcp
acp
browser & computer use

（9）主机部署和远程使用
