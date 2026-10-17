# Presentation

这些接口读写当前项目的展示配置并读取共享资产，采用既有 Bearer 鉴权和错误 envelope。绑定范围为项目；不要求 Agent 空闲或 ready，不触发 apply/reload，也不携带 generation/day/Turn 句柄。

## 配置文档

`GET /v2/presentation/configs/{document_id}` 和 `PATCH /v2/presentation/configs/{document_id}` 当前支持 `interface`。

GET 返回：

- `id`：`interface`。
- `path`：相对项目 presentation 目录的 `configs/interface.toml`，用于说明来源。
- `exists`：物理文档是否存在。
- `values`：当前界面值。
- `defaults`：同形状的 owner 默认值，供恢复默认操作使用。

| values/defaults 字段 | 允许值 |
| --- | --- |
| `theme` | `light` / `dark` |
| `font_sans` | `inter` / `system` / `serif` |
| `font_mono` | `jetbrains` / `system` / `cascadia` |
| `font_size` | 整数 12–18 |
| `line_height` | 数值 1.3–1.9 |
| `density` | `compact` / `comfortable` / `roomy` |
| `reduced_motion` | boolean |

PATCH 示例：

```json
{"changes":{"theme":"dark","font_size":16}}
```

changes 至少包含一个已知字段，字段不可为 null。服务读取当前文档并仅覆盖提交字段，校验后保存，返回完整 GET 形状；同一字段最后成功写入生效。不传绝对路径、source_id、revision 或 Agent mutation。

文件缺失时 GET 返回 `exists=false` 和默认值，不写文件；首次有效 PATCH 创建文档和父目录。读取失败返回错误，不回退并写入默认值。恢复默认通过提交 defaults 完成，不删除文件。结构化写入会重新排版 TOML，不保证原注释保留。

其它客户端重新读取后取得最新值；没有展示配置变更的 WebSocket 事件或实时推送。

## 共享资产

`GET /v2/presentation/assets` 返回 `{"items":[{"path":"images/example.png","media_type":"image/png","size":68}]}`。路径相对项目 `presentation/assets/`，按路径排序；目录缺失返回空 items。

`GET /v2/presentation/assets/content?path=images%2Fexample.png` 返回原始字节、Content-Type、attachment Content-Disposition 和 `Cache-Control: no-store`。目标必须位于 assets 根目录内，读取受 Endpoint 的 `max_resource_bytes` 上限约束。请求不支持 Range 或上传。

前端经现有 transport 加 Bearer 头读取 Blob，再生成预览/下载 Object URL；token 不进入 URL。资产 path 是该接口内的相对地址，不是 Workspace ref 或模型资源引用。

## 错误

| HTTP / code | 语义 |
| --- | --- |
| `401 auth.unauthorized` | 缺少有效鉴权 |
| `422 request.invalid` | 请求形状、空 changes、未知字段或字段值不满足协议 |
| `422 presentation.invalid_config` | 项目 TOML 无法解释或不符合界面配置类型 |
| `422 presentation.invalid_path` | 资产地址无效或越出目录 |
| `404 presentation.not_found` | 未支持的文档 ID 或不存在的资产 |
| `413 presentation.too_large` | 资产超过读取上限 |
| `500 presentation.io_failed` | 项目文件读写失败 |

details 可包含无效字段的 `field`，不返回原始异常、绝对路径或文件正文。这些失败停留在请求边界，不改变 Agent Runtime 控制流。

机器契约见 [配置 schema](contracts/schemas/presentation-config.json)、[资产 schema](contracts/schemas/presentation-assets.json) 及 [配置示例](contracts/examples/presentation-config.json)。
