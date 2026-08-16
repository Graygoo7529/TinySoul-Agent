# Visualization 对接

Visualization 只通过 `TinySoulClient` 访问 Endpoint。客户端按领域分层：

```text
client.runtime
client.maintenance
client.events
client.configuration
client.workspace
```

传输、Bearer、JSON/error 和 binary headers 由 `api/transport.ts` 统一处理；`api/events.ts` 保留独立 WebSocket 生命周期。`useBackend` 负责连接发现、身份校验、replay 后挂载事件流和状态恢复，不复制 Runtime Generation 或业务事实。

Settings 使用 `configuration.status()`、`catalog()`、`actions()` 并行读取。配置 PATCH 成功后由 store 再读 status/actions；写入入口使用后端同形的 `set`/`delete` union，写值经过非 null `ConfigValue` 边界。Workspace hooks 只调用 `client.workspace.*`，BinaryPreview 保留 blob read，Workspace client 保留 blob write。

Maintenance、Composer 和 event recovery 分别使用对应 domain client。所有 API wire DTO 位于 `src/types/` 的 runtime、maintenance、events、configuration、workspace 子模块，`types/index.ts` 只作 barrel；UI view model 不混入 Endpoint wire type。
