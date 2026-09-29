# Endpoint v2 contract fixtures

来源：`docs/endpoint/contracts/examples/`（后端真实捕获并脱敏的响应样例）。

基线提交：`c479ca0`（docs: refine visualization frontend implementation and acceptance plan）。

注意：

- 样例中的 id、时间戳与 continuation token 已被归一化，仅供结构参考，**不能发送到真实后端**。
- `resource-resolve` 只有 schema（`docs/endpoint/contracts/schemas/resource-resolve.json`），没有专门的 example；相关结构参考 `memory-fragment.json`（ResourceResolveResponse 实例）与 `runtime-status` / `context-overview` 中内嵌的 locator。
- `home-fragment.json` 与 `home-fragment-end.json` 是同一个超长单项的首页与末页，**不是相邻页**；中间序列在后端契约测试中消费。前端测试须另构造符合协议的短分片用例，不能直接拼接首尾。
- `capabilities.json` 捕获的是未配置 ACP/MCP 的目录；`model-observation.json` 是一条 Observation 事件，不是页响应。
