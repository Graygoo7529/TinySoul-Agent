# Configuration

## Read

- `GET /v1/config`：activity、sources、effective fields、Runtime generation/activation 和 process shell projection。
- `GET /v1/config/catalog`：Infra 维护的 surfaces、field groups、collections、field/document descriptors、choices 和 references。
- `GET /v1/config/actions`：当前 Runtime Generation 的 Action domain/action 语义、enabled/available、runtime policy、schema/backend、source binding。

Action catalog 是配置页面的运行时投影，不是聊天 Action API；它由当前 Generation 的 ActionEngine 生成，Endpoint 不缓存。

## Mutation

`PATCH /v1/config` 接受 `operations` 数组。每项是：

```json
{"op":"set","source_id":"project:configs/llm/models.toml","path":"llm.models.primary.provider","value":"openai"}
```

或：

```json
{"op":"delete","source_id":"project:configs/llm/models/custom.toml","path":"llm.models.custom.adapter_options"}
```

`set` 的 value 是不含 null 的递归 TOML/JSON value；`delete` 不携带 value。未知 op、缺失/多余字段和 `set(null)` 返回 `422 request.invalid`。PATCH 在 idle 时完成候选校验、持久化和 Runtime Generation 激活；活动 Turn、Maintenance Turn、daily transition 或既有 activation 返回 `409 config.activation_unavailable`。没有独立 validate/apply endpoint，也不要求 revision。

`.env` 作为 `dotenv` source 读取和写入；dotenv mutation 值必须是字符串。进程环境和进程外壳配置可读但不可由该 endpoint 改写。
